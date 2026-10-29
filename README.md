# CreArt 2API — R1（逆向 + 本地 demo + 压测）

> **STATUS: 🔒 ARCHIVED（研究报告归档，2026-10-29）**
> 真实生成被 Firebase AppCheck(Play Integrity) 前置门禁阻断；经用户决定：**暂不投硬件**，
> 本方按「可复用研究报告」归档。协议/demo/压测/证据均已完成可用；**不是**可投产的生成渠道。
> 若日后拿到「官方签名 APK + 真 GMS 手机」→ 走 `docs/INTEGRITY-ANALYSIS.md` 的路线 A/B 复活。

> 目标 APK：`CreArt_v2.7.2_(42)_Mod.apk`（包名 `ai.aiart.aiartgenerator.creart`，Flutter / Dart 3.11.0）
> 上游：`https://api.creartai.com`
> 本文档只记录**实测证据**；未验证项明确标注。

## TL;DR（一句话）

协议（端点/字段/鉴权头）**已全量还原**且本地 demo + 压测跑通；但真实图片生成被
**后端 Firebase AppCheck（Play Integrity）完整性门禁**挡住——任何未携带**合法 AppCheck token**
的请求（含 GET / 空 body / 坏 JSON）都会被**无条件**返回同一张
`Unable to verify app integrity / must be installed from an official source` 占位图(HTTP 200)。
合法 token 只能由「**官方签名 APK + 通过 Play Integrity 的真实 GMS 设备**」实时签发，
因此纯协议 / Mod 包 / 模拟器**无法直接真生成**。

## 已验证状态

| 项 | 结论 | 证据 |
|----|------|------|
| 后端起址/端点 | `https://api.creartai.com` · `POST /api/v2/{text2image,image2image,upscale}` | libapp.so 字符串 + 实测 200 PNG |
| 鉴权头 | 唯一：`X-Firebase-AppCheck` | libapp.so 字面量；无任何自定义签名头 |
| 完整性门禁 | **阻断真生成**（GET/坏JSON/空body 全返回同一占位图） | `creart_client.py probe`、`/probe`、截图 |
| demo 服务（mock+upstream） | 通过 | 截图 `screenshots/demo_*.png` |
| 压测 mock（本地） | 200/200，100%，56.9 rps，p95 489ms | `stress_test.py --mode mock` |
| 压测 upstream（真实链路） | 30/30 HTTP200，**全部 integrity_blocked**，p50 3.7s | `stress_test.py --mode upstream` |
| 真实出图 | **未达成 / blocked** | 见 `docs/INTEGRITY-ANALYSIS.md` |

## 目录

```
creart_client.py     协议客户端（真实打上游；probe / t2i）
demo_server.py       本地 demo 服务（mock / upstream 两模式，Flask）
demo.html            demo 页面（生成 + 实时展示 X-Creart-Kind / 门禁证据）
stress_test.py       并发压测（aiohttp）
assets/              integrity_blocked.png（后端占位图原件，作为门禁证据）
screenshots/         demo 页截图（initial / mock / upstream_blocked）
docs/
  REVERSE_REPORT.md  静态逆向全量报告
  INTEGRITY-ANALYSIS.md  完整性门禁深挖与可行性结论
  NEW-API-INTEGRATION.md  接入 new-api 的对接指南（骨架版 / 真机 token 桥版）
```

## 快速开始

```bash
pip install flask requests pillow aiohttp      # 依赖
python creart_client.py probe                  # 看后端 + 门禁证据（真打上游）
python demo_server.py                          # :8940 起 demo（mock 默认）
#   CREART_MODE=upstream python demo_server.py  # 默认走真实透传
python stress_test.py --mode mock     --n 200 --c 20
python stress_test.py --mode upstream  --n 30  --c 6
```

> 本机 8940 常被其它服务占用，实际用了 8955/8966 端口；`PORT=xxxx` 可改。

## 真实性声明（反伪实现）

- mock 模式产物**页面/图片均打大字 `MOCK`**，不冒充真实生成。
- upstream 模式**忠实透传上游字节**，用 `X-Creart-Kind` / `X-Creart-Notice` / `X-Creart-Upstream-MD5`
  标明「这是门禁占位图，不是生成结果」。
- 未在真机/官方包上验证过的能力，一律标 `待验证`，不写「已打通」。
