"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type { AuthUser } from "./api/types";
import * as api from "./api/client";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<boolean>;
  register: (
    email: string,
    password: string,
    displayName: string
  ) => Promise<boolean>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const { data, error: err } = await api.getMe();
    if (data) {
      setUser(data);
      setError(null);
    } else {
      setUser(null);
      // Only set error for non-auth failures
      if (err && !err.includes("401")) {
        setError(err);
      }
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const loginFn = useCallback(
    async (email: string, password: string): Promise<boolean> => {
      setError(null);
      const { data, error: err } = await api.login({ email, password });
      if (data) {
        setUser(data);
        return true;
      }
      setError(err || "Login failed");
      return false;
    },
    []
  );

  const registerFn = useCallback(
    async (
      email: string,
      password: string,
      displayName: string
    ): Promise<boolean> => {
      setError(null);
      const { data, error: err } = await api.register({
        email,
        password,
        display_name: displayName,
      });
      if (data) {
        setUser(data);
        return true;
      }
      setError(err || "Registration failed");
      return false;
    },
    []
  );

  const logoutFn = useCallback(async () => {
    await api.logout();
    setUser(null);
    setError(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        error,
        login: loginFn,
        register: registerFn,
        logout: logoutFn,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
