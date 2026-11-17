import { AxiosError, AxiosHeaders } from "axios";
import type { CurrentUser, Role } from "../api/types";
import { ROLE_ACCESS } from "../auth/access.gen";

/** Harf kümelerini birleştirir ("rv" + "vc" → "rvc"). */
function unionLetters(tables: readonly Readonly<Record<string, string>>[]): Record<string, string> {
  const merged: Record<string, string> = {};
  for (const table of tables) {
    for (const [key, text] of Object.entries(table)) {
      const letters = new Set([...(merged[key] ?? ""), ...text]);
      merged[key] = [..."rvca"].filter((letter) => letters.has(letter)).join("");
    }
  }
  return merged;
}

/**
 * Kişiye özel ayar yokken `me.access`: admin rolünde (ya da süper kullanıcıda) admin harfleri,
 * yoksa rolsüz tablo ile her rolün tablosunun birleşimi (backend `compute_access` ile aynı olduğunu
 * `test_role_access_union_matches_compute_access` denetler).
 */
export function accessFor(roles: readonly Role[], isSuperuser = false): Record<string, string> {
  if (isSuperuser || roles.includes("admin")) return { ...ROLE_ACCESS.admin };
  return unionLetters([ROLE_ACCESS[""], ...roles.map((role) => ROLE_ACCESS[role])]);
}

/** Verilen rollerle oturum açmış kullanıcının `me` yanıtı (yetki harfleri dahil). */
export function userWith(...roles: Role[]): CurrentUser {
  return {
    id: 1,
    username: roles[0] ?? "kullanici",
    full_name: "Deneme Kullanıcı",
    email: "",
    roles,
    is_superuser: false,
    is_admin: roles.includes("admin"),
    access: accessFor(roles),
    otp_enabled: false,
    password_change_required: false,
    otp_setup_required: false,
    field_device: false,
    idle_timeout_seconds: 3600,
  };
}

/** Rolü olmayan süper kullanıcının `me` yanıtı (admin sayılır). */
export function superuser(): CurrentUser {
  return { ...userWith(), is_superuser: true, is_admin: true, access: accessFor([], true) };
}

/** Kullanıcıdan verilen bölüm düzeylerini kaldırır (kişiye özel kaldırma; ör. `{"production.prep": "c"}`). */
export function withoutAccess(
  user: CurrentUser,
  removed: Readonly<Record<string, string>>,
): CurrentUser {
  const access = { ...user.access };
  for (const [key, letters] of Object.entries(removed)) {
    const rest = [...(access[key] ?? "")].filter((letter) => !letters.includes(letter)).join("");
    if (rest) access[key] = rest;
    else delete access[key];
  }
  return { ...user, access };
}

/** Kullanıcıya verilen bölüm düzeylerini ekler (kişiye özel ekleme; ör. `{"sales.orders": "v"}`). */
export function withAccess(
  user: CurrentUser,
  added: Readonly<Record<string, string>>,
): CurrentUser {
  const access = { ...user.access };
  for (const [key, letters] of Object.entries(added)) {
    const all = new Set([...(access[key] ?? ""), ...letters]);
    access[key] = [..."rvca"].filter((letter) => all.has(letter)).join("");
  }
  return { ...user, access };
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
