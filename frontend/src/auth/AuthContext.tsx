import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "../api/client";
import type { AppConfig, User } from "../api/types";
import { cognitoLogoutUrl } from "./cognito";

interface AuthState {
  config: AppConfig | null;
  user: User | null;
  loading: boolean;
  /** Set when the API can't be reached (e.g. only the web app was started). */
  apiDown: boolean;
  retry: () => void;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiDown, setApiDown] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      try {
        setConfig(await api.config());
        setApiDown(false);
      } catch {
        setApiDown(true);
        setLoading(false);
        return;
      }
      try {
        if (getToken()) setUser(await api.me());
      } catch {
        setToken(null);
      } finally {
        setLoading(false);
      }
    };
    void init();
  }, [attempt]);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener("cellloop:unauthorized", onUnauthorized);
    return () => window.removeEventListener("cellloop:unauthorized", onUnauthorized);
  }, []);

  const signIn = useCallback(async (token: string) => {
    setToken(token);
    setUser(await api.me());
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
    const url = config?.auth_mode === "cognito" ? cognitoLogoutUrl() : null;
    if (url) window.location.assign(url);
  }, [config]);

  const value = useMemo(
    () => ({ config, user, loading, apiDown, retry, signIn, signOut }),
    [config, user, loading, apiDown, retry, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function useConfig(): AppConfig {
  const { config } = useAuth();
  if (!config) throw new Error("Config not loaded");
  return config;
}
