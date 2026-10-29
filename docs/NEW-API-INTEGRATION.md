# CreArt 2API → new-api 对接指南（你自己对接，照着做）

> 面向：你自己在 new-api 里把 CreArt 接成一个可用渠道。
> 先说清楚现状，再给两套对接方案（当前 / 将来）。

---

## 0. ⚠️ 必须先读：现在接上去 = 一堆占位假图

上游 `api.creartai.com` 有 **Firebase AppCheck(Play Integrity) 前置门禁**：任何请求只要
**不带合法 `X-Firebase-AppCheck` token**（脚本 / Mod 包 / 模拟器都没有），后端就是
HTTP200 + 固定占位图（`Unable to verify app integrity`，md5 `379426a18eca81366a05cd39a39ea4a7`）。

- **现在**（无真机 token 源）：你把本 demo 接进 new-api，能"接通"，但每张图都是这张占位图 → **等于假图，别投产**。
- **将来**（有真机 token 源）：本指南第 3 节，改一处 token 来源即可真出图，其余不变。

如果只是想先把渠道骨架搭好、验证链路，走第 2 节（骨架版，明确标注 mock/占位）。

---

## 1. 上游契约速查（对接的核心）

| 项 | 值 |
|----|----|
| Base | `https://api.creartai.com` |
| 文生图 | `POST /api/v2/text2image` |
| 图生图 | `POST /api/v2/image2image` |
| 放大 | `POST /api/v2/upscale` |
| 鉴权头 | `X-Firebase-AppCheck: <token>`（唯一，必需） |
| Content-Type | `application/json` |
| 返回 | **`image/png` 原始字节**（不是 JSON，不是 base64） |
| 请求体 | `{ "prompt": str, "aspect_ratio": "1:1"/"3:4"/"4:3"/"9:16", "style"?, "model"?, "quality"?, "width"?, "height"? }`（i2i/upscale 用 `base64`/`imageUrl`） |

> 字段名来自 libapp.so；`style/model/quality` 的具体枚举值**待真机抓包确认**（现在过不了门禁，看不到）。

---

## 2. 方案 A：本地中转网关 + new-api（骨架版，现在可做）

思路：new-api 不直接连上游，而是连本仓库的 `demo_server.py`；`demo_server.py` 负责
带 `X-Firebase-AppCheck` 打上游、并把 `image/png` 字节转成 OpenAI 形态。

### 2.1 起 demo 服务
```bash
pip install flask requests pillow aiohttp
# 默认 mock（本地合成 MOCK 图，证明链路）
PORT=8940 python demo_server.py
# 真打上游（现在是占位图，但链路/头部/耗时都是真的）
CREART_MODE=upstream PORT=8940 python demo_server.py
# 有 token 源时（第3节）：把 token 注进去
CREART_MODE=upstream CREART_APPCHECK_TOKEN=<token> PORT=8940 python demo_server.py
```

### 2.2 new-api 侧怎么接
new-api 的内置 OpenAI images 渠道期望上游是 `/v1/images/generations`（返回 JSON `{data:[{b64_json|url}]}`），
而本服务是 `/api/v2/text2image` 直出 PNG。两种走法，二选一：

**走法①（推荐，最省心）：加一层 OpenAI 适配端点**
在 `demo_server.py` 里加一个 `/v1/images/generations`：
- 收 OpenAI 体 `{model,prompt,size,n,response_format}`
- 转成 `{prompt, aspect_ratio}`（`size 1024x1024→1:1`，`768x1024→3:4`...）
- 打 `/api/v2/text2image` 拿 PNG
- 回 `{"created":ts,"data":[{"b64_json":"<png的base64>"}]}`
这样 new-api 直接用「自定义 OpenAI 渠道」指向 `http://<host>:8940`，零改 new-api 代码。

**走法②：new-api 新增 CreArt 渠道类型**
参考历史 2API 渠道（`relay/channel/<name>/adaptor`），在 adaptor 里把 OpenAI 图请求转成
CreArt 体、把 PNG 字节回填成 `b64_json`。工作量大，除非要深度定制否则不必要。

