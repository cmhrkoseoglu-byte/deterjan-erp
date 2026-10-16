// /api/v1/auth/* sözleşmesi: docs/DECISIONS.md "Kimlik doğrulama API sözleşmesi".
// İleride openapi-typescript ile /api/schema/'dan üretilebilir.

export const ROLES = [
  "admin",
  "yonetim",
  "planlama",
  "depo",
  "uretim",
  "laboratuvar",
  "dolum",
  "sevkiyat",
  "satin_alma",
] as const;

export type Role = (typeof ROLES)[number];

export interface CurrentUser {
  id: number;
  username: string;
  full_name: string;
  email: string;
  /** Rol kodları (Django Group adları), alfabetik sıralı. */
  roles: Role[];
  is_superuser: boolean;
  /** İki aşamalı doğrulama (doğrulayıcı uygulama) kurulu mu? */
  otp_enabled: boolean;
  /** Rol 2FA istiyor ama kurulmamış: kurulana kadar diğer API'ler 403 otp_setup_required döner. */
  otp_setup_required: boolean;
  /** Bu tarayıcı saha tableti olarak işaretli mi? (kısa hareketsizlik süresi) */
  field_device: boolean;
  /** Bu süre kullanıcı işlem yapmazsa sunucu oturumu kapatır (401 session_expired). */
  idle_timeout_seconds: number;
}

/** Sayfalı liste yanıtı (`?page`, `?page_size`, en çok 500). */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Backend iş kuralı hatası biçimi (CLAUDE.md §6). */
export interface ApiError {
  code?: string;
  detail?: string;
  /** Alan doğrulama hataları (`code` = "validation_error"). */
  errors?: Record<string, string[]>;
}
