# VN Script Studio · Android 客户端（移动伴侣）

原生 Kotlin + Jetpack Compose。定位是**移动伴侣**，不是 Web 的移植：

| 在手机上做 | 留在 Web 做 |
|---|---|
| 写作 / 修改章节（离线可写、联网自动同步） | 剧本引擎、RPY 生成、导出 |
| 本地检查（字数、笔误、标点、分场） | 完整的一致性分析、设定库编辑 |
| Agent 对话（流式）、账本 / 摘要 / 伏笔查看 | 成员管理、邀请 |
| 协作批注（实时）、用量、本机 Key、每日提醒 | |

设置页里有「在网页端打开」（Custom Tabs），不在 App 内嵌 WebView，也不把令牌交给网页。

## 构建

需要 JDK 17 与 Android SDK（compileSdk 35，minSdk 26）。仓库已包含 Gradle Wrapper：

```bash
cd android
./gradlew testDebugUnitTest      # 单测（含与 Web / 后端共用的夹具）
./gradlew lintDebug
./gradlew assembleDebug
```

- debug 与 release 默认都连线上服务 `https://vnscriptstudio.cn`，且都只允许 HTTPS；
  需要连其它服务端时用 `-Pvnss.debugServerUrl=...` / `-Pvnss.releaseServerUrl=...` 覆盖
  （本机调试 http 后端还需把 `app/build.gradle.kts` 里 debug 的 `usesCleartext` 临时改为 `"true"`）。
- 签名：复制 `keystore.properties`（`storeFile / storePassword / keyAlias / keyPassword`，**已在 .gitignore**）到 `android/`；
  没有该文件时 release 回退用 debug 签名，仅供内测。
- 给作者下载的包请发到 [GitHub Releases](https://github.com/Saltedfish20060409/vn-script-studio/releases)（网页设置里也链到这里）；CI 的 debug APK 产物只供开发自测。

## 架构

```
app                      Hilt 装配、导航、Activity
feature:auth             登录 / 注册 / 找回
feature:projects         作品列表、章节列表
feature:editor           编辑器、本地检查、冲突裁决
feature:agent            Agent 流式对话
feature:ledger           账本 / 摘要 / 伏笔（只读）
feature:collab           批注 / 成员 / 编辑状态（SSE 实时）
feature:settings         设置、模型配置、用量、提醒
core:model               领域模型 + 仓库接口（feature 只依赖这一层）
core:data                仓库实现、同步引擎、WorkManager
core:network             Retrofit / OkHttp / SSE / 令牌刷新 / 超时预算
core:database            Room
core:datastore           DataStore + 加密存储
core:designsystem        主题与公共组件
core:common              工具（三方合并、字数口径、Outcome / AppError）
```

feature 之间不互相依赖，feature 也不依赖 `core:data / network / database` 的实现——实现由 Hilt 在 `app` 装配。

### 离线优先与同步

Room 是唯一数据源；章节的 `syncState`（`SYNCED / DIRTY / CONFLICT`）本身就是同步队列。

- 编辑只写本地并标记 `DIRTY`，WorkManager 去抖后上传（另有 15 分钟周期兜底）。
- 上传走「章级保存」：`PUT /projects/{id}` 带 `chapter_ids`，服务端只合并声明的章节，
  所以手机永远不会冲掉 Web 端的设定 / 脚本；移动端不认识的字段原样保存在 `rawJson` 里回传。
- 本地与服务端都改过同一章：先做三方合并（段落 / 行级 diff3）；无法自动合并才进入 `CONFLICT`，
  由用户选择「两份都保留 / 保留我的 / 采用服务器」，任何一种都不会静默丢内容。
- 刷新不会覆盖 `DIRTY / CONFLICT` 章节的正文。
- 会话过期不删库（草稿保留）；换账号登录必清库；退出时仍有未同步内容则保留本地库。

### 鉴权

请求带 `X-Client: android` 时，后端在响应体里返回 refresh token（浏览器仍走 Cookie）。
令牌保存在 EncryptedSharedPreferences；刷新由 OkHttp `Authenticator` 单飞完成，刷新失败才回到登录页。
**任何位置都不记录令牌与 LLM Key**（日志对 `Authorization / X-LLM-*` 脱敏）。

## 跨端一致性

同一份规则在 Web（TypeScript）和手机（Kotlin）各有一份实现，靠共享夹具防漂移：

- `shared/test-fixtures/writing_local_cases.json`：由 `frontend/scripts/gen_writing_local_cases.ts` 从 TS 实现生成；
  `frontend/src/lib/writingLocalCases.test.ts` 保证夹具与当前 TS 输出一致，Android `WritingLocalCasesTest` 逐条对照 Kotlin 输出。
  改了 Web 的检查规则就重新生成夹具，两边测试会一起提示。
- `shared/test-fixtures/android_api_contract.json`：Android 依赖的后端接口清单。
  后端 `tests/test_android_contract.py` 对照 OpenAPI 校验，Android `ApiContractTest` 对照 Retrofit 声明与 DTO 字段校验。

## 已知限制

- 手机端不取章节编辑锁（读取并展示他人正在编辑的章节）；章节被他人锁定时保存会被服务端拒绝，
  稿子留在手机上，锁释放后自动重试。
- Agent 默认「只给方案、不直接改稿」，需手动打开开关才会写入作品；运行前会先同步本机稿子，
  有冲突或同步失败时拒绝运行（避免 Agent 基于旧稿改写）。
- 每日提醒依赖 WorkManager，Doze 下可能晚几分钟；Android 13+ 需要用户授予通知权限。
- 没有 Room DAO 的仪器 / Robolectric 测试；同步引擎的核心决策（三方合并、同步规划、项目 JSON 往返）有纯 JVM 单测。