> 适配端点（走法①）本 R1 **未实现**（门禁未解，做了也是假图）。你真要搭骨架我可以给你这段代码——
> 但请先明确：骨架期产物全是占位图，仅用于打通链路。

### 2.3 关键坑（必看）
- **响应是裸 PNG 不是 JSON**：new-api 侧一定要做 base64 回填，别直接当 JSON 解析。
- **别把占位图当成功**：占位图也是 HTTP200+image/png，靠 md5(`3794...4a7`) 或响应头
  `X-Creart-Kind: integrity_blocked` 识别，命中就当"上游不可用/被门禁"。
- **AppCheck token 短时**：静态注入 30-60 分钟就废，必须换成按请求实时取（第3节）。

---

## 3. 方案 B：真机 frida token 桥 + new-api（将来真出图）

要让每张图都是真图，唯一现实路线：**官方签名 APK + 通过 Play Integrity 的真 GMS 手机**
常驻，frida 拦截 App 每次请求的 `X-Firebase-AppCheck`，做成一个"取 token"的本地接口，
由 `demo_server.py` 每请求前调它拿最新 token。

改造点（只改 `demo_server.py` 里 `_serve` 的 `APPCHECK` 来源）：
```python
# 现在：APPCHECK = os.environ.get("CREART_APPCHECK_TOKEN")  # 静态
# 改成：每请求从 token 桥现取
def get_appcheck_token():
    return requests.get("http://127.0.0.1:PORT_ON_PHONE/token", timeout=3).text.strip()
```
token 桥（真机侧，需另建）：frida hook `okhttp`/`dart:io` 的请求，把 `X-Firebase-AppCheck`
写到本地 `/token`。**这部分本 R1 未做（缺真机）**，是你后续要补的硬件环节。

**判定先做**：拿现在的 Mod 包装真机点一次生成——出真图=后端只卡设备完整性，Mod 可用；
还是占位图=卡 App 签名，必须官方原版 APK。见 `docs/INTEGRITY-ANALYSIS.md` 第 5 节。

---

## 4. 自检命令（对接后立刻验）
```bash
# 1) 网关活着
curl -s http://127.0.0.1:8940/health
# 2) 门禁/上游证据
curl -s http://127.0.0.1:8940/probe | python -m json.tool
# 3) 打一张（看响应头判断真假）
curl -s -D - -o out.png -X POST "http://127.0.0.1:8940/api/v2/text2image" \
  -H "Content-Type: application/json" -d '{"prompt":"a red fox"}' | grep -i "x-creart"
#    X-Creart-Kind: mock            -> 本地合成（非真图）
#    X-Creart-Kind: integrity_blocked -> 上游门禁占位图（非真图）
#    X-Creart-Kind: image           -> 真图（只有在带合法 token 时才会出现）
# 4) new-api 侧：渠道测试 -> 发一张图，看是不是占位图
```

---

## 5. 契约对照表（OpenAI ↔ CreArt，供你的适配层用）

| OpenAI images 字段 | CreArt 字段 | 映射 |
|---|---|---|
| `prompt` | `prompt` | 直传 |
| `size: "1024x1024"` | `aspect_ratio: "1:1"` | 方→1:1 |
| `size: "1024x1536"` | `aspect_ratio: "3:4"`(近似) | 竖→3:4 |
| `size: "1536x1024"` | `aspect_ratio: "4:3"` | 横→4:3 |
| `n` | （后端定，多图多次请求） | 循环 N 次 |
| `response_format:"b64_json"` | —— | 把 PNG 字节 base64 回填 |
| `image`(编辑) | `base64`/`imageUrl` → `/api/v2/image2image` | i2i |

---

## 6. 结论

- **现在**：能接骨架，但产物是占位图 → 只做链路验证，别投产。
- **要真图**：必须先解决"真机 + 官方签名 + frida token 桥"（第3节），这是硬件前提，不是代码问题。
- 本文档所有字段/映射以静态还原为准；`style/model/quality` 枚举 **待真机抓包** 补齐。
