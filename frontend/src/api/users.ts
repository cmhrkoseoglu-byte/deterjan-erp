// /api/v1/users/* (yalnızca admin): kullanıcı listesi, yeni kullanıcı (geçici şifreyle), bilgi
// güncelleme, pasife alma / etkinleştirme, şifre sıfırlama, kilit açma, 2FA sıfırlama.
// Kullanıcılar silinmez; ayrılan çalışan pasife alınır. Roller ve kişiye özel yetkiler kişinin
// Yetkiler ekranından değişir (api/access.ts, plan §8 madde 13).
import { api } from "./client";
import type { Paginated, Role } from "./types";

export interface UserRecord {
  id: number;
  username: string;
  full_name: string;
  email: string;
  phone: string;
  roles: Role[];
  is_active: boolean;
  is_superuser: boolean;
  /** Geçici şifreyle açıldı ya da şifresi sıfırlandı; ilk girişte kendi şifresini belirleyecek. */
  must_change_password: boolean;
  last_login: string | null;
  date_joined: string;
  /** Hatalı girişler yüzünden şu an kilitli mi? */
  is_locked: boolean;
  otp_enabled: boolean;
  /** Etkin kişiye özel ayarlar (etkisizler dahil): eklenen ve kaldırılan yetki sayısı. */
  personal_counts: { granted: number; revoked: number };
}

/** Yeni kullanıcı bilgileri. Şifre girilmez; sistem geçici şifre üretir. */
export interface NewUser {
  username: string;
  full_name: string;
  email: string;
  phone: string;
  roles: Role[];
}

/**
 * Güncellenebilen alanlar (kullanıcı adı değişmez); yalnızca gönderilenler değişir. Roller burada
 * değişmez (`roles_on_access_page`): Yetkiler ekranında, gerekçe yazılarak değişir.
 */
export type UserChanges = Partial<Omit<NewUser, "username" | "roles">>;

/** Kullanıcı listesi süzgeçleri (adreste saklanır). */
export interface UserFilters {
  search?: string;
  role?: Role | "";
  /** "true" etkin, "false" pasif, boş hepsi. */
  active?: "true" | "false" | "";
  /** Yalnız kişiye özel yetkisi olanlar. */
  personal?: boolean;
}

/** Yeni kullanıcı ya da şifre sıfırlama yanıtı: geçici şifre yalnızca burada, bir kez görünür. */
export interface IssuedPassword {
  user: UserRecord;
  temporary_password: string;
}

export async function listUsers(filters: UserFilters = {}): Promise<Paginated<UserRecord>> {
  const { data } = await api.get<Paginated<UserRecord>>("/users/", {
    params: {
      page_size: 200,
      search: filters.search || undefined,
      role: filters.role || undefined,
      is_active: filters.active || undefined,
      has_personal: filters.personal ? "true" : undefined,
    },
  });
  return data;
}

/** Hata kodları: invalid_username, username_taken, full_name_required, validation_error. */
export async function createUser(input: NewUser): Promise<IssuedPassword> {
  const { data } = await api.post<IssuedPassword>("/users/", input);
  return data;
}

/** Hata kodları: full_name_required, validation_error, roles_on_access_page. */
export async function updateUser(id: number, changes: UserChanges): Promise<UserRecord> {
  const { data } = await api.patch<UserRecord>(`/users/${id}/`, changes);
  return data;
}

/** Pasife alma hata kodları: cannot_deactivate_self, last_admin. */
export async function setUserActive(id: number, active: boolean): Promise<UserRecord> {
  const { data } = await api.post<UserRecord>(
    `/users/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

/** Hata kodları: use_security_page (kendi şifreniz), user_inactive. */
export async function resetUserPassword(id: number): Promise<IssuedPassword> {
  const { data } = await api.post<IssuedPassword>(`/users/${id}/reset-password/`);
  return data;
}

export async function unlockUser(id: number): Promise<UserRecord> {
  const { data } = await api.post<UserRecord>(`/users/${id}/unlock/`);
  return data;
}

export async function resetUserOtp(id: number): Promise<UserRecord> {
  const { data } = await api.post<UserRecord>(`/users/${id}/reset-otp/`);
  return data;
}
