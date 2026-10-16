import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { tr } from "../i18n/tr";
import { IDLE_HEADER, idleSeconds } from "./idle";
import type { ApiError } from "./types";

// SPA ve API aynı origin'de (nginx). Django session + CSRF çerezi kullanılır;
// axios "csrftoken" çerezini okuyup X-CSRFToken başlığını otomatik ekler.
export const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  xsrfCookieName: "csrftoken",
  xsrfHeaderName: "X-CSRFToken",
  headers: { Accept: "application/json" },
});

// Her istek, kullanıcının kaç saniyedir işlem yapmadığını bildirir (bkz. idle.ts): arka plandaki
// yenilemeler oturumu açık tutmaz.
api.interceptors.request.use((config) => {
  config.headers.set(IDLE_HEADER, String(idleSeconds()));
  return config;
});

// CSRF çerezi yoksa ya da eskidiyse (403 csrf_failed) çerez yenilenir ve istek bir kez tekrarlanır.
api.interceptors.response.use(undefined, async (error: AxiosError<ApiError>) => {
  const config = error.config as
    (InternalAxiosRequestConfig & { _csrfRetried?: boolean }) | undefined;
  if (error.response?.status === 403 && error.response.data?.code === "csrf_failed" && config) {
    if (!config._csrfRetried) {
      config._csrfRetried = true;
      await api.get("/auth/csrf/");
      return api.request(config);
    }
  }
  return Promise.reject(error);
});

/** Oturum yok ya da sona ermiş mi? (401 not_authenticated; rol yetkisi yoksa 403 döner.) */
export function isUnauthenticated(error: unknown): boolean {
  return (error as AxiosError | undefined)?.response?.status === 401;
}

/** Hareketsizlik nedeniyle sunucu oturumu kapattı mı? (401 session_expired) */
export function isSessionExpired(error: unknown): boolean {
  return isUnauthenticated(error) && getErrorCode(error) === "session_expired";
}

/** Rol 2FA istiyor ama kurulmamış mı? (403 otp_setup_required) */
export function isOtpSetupRequired(error: unknown): boolean {
  return (
    (error as AxiosError | undefined)?.response?.status === 403 &&
    getErrorCode(error) === "otp_setup_required"
  );
}

/** API hatasından kullanıcıya gösterilecek Türkçe mesajı çıkarır. */
export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) return tr.common.networkError;
    const data = error.response.data as ApiError | undefined;
    if (data && typeof data === "object") {
      if (typeof data.detail === "string") return data.detail;
    }
  }
  return tr.common.unexpectedError;
}

/** API iş kuralı hatasının sabit kodu (ör. "lot_not_reserved"); yoksa boş metin. */
export function getErrorCode(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as ApiError | undefined;
    if (data && typeof data === "object" && typeof data.code === "string") return data.code;
  }
  return "";
}
