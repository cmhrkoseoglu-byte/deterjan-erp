import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as authApi from "../api/auth";
import { api, isOtpSetupRequired, isSessionExpired, isUnauthenticated } from "../api/client";
import { idleSeconds, markActivity, startIdleTracking } from "../api/idle";
import type { CurrentUser } from "../api/types";
import { installClientErrorHandlers, setClientErrorReporting } from "../errors/clientErrors";
import { AuthContext, type AuthContextValue } from "./AuthContext";

export const ME_QUERY_KEY = ["auth", "me"] as const;

/** İstemci tarafı hareketsizlik denetiminin sıklığı (ms). */
const IDLE_CHECK_MS = 15_000;
/** Sunucu saatindeki küçük farklara rağmen bu kadar geç kalınırsa oturum yerelde kapatılır (sn). */
const IDLE_GRACE_SECONDS = 120;

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [sessionExpired, setSessionExpired] = useState(false);

  const meQuery = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: async (): Promise<CurrentUser | null> => {
      try {
        return await authApi.fetchMe();
      } catch (error) {
        if (isUnauthenticated(error)) {
          if (isSessionExpired(error)) setSessionExpired(true);
          return null;
        }
        throw error;
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const user = meQuery.data ?? null;
  const userRef = useRef(user);
  userRef.current = user;

  const expire = useCallback(() => {
    setSessionExpired(true);
    queryClient.setQueryData(ME_QUERY_KEY, null);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
  }, [queryClient]);

  useEffect(() => {
    startIdleTracking();
    installClientErrorHandlers();
    // CSRF çerezi açılışta bir kez alınır; hata olursa ilk yazma isteği zaten 403 ile görünür.
    authApi.fetchCsrf().catch(() => undefined);

    const id = api.interceptors.response.use(undefined, (error) => {
      if (isSessionExpired(error)) {
        // Hareketsizlik nedeniyle oturum kapandı: giriş ekranı nedenini gösterir.
        expire();
      } else if (isUnauthenticated(error)) {
        // Oturum başka nedenle sona erdi: kullanıcı "yok" sayılır, RequireAuth yönlendirir.
        queryClient.setQueryData(ME_QUERY_KEY, null);
      } else if (isOtpSetupRequired(error) && !userRef.current?.otp_setup_required) {
        // Rol 2FA istiyor ama kurulmamış: `me` yenilenince RequireAuth Güvenlik sayfasına götürür.
        queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
      }
      return Promise.reject(error);
    });
    return () => api.interceptors.response.eject(id);
  }, [queryClient, expire]);

  useEffect(() => {
    setClientErrorReporting(Boolean(user));
  }, [user]);

  // İstemci tarafı hareketsizlik denetimi: süre dolunca `me` sorulur; sunucu 401 session_expired
  // dönünce yukarıdaki yakalayıcı oturumu kapatır. Sunucu hâlâ açık sayıyorsa (saat farkı) bir süre
  // sonra yerelde kapatılır.
  const timeout = user?.idle_timeout_seconds ?? 0;
  useEffect(() => {
    if (!timeout) return;
    let checking = false;
    const timer = window.setInterval(async () => {
      const idle = idleSeconds();
      if (idle < timeout || checking) return;
      if (idle >= timeout + IDLE_GRACE_SECONDS) {
        authApi.logout().catch(() => undefined);
        expire();
        return;
      }
      checking = true;
      try {
        await api.get("/auth/me/");
      } catch {
        // 401 yakalayıcıda işlenir; ağ hatasında bir sonraki denetim tekrar dener.
      } finally {
        checking = false;
      }
    }, IDLE_CHECK_MS);
    return () => window.clearInterval(timer);
  }, [timeout, expire]);

  const login = useCallback(
    async (payload: authApi.LoginPayload) => {
      const loggedIn = await authApi.login(payload);
      markActivity();
      setSessionExpired(false);
      queryClient.setQueryData(ME_QUERY_KEY, loggedIn);
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      // Önceki kullanıcıya ait önbelleği temizle; oturum bilgisi "yok" olarak kalır.
      setSessionExpired(false);
      queryClient.setQueryData(ME_QUERY_KEY, null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
    }
  }, [queryClient]);

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, isLoading: meQuery.isPending, sessionExpired, login, logout, refresh }),
    [user, meQuery.isPending, sessionExpired, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
