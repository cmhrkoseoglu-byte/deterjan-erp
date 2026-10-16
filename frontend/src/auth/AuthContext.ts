import { createContext, useContext } from "react";
import type { LoginPayload } from "../api/auth";
import type { CurrentUser } from "../api/types";

export interface AuthContextValue {
  user: CurrentUser | null;
  isLoading: boolean;
  /** Oturum hareketsizlik nedeniyle kapandı (giriş ekranı bilgi mesajı gösterir). */
  sessionExpired: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  logout: () => Promise<void>;
  /** `me` bilgisini sunucudan yeniden alır (2FA kurulumu, saha tableti işareti sonrası). */
  refresh: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth, AuthProvider içinde kullanılmalı");
  return value;
}
