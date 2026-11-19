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
  /** Admin rolü ya da süper kullanıcı (docs/plan/kisi-yetkileri.md §5.9): her yetkiye sahiptir. */
  is_admin: boolean;
  /**
   * Geçerli yetkiler: bölüm → "rvca" harfleri (r kayıtları okur, v görür, c değiştirir, a onaylar).
   * Sunucu hesaplar (ön koşullar, KVKK kısıtı ve kişiye özel ayarlar uygulanmış); arayüz yalnız
   * okur (`auth/access.ts`). Yetkisi olmayan bölüm yazılmaz.
   */
  access: Readonly<Record<string, string>>;
  /**
   * Hesap türü: çalışan ya da müşteri / tedarikçi portalı kullanıcısı (portal kullanıcısında
   * `access` boştur; arayüz yalnız `/portal` düzenini açar).
   */
  account_type: "staff" | "customer_portal" | "supplier_portal";
  /** İki aşamalı doğrulama (doğrulayıcı uygulama) kurulu mu? */
  otp_enabled: boolean;
  /**
   * Yöneticinin verdiği geçici şifreyle girdi: kendi şifresini belirleyene kadar diğer API'ler
   * 403 password_change_required döner.
   */
  password_change_required: boolean;
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
  /** Yetki hatasında (`code` = "permission_denied") eksik yetkiler: bölüm ve düzey. */
  required?: RequiredAccess[];
}

/** Gereken yetki: bölüm anahtarı (ör. "production.orders") ya da modül anahtarı ve düzey. */
export interface RequiredAccess {
  key: string;
  level: "read" | "view" | "change" | "approve";
}
