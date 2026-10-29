# CreArt v2.7.2 静态逆向报告

包名 `ai.aiart.aiartgenerator.creart` ｜ 版本 2.7.2 (42) ｜ Flutter / Dart 3.11.0
样本：`CreArt_v2.7.2_(42)_Mod.apk`（arm64-v8a only，libapp.so 6.1MB，build 2026-02-19）

## 1. 引擎与结构

- **Flutter AOT**：`lib/arm64-v8a/{libapp.so, libflutter.so}`，`libapp.so` 内 Dart 快照 `Dart 3.11.0`，
  snapshot hash `78da37fed6bf1489361a312568249f3f`，flags 含 `compressed-pointers / dedup_instructions`。
- **无 ARM 之外的 ABI**：只有 arm64 —— 直接用 x86_64 AVD 无法运行（本机 emulator-5554 即 x86_64）。
- 原生 dex：`classes.dex(9.4M) / classes3.dex(7.2M) / classes4.dex(1.2M)`，主要是 GMS / Firebase / AppLovin / RevenueCat。

## 2. 网络基座

| 项 | 值 | 来源 |
|----|----|------|
| API base | `https://api.creartai.com` | libapp.so 字面量 |
| 业务端点 | `/api/v2/text2image`、`/api/v2/image2image`、`/api/v2/upscale` | libapp.so 片段 `/v2`、`/text2image`、`/image2image`、`/upscale` + 命名空间实测 |
| 健康检查 | `/health` → `{"status":"ok"}` | 实测 |
| 响应体 | `image/png` 原始字节（512×512 起） | 实测 |
| 翻译旁路 | `translate.googleapis.com/translate_a/single` | libapp.so |
| 静态资源 | `creart-app.firebasestorage.app`（Firebase Storage bucket） | libapp.so |

其它域名（`waitos.github.io/creart`、facebook/instagram、app store）均为 运营/法务/商店链接，非 API。

## 3. 鉴权 / 完整性（核心）

- libapp.so 内**唯一**的鉴权/身份类请求头字面量：`X-Firebase-AppCheck`。
- 未发现任何自定义签名头（`X-Signature / X-Sign / X-Device` 等均无）。
- dex 中确认存在 **Firebase AppCheck + Play Integrity provider**：
  `com.google.android.play.core.integrity` / `PlayIntegrity` / `AppCheckProvider` / `AppCheckToken`
  （`classes.dex`、`classes3.dex`）。
- libapp.so 含 `playIntegrity`、`appAttestWithDeviceCheckFallback`（iOS 侧 DeviceCheck 回退）、
  `signatureVerificationFailed`、`AuthenticationStatus` 等字符串（多为 firebase_app_check 插件自带）。
- 结论：App 用 **Firebase AppCheck** 取 token，塞进 `X-Firebase-AppCheck` 请求头发给 `api.creartai.com`；
  后端校验 Play Integrity 结论。详见 `INTEGRITY-ANALYSIS.md`。

## 4. 请求体字段（从 Dart 字符串还原，命名以待真机确认）

`prompt`、`aspect_ratio`/`aspectratio`、`style`、`model`、`quality`、`width`、`height`、
`base64`（i2i 输入图）、`imageUrl`、`deviceId`。
> 这些字段在**门禁通过后**才被后端解析；本 R1 因门禁未过，字段语义（尤其 style/model 取值枚举）
> 仍属 **待验证**。

## 5. 计费 / 变现

- **RevenueCat / in_app_purchase**：`Purchases-*`、`amountMicros`、`appGroupId`、
  `app_store_subscription_*`、`allPurchasedProductIdentifiers`、`Rewarded_Android`（激励广告）。
- 变现模型：订阅（RevenueCat IAP）+ 激励广告（AdMob / AppLovin）+ 内含 credits。
- credits 的真正记账在后端（`/api/v2/*` 侧），客户端只展示；`/device_info` 疑似设备注册/额度接口
  （实测该路径 502，可能挂在别的前缀或需门禁后可达，**待验证**）。

## 6. Firebase 配置（公开值，非密钥）

```
google_api_key = AIzaSy…(已脱敏，客户端公开 Web API Key，非服务端密钥)
mobilesdk_app_id = 1:632286816849:android:4d2ec329e6923b4e97a670
project_id = creart-app
storage_bucket = creart-app.firebasestorage.app
```
> 这些是客户端公开配置，**不能**用来绕过 AppCheck（token 由 Play Integrity 在设备侧签发、服务端验签）。

## 7. 工具/环境备注

- 本机：Java17、Python3.14、frida、mitmdump、adb（emulator-5554 为 **x86_64 无 GMS**）、
  `D:/apk-analysis/blutter`（预编译仅 Dart 3.6.2/3.7.2，**不支持 3.11**，故未用 blutter 反编译）。
- APK 仅 arm64 → 本机模拟器不能原生运行；Play Integrity 又要求真机+GMS+官方签名 → 动态真生成在本环境**不可达**。
