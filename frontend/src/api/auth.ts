import { api } from "./client";
import type { CurrentUser } from "./types";

export interface LoginPayload {
  username: string;
  password: string;
  /** İki aşamalı doğrulama kodu (6 hane) ya da kurtarma kodu ("abcd-efgh"). */
  otp_code?: string;
}

/** `csrftoken` çerezini ayarlatır (204). SPA açılışta bir kez çağırır. */
export async function fetchCsrf(): Promise<void> {
  await api.get("/auth/csrf/");
}

export async function fetchMe(): Promise<CurrentUser> {
  const { data } = await api.get<CurrentUser>("/auth/me/");
  return data;
}

/**
 * Başarılı girişte `me` ile aynı gövde döner. 400 hata kodları: invalid_credentials,
 * account_locked (detail ne kadar süre kilitli olduğunu söyler), otp_required (2FA kurulu; aynı
 * bilgilerle `otp_code` eklenerek yeniden gönderilir), invalid_otp.
 */
export async function login(payload: LoginPayload): Promise<CurrentUser> {
  const { data } = await api.post<CurrentUser>("/auth/login/", payload);
  return data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout/");
}

// --- Güvenlik (Faz 5): şifre, iki aşamalı doğrulama, saha tableti ---

export interface SecurityStatus {
  otp_enabled: boolean;
  /** Rol 2FA istiyor: kapatılamaz. */
  otp_required: boolean;
  recovery_codes_remaining: number;
  field_device: boolean;
  idle_timeout_seconds: number;
  /** Şifre kuralları (Türkçe). */
  password_help: string[];
}

export interface OtpSetup {
  secret: string;
  /** otpauth:// adresi (QR kodun içeriği). */
  uri: string;
  /** QR kod, SVG metni. */
  qr_svg: string;
}

export interface RecoveryCodes {
  recovery_codes: string[];
}

export async function fetchSecurity(): Promise<SecurityStatus> {
  const { data } = await api.get<SecurityStatus>("/auth/security/");
  return data;
}

/** 204; hata kodları wrong_password, weak_password (detail kuralları sayar). */
export async function changePassword(payload: {
  old_password: string;
  new_password: string;
}): Promise<void> {
  await api.post("/auth/password/", payload);
}

export async function startOtpSetup(): Promise<OtpSetup> {
  const { data } = await api.post<OtpSetup>("/auth/otp/setup/");
  return data;
}

/** Uygulamadaki ilk kodla kurulumu tamamlar; kurtarma kodları yalnızca bu yanıtta gelir. */
export async function confirmOtpSetup(code: string): Promise<RecoveryCodes> {
  const { data } = await api.post<RecoveryCodes>("/auth/otp/confirm/", { code });
  return data;
}

/** Geçerli bir kodla yeni kurtarma kodları (eskiler geçersiz olur). */
export async function regenerateRecoveryCodes(code: string): Promise<RecoveryCodes> {
  const { data } = await api.post<RecoveryCodes>("/auth/otp/recovery-codes/", { code });
  return data;
}

/** Şifreyle 2FA'yı kapatır (204); rol zorunlu kılıyorsa kapatılamaz. */
export async function disableOtp(password: string): Promise<void> {
  await api.post("/auth/otp/disable/", { password });
}

/** Bu tarayıcıyı saha tableti olarak işaretler ya da işareti kaldırır (yalnızca admin). */
export async function setFieldDevice(enabled: boolean): Promise<{ enabled: boolean }> {
  const { data } = await api.post<{ enabled: boolean }>("/auth/field-device/", { enabled });
  return data;
}
