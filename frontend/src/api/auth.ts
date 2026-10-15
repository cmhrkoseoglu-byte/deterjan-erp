import { api } from "./client";
import type { CurrentUser } from "./types";

export interface LoginPayload {
  username: string;
  password: string;
}

/** `csrftoken` çerezini ayarlatır (204). SPA açılışta bir kez çağırır. */
export async function fetchCsrf(): Promise<void> {
  await api.get("/auth/csrf/");
}

export async function fetchMe(): Promise<CurrentUser> {
  const { data } = await api.get<CurrentUser>("/auth/me/");
  return data;
}

/** Başarılı girişte `me` ile aynı gövde döner; hatalıysa 400 invalid_credentials. */
export async function login(payload: LoginPayload): Promise<CurrentUser> {
  const { data } = await api.post<CurrentUser>("/auth/login/", payload);
  return data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout/");
}
