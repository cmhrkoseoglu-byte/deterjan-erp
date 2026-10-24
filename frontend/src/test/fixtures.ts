import { AxiosError, AxiosHeaders } from "axios";
import type { CurrentUser, Role } from "../api/types";

export function userWith(...roles: Role[]): CurrentUser {
  return {
    id: 1,
    username: roles[0] ?? "kullanici",
    full_name: "Deneme Kullanıcı",
    email: "",
    roles,
    is_superuser: false,
    otp_enabled: false,
    password_change_required: false,
    otp_setup_required: false,
    field_device: false,
    idle_timeout_seconds: 3600,
  };
}

export function httpError(status: number, data: unknown = {}) {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError("hata", String(status), config, null, {
    status,
    statusText: "",
    headers: {},
    config,
    data,
  });
}

export function page<T>(results: T[]) {
  return { count: results.length, next: null, previous: null, results };
}
