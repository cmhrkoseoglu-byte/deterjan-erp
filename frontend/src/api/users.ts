// /api/v1/users/* (yalnızca admin): kullanıcı listesi, kilit açma, 2FA sıfırlama.
// Kullanıcı ekleme ve rol atama Django yönetim panelinden yapılır.
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
  last_login: string | null;
  date_joined: string;
  /** Hatalı girişler yüzünden şu an kilitli mi? */
  is_locked: boolean;
  otp_enabled: boolean;
}

export async function listUsers(search = ""): Promise<Paginated<UserRecord>> {
  const { data } = await api.get<Paginated<UserRecord>>("/users/", {
    params: { page_size: 200, search: search || undefined },
  });
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
