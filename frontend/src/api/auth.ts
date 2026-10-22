import { apiFetch, setToken } from "./http";
import { TIMEOUTS } from "./timeouts";

export interface TokenOut {
  access_token: string;
  refresh_token?: string | null;
  token_type: string;
  expires_in?: number | null;
}

export interface UserOut {
  id: string;
  username: string;
  email?: string | null;
  email_verified?: boolean;
  created_at: string;
  is_admin?: boolean;
}

export interface RegisterOut {
  ok: boolean;
  message: string;
  email: string;
}

export interface OkMessageOut {
  ok: boolean;
  message: string;
}

export async function register(
  username: string,
  password: string,
  email: string
): Promise<RegisterOut> {
  return apiFetch<RegisterOut>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password, email }),
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

export async function login(username: string, password: string): Promise<TokenOut> {
  const data = await apiFetch<TokenOut>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
  // Refresh token arrives as an HttpOnly cookie; only the access token is
  // kept (in memory) by the HTTP layer.
  setToken(data.access_token);
  return data;
}

export function logout(): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/logout", {
    method: "POST",
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

export function me(): Promise<UserOut> {
  // 登录态探测：401 时静默失败即可（refresh 也在 apiFetch 内自动尝试）。
  // 不能带全局跳转登录——否则公开页（/verify-email、/reset-password 等）
  // 一挂载就因未登录被踢去 /login，验证/重置流程无法执行。
  return apiFetch<UserOut>("/auth/me", {
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

export function verifyEmail(token: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

export function resendVerification(email: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

export function forgotPassword(email: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

export function resetPassword(token: string, password: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}

/**
 * 永久删除当前账号及名下全部数据（不可恢复）。
 *
 * 不要与 `logout()` 混淆：logout 只是清掉本机登录态，账号与项目都在。
 * 这里需要密码 + 用户名双重确认（后端也会各自校验一次）。
 */
export function deleteAccount(
  password: string,
  confirm: string
): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/me", {
    method: "DELETE",
    body: JSON.stringify({ password, confirm }),
    // 删号失败时不要顺手把人踢去登录页：错误信息要留在对话框里给人看。
    skipAuthRedirect: true,
    timeoutMs: TIMEOUTS.auth,
    timeoutKind: "auth",
  });
}
