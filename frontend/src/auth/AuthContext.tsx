import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearToken,
  getToken,
  login as apiLogin,
  me as apiMe,
  register as apiRegister,
  type UserOut,
} from "../api/client";

interface AuthContextValue {
  token: string | null;
  user: UserOut | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<UserOut | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      const existing = getToken();
      if (!existing) {
        setLoading(false);
        return;
      }
      try {
        const u = await apiMe();
        if (!cancelled) {
          setUser(u);
          setTokenState(existing);
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

  const register = useCallback(async (username: string, password: string) => {
    await apiRegister(username, password);
    setTokenState(getToken());
    const u = await apiMe();
    setUser(u);
  }, []);

  const logout = useCallback(() => {
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

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
