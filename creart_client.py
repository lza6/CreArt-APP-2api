#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CreArt (ai.aiart.aiartgenerator.creart) v2.7.2 协议客户端 —— R1 侦察版
=====================================================================

本文件是逆向得到的「上游真实协议」的忠实封装。它不是 mock，而是把
libapp.so 里还原出来的端点、方法、请求体字段、鉴权头拼好，直接打真实后端。

已还原事实（证据见 docs/REVERSE_REPORT.md）:
  base            = https://api.creartai.com
  端点(命名空间)   = /api/v2/{text2image,image2image,upscale}
  health          = /health          -> {"status":"ok"}
  鉴权头           = X-Firebase-AppCheck: <Firebase AppCheck JWT>   (唯一鉴权头)
  响应            = image/png 原始字节

关键约束（这是 R1 的核心结论）:
  后端在进入业务逻辑【之前】就做 Firebase AppCheck(Play Integrity) 完整性校验。
  任何一个【不带合法 AppCheck token】的请求（哪怕 GET / 空 body / 坏 JSON），
  都会被无条件返回一张固定的 "Unable to verify app integrity" 占位图(200)。
  合法 token 只能由「官方签名 APK + 通过 Play Integrity 的真实 GMS 设备」实时签发，
  因此本客户端在无真机的前提下，只能复现到「打真后端 -> 拿到占位图」这一层。

用法:
  python creart_client.py probe                 # 探测后端存活 + 完整性门禁证据
  python creart_client.py t2i "a cat"           # 打真实 text2image，落地返回字节
  python creart_client.py t2i "a cat" --appcheck <TOKEN>   # 若你有真机签发的 token
"""
import argparse
import hashlib
import json
import os
import sys
import time

import requests

BASE = "https://api.creartai.com"

# 已由静态分析确认的、后端在完整性门禁失败时无条件返回的占位图 md5
BLOCKED_MD5 = "379426a18eca81366a05cd39a39ea4a7"

# 端点契约。请求体字段来自 libapp.so 的 Dart 字符串（prompt / aspect_ratio /
# style / model / base64 / imageUrl / deviceId / width / height / quality）。
ENDPOINTS = {
    "t2i": ("POST", "/api/v2/text2image"),
    "i2i": ("POST", "/api/v2/image2image"),
    "upscale": ("POST", "/api/v2/upscale"),
}


def _headers(appcheck_token: str | None) -> dict:
    h = {
        "Content-Type": "application/json",
        "User-Agent": "Dart/3.11 (dart:io)",  # App 侧是 Flutter dart:io
        "Accept": "image/png",
    }
    if appcheck_token:
        h["X-Firebase-AppCheck"] = appcheck_token
    return h


def _classify(content: bytes, http_status: int, content_type: str) -> dict:
    """判定一次响应的『语义类别』，用于区分真生成 / 完整性门禁 / 其它。"""
    md5 = hashlib.md5(content).hexdigest()
    if http_status == 200 and content_type.startswith("image/png"):
        if md5 == BLOCKED_MD5:
            return {"kind": "integrity_blocked", "md5": md5,
                    "note": "后端返回完整性占位图：请求未携带合法 Firebase AppCheck token"}
        return {"kind": "image", "md5": md5, "note": "收到 PNG（非占位图）"}
    return {"kind": "other", "md5": md5, "note": f"HTTP {http_status} {content_type}"}


def probe(timeout=20) -> dict:
    """探测后端存活与完整性门禁的真实行为证据。"""
    out = {"base": BASE, "ts": int(time.time()), "checks": []}

    # 1) /health 是否活着
    try:
        r = requests.get(BASE + "/health", timeout=timeout)
        out["checks"].append({"probe": "GET /health", "http": r.status_code,
                              "body": r.text[:200]})
    except Exception as e:
        out["checks"].append({"probe": "GET /health", "error": repr(e)})

    # 2) 业务端点 + 一个正常请求体 / 一个坏 JSON / 一个 GET  —— 证明门禁在解析前
    cases = [
        ("POST valid-body", "POST", "/api/v2/text2image",
         json.dumps({"prompt": "a red fox", "aspect_ratio": "1:1"}).encode(), "application/json"),
        ("POST empty-body", "POST", "/api/v2/text2image", b"{}", "application/json"),
        ("POST bad-json",   "POST", "/api/v2/text2image", b"{bad json", "application/json"),
        ("GET  no-body",    "GET",  "/api/v2/text2image", None, None),
    ]
    for name, method, path, body, ctype in cases:
        try:
            r = requests.request(method, BASE + path, data=body, timeout=timeout,
                                  headers=_headers(None) if ctype else {"User-Agent": "Dart/3.11 (dart:io)"})
            c = _classify(r.content, r.status_code, r.headers.get("Content-Type", ""))
            out["checks"].append({"probe": name, "http": r.status_code,
                                  "content_type": r.headers.get("Content-Type"),
                                  "bytes": len(r.content), **c})
        except Exception as e:
            out["checks"].append({"probe": name, "error": repr(e)})

    blocked = sum(1 for c in out["checks"] if c.get("kind") == "integrity_blocked")
    out["conclusion"] = (
        f"完整性门禁：{blocked} 个请求（含 GET/坏JSON/空body）全部返回同一占位图 -> "
        "门禁在任何解析之前生效，需合法 Firebase AppCheck token"
        if blocked >= 2 else "未见完整性门禁（可能现已变化，需复测）"
    )
    return out


def call(endpoint_key: str, payload: dict, appcheck_token: str | None = None,
         timeout=60, save_to: str | None = None) -> dict:
    """打真实端点。返回 {kind, md5, http, bytes, saved, ...}。"""
    method, path = ENDPOINTS[endpoint_key]
    r = requests.request(method, BASE + path, data=json.dumps(payload).encode(),
                         headers=_headers(appcheck_token), timeout=timeout)
    info = {"http": r.status_code, "content_type": r.headers.get("Content-Type"),
            "bytes": len(r.content)}
    info.update(_classify(r.content, r.status_code, r.headers.get("Content-Type", "")))
    if save_to:
        with open(save_to, "wb") as f:
            f.write(r.content)
        info["saved"] = os.path.abspath(save_to)
    return info


def text2image(prompt: str, appcheck_token=None, **kw):
    return call("t2i", {"prompt": prompt, "aspect_ratio": "1:1"}, appcheck_token, **kw)


def main():
    ap = argparse.ArgumentParser(description="CreArt 2API protocol client (R1 recon)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="探测后端 + 完整性门禁证据")

    p = sub.add_parser("t2i", help="text2image")
    p.add_argument("prompt")
    p.add_argument("--appcheck", default=None, help="真机签发的 X-Firebase-AppCheck token")
    p.add_argument("--out", default=None, help="保存 PNG 的路径")

    args = ap.parse_args()
    if args.cmd == "probe":
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
    elif args.cmd == "t2i":
        out = args.out or f"t2i_{int(time.time())}.png"
        info = text2image(args.prompt, args.appcheck, save_to=out)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        if info["kind"] == "integrity_blocked":
            print("\n[!] 完整性门禁拦截：这是预期结果。无合法 AppCheck token 时后端只返回占位图。",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
