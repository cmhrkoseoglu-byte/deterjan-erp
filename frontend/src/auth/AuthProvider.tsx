import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import * as authApi from "../api/auth";
import {
  api,
  isOtpSetupRequired,
  isPasswordChangeRequired,
  isPermissionDenied,
  isSessionExpired,
  isUnauthenticated,
} from "../api/client";
import { idleSeconds, markActivity, startIdleTracking } from "../api/idle";
import type { CurrentUser } from "../api/types";
import { installClientErrorHandlers, setClientErrorReporting } from "../errors/clientErrors";
import { AuthContext, type AuthContextValue } from "./AuthContext";

export const ME_QUERY_KEY = ["auth", "me"] as const;

/** İstemci tarafı hareketsizlik denetiminin sıklığı (ms). */
const IDLE_CHECK_MS = 15_000;
/** Sunucu saatindeki küçük farklara rağmen bu kadar geç kalınırsa oturum yerelde kapatılır (sn). */
const IDLE_GRACE_SECONDS = 120;
/**
 * Yetki değişikliğini yakalamak için `me` yeniden sorulur (plan §5.9, §8 madde 11): pencereye
 * dönünce (son yenilemeden en az bu kadar sonra, ms) ...
 */
export const FOCUS_REFRESH_MS = 30_000;
/**
 * ... ve yetki hatası (403 permission_denied) alınca. Aynı anda gelen 403'ler tek bir yenileme
 * yapar; yenilemeden hemen sonra gelenler yeniden sormaz (ms).
 */
export const DENIED_REFRESH_MS = 5_000;

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

  /** `me` son yenilemeden bu yana `minAge` ms geçtiyse (ve yenilenmiyorsa) yeniden sorar. */
  const refreshIfStale = useCallback(
    (minAge: number) => {
      const state = queryClient.getQueryState(ME_QUERY_KEY);
      if (!state?.data || state.fetchStatus === "fetching") return;
      if (Date.now() - state.dataUpdatedAt < minAge) return;
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
    [queryClient],
  );

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
      } else if (
        (isPasswordChangeRequired(error) && !userRef.current?.password_change_required) ||
        (isOtpSetupRequired(error) && !userRef.current?.otp_setup_required)
      ) {
        // Geçici şifreyle girdi ya da rol 2FA istiyor ama kurulmamış: `me` yenilenince
        // RequireAuth Güvenlik sayfasına götürür.
        queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
      } else if (isPermissionDenied(error)) {
        // Yetki sayfa açıkken değişmiş olabilir: menü, sekme ve düğmeler yeni `me` ile çizilir;
        // açık sayfa artık izinli değilse koruması "Yetkiniz yok" gösterir (plan §6.5).
        refreshIfStale(DENIED_REFRESH_MS);
      }
      return Promise.reject(error);
    });
    return () => api.interceptors.response.eject(id);
  }, [queryClient, expire, refreshIfStale]);

  // Pencereye dönünce `me` yenilenir: başka sekmede ya da yöneticinin değiştirdiği yetki görünür.
  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState !== "hidden") refreshIfStale(FOCUS_REFRESH_MS);
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refreshIfStale]);

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
