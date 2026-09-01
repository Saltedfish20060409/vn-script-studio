import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearToken,
  getToken,
  login as apiLogin,
  logout as apiLogout,
  me as apiMe,
  register as apiRegister,
  type RegisterOut,
  type UserOut,
} from "../api/client";
import { AuthContext } from "../lib/authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        // Always probe /auth/me: if we have a refresh cookie, apiFetch will
        // transparently obtain a fresh access token on 401. This restores the
        // session after a page reload (access token is memory-only by design).
        const u = await apiMe();
        if (!cancelled) {
          setUser(u);
          setTokenState(getToken());
        }
      } catch {
        if (!cancelled) {
          clearToken();
          setTokenState(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    await apiLogin(username, password);
    setTokenState(getToken());
    const u = await apiMe();
    setUser(u);
  }, []);

  const register = useCallback(
    async (username: string, password: string, email: string): Promise<RegisterOut> => {
      return apiRegister(username, password, email);
    },
    []
  );

  const logout = useCallback(() => {
    void apiLogout().catch(() => undefined);
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ token, user, loading, login, register, logout }),
    [token, user, loading, login, register, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
