#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CreArt 2API Demo Server —— R1
=============================

把逆向得到的 CreArt 协议暴露成一个本地 HTTP 服务，供 demo 页 / new-api 试接。
两种模式（可全局默认，也可逐请求覆盖）：

  mock      本地用 PIL 合成一张【明确标注 MOCK】的占位图，证明前后端管线打通。
            这不是真生成，页面上会打大字 "MOCK"，绝不当真实产出。
  upstream  忠实透传到真实后端 https://api.creartai.com。
            在无合法 AppCheck token 时，后端返回的是完整性占位图——本服务原样透传，
            并通过 X-Creart-Kind / X-Creart-Notice 响应头把这个事实标出来。
            这是「真实可复现」的行为，不是 bug。

端点（与 App 契约一致）:
  POST /api/v2/text2image
  POST /api/v2/image2image
  POST /api/v2/upscale
  GET  /health
  GET  /probe        后端存活 + 完整性门禁证据(JSON)
  GET  /              demo 页面

启动:
  python demo_server.py                    # 默认 mock，:8940
  CREART_MODE=upstream python demo_server.py
"""
import os
import time
import io
import json
import threading

from flask import Flask, request, Response, send_from_directory, jsonify
from PIL import Image, ImageDraw, ImageFont

import creart_client as cc

MODE = os.environ.get("CREART_MODE", "mock").lower()
APPCHECK = os.environ.get("CREART_APPCHECK_TOKEN") or None
PORT = int(os.environ.get("PORT", "8940"))
APP = Flask(__name__, static_folder=None)

_LOCK = threading.Lock()
_STATS = {"total": 0, "mock": 0, "upstream": 0, "integrity_blocked": 0,
          "image": 0, "error": 0, "started": int(time.time())}
_PROBE_CACHE = {"ts": 0, "data": None}


def _bump(kind):
    with _LOCK:
        _STATS["total"] += 1
        if kind in _STATS:
            _STATS[kind] += 1


def _mock_png(prompt: str, w=512, h=512) -> bytes:
    """合成一张带 MOCK 水印的图，证明管线；这不是真实生成结果。"""
    img = Image.new("RGB", (w, h), (18, 20, 28))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(30 + 60 * t), int(30 + 40 * t), int(60 + 90 * t)))
    try:
        font_big = ImageFont.truetype("arial.ttf", 40)
        font_mid = ImageFont.truetype("arial.ttf", 22)
        font_sm = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_big = font_mid = font_sm = ImageFont.load_default()
    d.rectangle([10, 10, w - 10, h - 10], outline=(120, 140, 220), width=3)
    d.text((30, 30), "MOCK", font=font_big, fill=(255, 210, 90))
    d.text((30, 90), "not a real generation", font=font_sm, fill=(220, 120, 120))
    # 简单按 prompt 换色，直观看出参数确实传进来了
    seed = sum(ord(c) for c in prompt) % 255
    d.ellipse([w // 2 - 120, h // 2 - 120, w // 2 + 120, h // 2 + 120],
              fill=(120, 80 + (seed % 120), 200 - (seed % 120)))
    # wrap prompt
    words, line, y = prompt.split(), "", 230
    for wd in words:
        if len(line) + len(wd) > 34:
            d.text((30, y), line, font=font_mid, fill=(235, 235, 245)); y += 30; line = ""
        line += wd + " "
    if line:
        d.text((30, y), line, font=font_mid, fill=(235, 235, 245))
    d.text((30, h - 40), "CreArt 2API demo — MOCK MODE", font=font_sm, fill=(160, 170, 210))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _serve(endpoint_key: str, body: dict, mode: str):
    with _LOCK:
        _STATS["total"] += 1
        _STATS[mode] += 1 if mode in _STATS else 0

    if mode == "mock":
        prompt = str(body.get("prompt") or body.get("promptText") or
                     body.get("imageUrl") or body.get("base64", "")[:24] or "untitled")
        png = _mock_png(prompt)
        _bump("image")
        resp = Response(png, mimetype="image/png")
        resp.headers["X-Creart-Kind"] = "mock"
        resp.headers["X-Creart-Notice"] = "MOCK - not a real model generation"
        return resp

    # upstream: 忠实透传（单次请求）
    try:
        import requests
        method, path = cc.ENDPOINTS[endpoint_key]
        r = requests.request(method, cc.BASE + path, data=json.dumps(body).encode(),
                             headers=cc._headers(APPCHECK), timeout=90)
    except Exception as e:
        _bump("error")
        return jsonify({"error": "upstream_exception", "detail": repr(e)}), 502

    content = r.content
    ctype = r.headers.get("Content-Type", "image/png")
    info = cc._classify(content, r.status_code, ctype)
    kind = info.get("kind", "other")
    _bump(kind if kind in _STATS else "error")

    if not ctype.startswith("image/") and not ctype.startswith("application/json"):
        ctype = "application/octet-stream"
    resp = Response(content, mimetype=ctype)
    resp.headers["X-Creart-Kind"] = kind
    resp.headers["X-Creart-Upstream-MD5"] = info.get("md5", "")
    if kind == "integrity_blocked":
        resp.headers["X-Creart-Notice"] = (
            "upstream returned integrity placeholder: request lacks valid Firebase AppCheck token")
    return resp


def _endpoint(endpoint_key):
    body = request.get_json(silent=True) or {}
    mode = (request.args.get("mode") or request.headers.get("X-Creart-Mode") or MODE).lower()
    if mode not in ("mock", "upstream"):
        mode = "mock"
    return _serve(endpoint_key, body, mode)


@APP.post("/api/v2/text2image")
def ep_t2i():
    return _endpoint("t2i")


@APP.post("/api/v2/image2image")
def ep_i2i():
    return _endpoint("i2i")


@APP.post("/api/v2/upscale")
def ep_upscale():
    return _endpoint("upscale")


@APP.get("/health")
def health():
    return jsonify({"status": "ok", "mode": MODE,
                    "upstream": cc.BASE, "appcheck_present": bool(APPCHECK)})


@APP.get("/stats")
def stats():
    with _LOCK:
        s = dict(_STATS)
    s["uptime_s"] = int(time.time()) - s["started"]
    return jsonify(s)


@APP.get("/probe")
def probe():
    # 90s 缓存，避免 demo 页反复打真后端
    if _PROBE_CACHE["data"] and time.time() - _PROBE_CACHE["ts"] < 90:
        return jsonify(_PROBE_CACHE["data"])
    data = cc.probe()
    _PROBE_CACHE.update(ts=time.time(), data=data)
    return jsonify(data)


@APP.get("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "demo.html")


if __name__ == "__main__":
    print(f"[creart-2api demo] mode={MODE}  http://127.0.0.1:{PORT}  upstream={cc.BASE}")
    APP.run(host="0.0.0.0", port=PORT, threaded=True)
