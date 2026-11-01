"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

type AuthState = {
  configured: boolean;
  token: string | null;
  email: string | null;
  client: SupabaseClient | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<string>;
  signOut: () => Promise<void>;
  useToken: (token: string) => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  const configured = Boolean(url && anon);
  const client = useMemo(() => (configured ? createClient(url, anon) : null), [configured, url, anon]);
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!client) {
      const stored = window.sessionStorage.getItem("shade.token");
      if (stored) setToken(stored);
      return;
    }
    client.auth.getSession().then(({ data }) => {
      setToken(data.session?.access_token ?? null);
      setEmail(data.session?.user.email ?? null);
    });
    const { data } = client.auth.onAuthStateChange((_event, session) => {
      setToken(session?.access_token ?? null);
      setEmail(session?.user.email ?? null);
    });
    return () => data.subscription.unsubscribe();
  }, [client]);

  const value: AuthState = {
    configured,
    token,
    email,
    client,
    async signIn(emailAddress, password) {
      if (!client) throw new Error("Supabase is not configured in this frontend build.");
      const { error } = await client.auth.signInWithPassword({ email: emailAddress, password });
      if (error) throw error;
    },
    async signUp(emailAddress, password) {
      if (!client) throw new Error("Supabase is not configured in this frontend build.");
      const { error } = await client.auth.signUp({ email: emailAddress, password });
      if (error) throw error;
      return "Check your email if this project requires confirmation, then sign in.";
    },
    async signOut() {
      if (client) await client.auth.signOut();
      window.sessionStorage.removeItem("shade.token");
      setToken(null);
      setEmail(null);
    },
    useToken(next) {
      window.sessionStorage.setItem("shade.token", next);
      setToken(next);
      setEmail("local token");
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
