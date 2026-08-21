import { apiFetch, setToken, setRefreshToken } from "./http";

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
  });
}

export async function login(username: string, password: string): Promise<TokenOut> {
  const data = await apiFetch<TokenOut>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    skipAuthRedirect: true,
  });
  setToken(data.access_token);
  if (data.refresh_token) setRefreshToken(data.refresh_token);
  return data;
}

export function me(): Promise<UserOut> {
  return apiFetch<UserOut>("/auth/me");
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
