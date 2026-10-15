import { useCallback, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as authApi from "../api/auth";
import { api, isUnauthenticated } from "../api/client";
import type { CurrentUser } from "../api/types";
import { AuthContext, type AuthContextValue } from "./AuthContext";

export const ME_QUERY_KEY = ["auth", "me"] as const;

async function loadCurrentUser(): Promise<CurrentUser | null> {
  try {
    return await authApi.fetchMe();
  } catch (error) {
    if (isUnauthenticated(error)) return null;
    throw error;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const meQuery = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: loadCurrentUser,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  useEffect(() => {
    // CSRF çerezi açılışta bir kez alınır; hata olursa ilk yazma isteği zaten 403 ile görünür.
    authApi.fetchCsrf().catch(() => undefined);

    // Herhangi bir istek 401 dönerse oturum sona ermiştir: kullanıcı "yok" sayılır,
    // RequireAuth giriş ekranına yönlendirir.
    const id = api.interceptors.response.use(undefined, (error) => {
      if (isUnauthenticated(error)) queryClient.setQueryData(ME_QUERY_KEY, null);
      return Promise.reject(error);
    });
    return () => api.interceptors.response.eject(id);
  }, [queryClient]);

  const login = useCallback(
    async (payload: authApi.LoginPayload) => {
      const user = await authApi.login(payload);
      queryClient.setQueryData(ME_QUERY_KEY, user);
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      // Önceki kullanıcıya ait önbelleği temizle; oturum bilgisi "yok" olarak kalır.
      queryClient.setQueryData(ME_QUERY_KEY, null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
    }
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({ user: meQuery.data ?? null, isLoading: meQuery.isPending, login, logout }),
    [meQuery.data, meQuery.isPending, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
