import { apiFetch, setToken } from "./http";
import { getRef } from "../lib/refSource";

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
  // 渠道归因：把首次带到的 ?ref= 一起提交（后端写入 users.signup_source）。
  const ref = getRef();
  return apiFetch<RegisterOut>("/auth/register", {
    method: "POST",
    body: JSON.stringify(ref ? { username, password, email, ref } : { username, password, email }),
    skipAuthRedirect: true,
  });
}

export async function login(username: string, password: string): Promise<TokenOut> {
  const data = await apiFetch<TokenOut>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    skipAuthRedirect: true,
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
  });
}

export function me(): Promise<UserOut> {
  // 登录态探测：401 时静默失败即可（refresh 也在 apiFetch 内自动尝试）。
  // 不能带全局跳转登录——否则公开页（/verify-email、/reset-password 等）
  // 一挂载就因未登录被踢去 /login，验证/重置流程无法执行。
  return apiFetch<UserOut>("/auth/me", {
    skipAuthRedirect: true,
  });
}

export function verifyEmail(token: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
    skipAuthRedirect: true,
  });
}

export function resendVerification(email: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuthRedirect: true,
  });
}

export function forgotPassword(email: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
    skipAuthRedirect: true,
  });
}

export function resetPassword(token: string, password: string): Promise<OkMessageOut> {
  return apiFetch<OkMessageOut>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
    skipAuthRedirect: true,
  });
}
