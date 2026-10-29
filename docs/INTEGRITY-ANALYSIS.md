# 完整性门禁深挖与可行性结论

## 1. 现象（已验证）

对 `POST https://api.creartai.com/api/v2/text2image` 做四类请求，**结果完全相同**：

| 请求 | HTTP | Content-Type | 字节 | kind |
|------|------|--------------|------|------|
| POST 正常 body `{"prompt":"a red fox","aspect_ratio":"1:1"}` | 200 | image/png | 180210 | integrity_blocked |
| POST 空 body `{}` | 200 | image/png | 180210 | integrity_blocked |
| POST 坏 JSON `{bad json` | 200 | image/png | 180210 | integrity_blocked |
| **GET**（无 body） | 200 | image/png | 180210 | integrity_blocked |

四个响应 **md5 完全一致** = `379426a18eca81366a05cd39a39ea4a7`，内容是一张 512×512 的
"Unable to verify app integrity. This app must be installed from an official source" 图
（见 `assets/integrity_blocked.png`）。

**含义**：门禁在**方法校验 / body 解析之前**就生效——连 `GET` 和坏 JSON 都返回同一图，
说明这是**请求入口层的前置完整性校验**，不是「参数错误兜底」，也不是业务 handler 的报错。

## 2. 机制判定（证据链）

1. **请求头**：libapp.so 里与身份相关的请求头**只有** `X-Firebase-AppCheck` 一个。
2. **SDK**：dex 内有 `com.google.android.play.core.integrity` / `PlayIntegrity` / `AppCheckProvider`
   / `AppCheckToken`（Firebase AppCheck 的 Android provider = Play Integrity）。
3. **文案**："installed from an official source" 是 Play Integrity 的 app-integrity 语义
   （要求 App 由 Play 授权签名、且设备通过设备完整性）。
4. **无法伪造**：Play Integrity 结论由 Google 服务端按 **硬件-backed attestation + 官方签名**
   产出；AppCheck token 由 Firebase 用该结论签发并短时有效（~30-60 分钟）。

⇒ 判定：**后端用 Firebase AppCheck（Play Integrity）做前置完整性校验**，
客户端每请求带 `X-Firebase-AppCheck`；backend 验签不过 → 直接回占位图。

## 3. 为什么 Mod 包 / 模拟器 / 纯脚本都不行

| 载体 | 能否过 AppCheck(Play Integrity) | 原因 |
|------|-------------------------------|------|
| 纯脚本（curl/本 demo） | ❌ | 没有 token；token 无法伪造 |
| Mod / 重签 APK | ❌（大概率） | 非 Play 官方签名 → app integrity 失败 |
| x86_64 模拟器 | ❌ | 无 GMS / 无 Play，设备完整性不过 |
| 官方原版 APK + 真 GMS 手机 | ✅ | 唯一能签发合法 token 的组合 |
| 官方原版 APK + 真机 + frida 桥 | ✅（可工程化） | 拦截/注入实时 token，暴露成本地 API |

> 注：Mod 包在**真机**上是否仍能过，取决于后端是否只校验「设备完整性」而非「App 签名」。
> 该点**只能在真机实测**，本环境无法验证（见第 6 节选项 B）。

## 4. 对「2API」目标的影响

- **协议层 = 已打通**：端点、方法、字段、鉴权头全部还原；demo/压测证明本地管线与透传链路可用。
- **生成层 = 被 AppCheck 挡死**：无「官方签名 + 真 GMS 设备」就拿不到合法 token → 永远只拿到占位图。
- 因此**纯协议 2API（无真机）不可行**；这不是「还没做完」，是**设计上的反滥用墙**。

## 5. 可行的真生成路线（按成本排序）

### A. 真机 + frida 桥（推荐，但要硬件）
- 一台通过 Play Integrity 的真 GMS 手机，装**官方原版** CreArt（不是 Mod）。
- frida hook 其 HTTP 层 / 或在 App 内注入本地代理，把每次 `X-Firebase-AppCheck` 实时取出，
  由一个本地/内网网关带 token 转发到 `api.creartai.com`。
- 缺点：token 短时（~30-60 分钟）→ 设备需**常驻在线**持续产出 token；本质是「活体桥」，非无头 2API。
- 前提：用户能提供真机 + 官方包。

### B. 真机装 Mod 包先做 5 分钟判定（最省，先做）
- 把当前 Mod APK 装到一台通过完整性检测的真机上，人工点 1 次生成：
  - 若**出真图** → 说明后端只卡「设备完整性」，Mod 可用 → 直接走 A 的抓包/桥接（甚至模拟器+Magisk 也可能过）。
  - 若**还是占位图** → 后端卡「App 签名」→ 必须官方包 → 回到 A。
- 这一步能把「能不能低成本搞定」一次性问清，强烈建议先做。

### C. 归档为研究报告（当前已交付）
- 已有：协议还原 + demo（mock/upstream）+ 压测 + 完整证据 + 本分析。
- 适合「先要结论与可复用资产，暂不投入硬件」的场景。

### D. 放弃
- 若三个方向都不成立（无真机、无官方包、不接受常驻设备）。

## 6. 本环境未能验证 / 待验证项

- Mod 包在**真机**上能否过完整性 → 待真机实测（选项 B）。
- `/device_info`、credits、订阅校验等**门禁后**接口的真实语义 → 待真机带 token 后抓包。
- 请求体字段的**取值枚举**（style/model/quality 具体枚举值）→ 待真机抓包确认。
