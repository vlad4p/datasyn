import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getAuthMe, logoutAuth, type AuthMeResponse, type AuthUser } from "../api";

type AuthContextValue = {
  loading: boolean;
  authEnabled: boolean;
  user: AuthUser | null;
  providers: string[];
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [providers, setProviders] = useState<string[]>([]);

  const applyMe = useCallback((me: AuthMeResponse) => {
    setAuthEnabled(me.auth_enabled);
    setUser(me.authenticated ? me.user : null);
    setProviders(me.providers ?? []);
  }, []);

  const refresh = useCallback(async () => {
    const me = await getAuthMe();
    applyMe(me);
  }, [applyMe]);

  const logout = useCallback(async () => {
    await logoutAuth();
    setUser(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await getAuthMe();
        if (!cancelled) applyMe(me);
      } catch {
        if (!cancelled) {
          setAuthEnabled(false);
          setUser(null);
          setProviders([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applyMe]);

  const value = useMemo(
    () => ({
      loading,
      authEnabled,
      user,
      providers,
      refresh,
      logout,
    }),
    [loading, authEnabled, user, providers, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
