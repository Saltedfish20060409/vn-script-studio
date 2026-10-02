/**
 * P4.5：`enforce_prose_engine_syntax_reject`（服务端 settings 下发）。
 * 默认开（fail-closed）；settings 拉失败保持开，并记一次日志。
 * 运维改 .env 后需刷新页面才生效。
 */

import type { ServerSettingsOut } from "./settings";

let enforceProseEngineSyntaxReject = true;
let settingsSyncFailedLogged = false;
let settingsSyncFailed = false;
let lastPasteHintAt = 0;
let lastPasteFingerprint = "";

export function isEnforceProseEngineSyntaxReject(): boolean {
  return enforceProseEngineSyntaxReject;
}

/** settings 持续失败时 UI 可用（非阻塞）。 */
export function isProseEngineSettingsSyncFailed(): boolean {
  return settingsSyncFailed;
}

export function applyEnforceProseFlagFromSettings(
  out: ServerSettingsOut | null | undefined
): void {
  if (!out) {
    settingsSyncFailed = true;
    if (!settingsSyncFailedLogged) {
      settingsSyncFailedLogged = true;
      console.warn(
        "[P4.5] settings 未同步，enforce_prose_engine_syntax_reject 保持默认开（fail-closed）"
      );
    }
    return;
  }
  settingsSyncFailed = false;
  if (typeof out.enforce_prose_engine_syntax_reject === "boolean") {
    enforceProseEngineSyntaxReject = out.enforce_prose_engine_syntax_reject;
  } else {
    enforceProseEngineSyntaxReject = true;
  }
}

/** 测试 / 紧急回滚模拟。 */
export function setEnforceProseEngineSyntaxRejectForTest(value: boolean): void {
  enforceProseEngineSyntaxReject = value;
  settingsSyncFailed = false;
}

/** 粘贴提示节流：同一 clipboard 指纹 10s 内最多一次。 */
export function shouldShowPasteEngineHint(clipboardText: string): boolean {
  if (!enforceProseEngineSyntaxReject) return false;
  const fp = clipboardText.slice(0, 200);
  const now = Date.now();
  if (fp === lastPasteFingerprint && now - lastPasteHintAt < 10_000) return false;
  lastPasteFingerprint = fp;
  lastPasteHintAt = now;
  return true;
}

export function resetPasteEngineHintThrottleForTest(): void {
  lastPasteHintAt = 0;
  lastPasteFingerprint = "";
}
