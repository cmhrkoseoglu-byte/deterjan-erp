// /api/v1/users/* (yalnızca admin): kullanıcı listesi, yeni kullanıcı (geçici şifreyle), bilgi ve
// rol güncelleme, pasife alma / etkinleştirme, şifre sıfırlama, kilit açma, 2FA sıfırlama.
// Kullanıcılar silinmez; ayrılan çalışan pasife alınır.
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
}

/** Yeni kullanıcı bilgileri. Şifre girilmez; sistem geçici şifre üretir. */
export interface NewUser {
  username: string;
  full_name: string;
  email: string;
  phone: string;
  roles: Role[];
}

/** Güncellenebilen alanlar (kullanıcı adı değişmez); yalnızca gönderilenler değişir. */
export type UserChanges = Partial<Omit<NewUser, "username">>;

/** Yeni kullanıcı ya da şifre sıfırlama yanıtı: geçici şifre yalnızca burada, bir kez görünür. */
export interface IssuedPassword {
  user: UserRecord;
  temporary_password: string;
}

export async function listUsers(search = ""): Promise<Paginated<UserRecord>> {
  const { data } = await api.get<Paginated<UserRecord>>("/users/", {
    params: { page_size: 200, search: search || undefined },
  });
  return data;
}

/** Hata kodları: invalid_username, username_taken, full_name_required, validation_error. */
export async function createUser(input: NewUser): Promise<IssuedPassword> {
  const { data } = await api.post<IssuedPassword>("/users/", input);
  return data;
}

/** Hata kodları: cannot_remove_own_admin, last_admin, full_name_required, validation_error. */
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
