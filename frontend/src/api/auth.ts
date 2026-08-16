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
  created_at: string;
}

export async function register(
  username: string,
  password: string
): Promise<TokenOut> {
  const data = await apiFetch<TokenOut>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    skipAuthRedirect: true,
  });
  setToken(data.access_token);
  if (data.refresh_token) setRefreshToken(data.refresh_token);
  return data;
}

export async function login(
  username: string,
  password: string
): Promise<TokenOut> {
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
