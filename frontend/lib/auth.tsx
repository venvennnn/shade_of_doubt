"use client";

import { createContext, useContext, useEffect, useState } from "react";

const KEY = "shade.session";
const SESSION = /^[A-Za-z0-9_-]{32,200}$/;

type AuthState = {
  token: string | null;
  clearSession: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

function createToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  let binary = "";
  bytes.forEach((value) => {
    binary += String.fromCharCode(value);
  });
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem(KEY);
    const next = stored && SESSION.test(stored) ? stored : createToken();
    if (next !== stored) window.localStorage.setItem(KEY, next);
    setToken(next);
  }, []);

  function clearSession() {
    const next = createToken();
    window.localStorage.setItem(KEY, next);
    setToken(next);
  }

  return <AuthContext.Provider value={{ token, clearSession }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
