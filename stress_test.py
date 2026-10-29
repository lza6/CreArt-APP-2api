#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CreArt 2API 本地压测 —— R1
==========================

两个用例：
  mock      打本地 demo_server 的 mock 端点，验证【服务端吞吐/稳定性】。
  upstream  打本地 demo_server 的 upstream 透传，验证【真实上游链路的并发行为】。
            无 AppCheck token 时上游只会返回完整性占位图，这里主要量测 RTT 与稳定性，
            并统计 _kind 分布（预期几乎全是 integrity_blocked）。

不碰生产、不碰付费（上游本身对匿名回占位图，无扣费）。

用法:
  python stress_test.py --n 200 --c 20 --mode mock
  python stress_test.py --n 100 --c 10 --mode upstream --server http://127.0.0.1:8940
"""
import argparse
import asyncio
import statistics
import time
import hashlib
import json

import aiohttp

PROMPTS = [
    "a red fox in snow", "cyberpunk city at night", "a glass of orange juice",
    "an astronaut riding a horse", "watercolor mountains", "neon tiger portrait",
    "a serene japanese garden", "abstract geometric art", "a vintage car",
    "fantasy castle in clouds",
]


async def one(session, url, prompt, mode):
    body = json.dumps({"prompt": prompt, "aspect_ratio": "1:1"}).encode()
    t0 = time.perf_counter()
    try:
        async with session.post(f"{url}?mode={mode}", data=body,
                                headers={"Content-Type": "application/json"},
                                timeout=aiohttp.ClientTimeout(total=120)) as r:
            content = await r.read()
            dt = (time.perf_counter() - t0) * 1000
            return {"ok": r.status == 200, "http": r.status, "ms": dt,
                    "kind": r.headers.get("X-Creart-Kind", "?"),
                    "md5": hashlib.md5(content).hexdigest()[:10], "bytes": len(content)}
    except Exception as e:
        dt = (time.perf_counter() - t0) * 1000
        return {"ok": False, "http": 0, "ms": dt, "kind": "exception", "err": repr(e)[:80]}


def pct(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1)))))
    return xs[k]


async def run(url, mode, n, conc):
    sem = asyncio.Semaphore(conc)
    results = []

    async def bounded(i):
        async with sem:
            return await one(session, url, PROMPTS[i % len(PROMPTS)], mode)

    conn = aiohttp.TCPConnector(limit=conc)
    async with aiohttp.ClientSession(connector=conn) as session:
        t0 = time.perf_counter()
        tasks = [asyncio.create_task(bounded(i)) for i in range(n)]
        for c in asyncio.as_completed(tasks):
            results.append(await c)
        wall = time.perf_counter() - t0

    lat = [r["ms"] for r in results]
    ok = sum(1 for r in results if r["ok"])
    kinds = {}
    for r in results:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    summary = {
        "mode": mode, "requests": n, "concurrency": conc, "wall_s": round(wall, 2),
        "rps": round(n / wall, 2) if wall else 0,
        "ok": ok, "fail": n - ok, "success_rate": round(100 * ok / n, 1),
        "latency_ms": {"p50": round(pct(lat, 50), 1), "p95": round(pct(lat, 95), 1),
                       "p99": round(pct(lat, 99), 1),
                       "min": round(min(lat), 1) if lat else 0, "max": round(max(lat), 1) if lat else 0},
        "kind_dist": kinds,
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8940")
    ap.add_argument("--mode", default="mock", choices=["mock", "upstream"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--c", type=int, default=20)
    a = ap.parse_args()
    url = a.server.rstrip("/") + "/api/v2/text2image"
    print(f"[stress] {a.mode}  n={a.n} c={a.c}  -> {url}")
    s = asyncio.run(run(url, a.mode, a.n, a.c))
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print("\n结论: " + (
        f"成功率 {s['success_rate']}%, {s['rps']} rps, p95 {s['latency_ms']['p95']}ms; "
        f"kind 分布 {s['kind_dist']}" +
        ("（upstream 模式几乎全 integrity_blocked 属预期：无合法 AppCheck token）"
         if a.mode == "upstream" else "")))


if __name__ == "__main__":
    main()
