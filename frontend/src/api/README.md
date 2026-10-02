# `frontend/src/api`

HTTP 客户端与超时预算。数字真源见 `timeouts.ts`；契约见 `timeouts.test.ts` /
`timeoutWiring.test.ts`。

## 超时 kind

- 认证：`timeoutMs: TIMEOUTS.auth` + `timeoutKind: "auth"`
- 模型：`timeoutMs: TIMEOUTS.(quick|chat|write|long|batch|probe)` + `timeoutKind: "llm"`
- 其余：可显式 `timeoutKind: "api"`，或不传（默认按预算兜底）

## Code review 检查项（无自动守卫 / 已知不覆盖）

1. **`fetchWithTimeout` 内 `timeoutMessage` 的 kind**：必须来自
   `resolveTimeoutKind`（或绑定到其返回值的标识符），禁止写成
   `timeoutMessage(timeout, "api")` 字面量兜底。此项由 `timeoutWiring.test.ts` T4
   自动钉；若结构大改导致 T4 不稳，以本条 review 为准，**不要**用 `it.todo` 挂死信。

2. **规则 A 不覆盖**：多层 const 转发、函数返回、跨文件 import 别名
   （`const t = TIMEOUTS.chat; apiFetch(..., { timeoutMs: t })` 的一层同文件转发
   **有**自动覆盖）。

3. **规则 B 不覆盖**：`const b = { timeoutMs: ... }; JSON.stringify(b)` 间接 body。
   当前无白名单；不要用间接对象绕过守卫。
