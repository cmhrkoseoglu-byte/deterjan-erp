import { createContext, useContext } from "react";
import type { LoginPayload } from "../api/auth";
import type { CurrentUser } from "../api/types";

export interface AuthContextValue {
  user: CurrentUser | null;
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth, AuthProvider içinde kullanılmalı");
  return value;
}
