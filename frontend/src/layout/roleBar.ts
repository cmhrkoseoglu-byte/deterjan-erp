import type { CurrentUser, Role } from "../api/types";
import { isAdminUser } from "../auth/access";

export interface RoleBar {
  /** Rol ya da rolü olmayan (admin olmayan) kullanıcı için "neutral". */
  role: Role | "neutral";
  /** Degradenin başı (solda marka yazısının altı) ve sonu. */
  from: string;
  to: string;
}

/**
 * Üst çubuğun rengi rolü gösterir (DentMesher'daki gibi: yönetim altın, laboratuvar yeşil,
 * planlama mavi…); gündüz ve gecede aynı kalır. Ortak tablette hangi birimin ekranı olduğu
 * renkten anlaşılır. Beyaz yazının okunması için tonlar koyu tutuldu. Birden fazla rolü olan
 * kullanıcıda listede önce gelen rolün rengi kullanılır.
 */
export const ROLE_BARS: readonly RoleBar[] = [
  { role: "admin", from: "#0f172a", to: "#334155" },
  { role: "yonetim", from: "#8a5a06", to: "#a8760a" },
  { role: "planlama", from: "#1d4ed8", to: "#2563eb" },
  { role: "laboratuvar", from: "#0f7a52", to: "#0f8a5f" },
  { role: "uretim", from: "#3730a3", to: "#4f46e5" },
  { role: "dolum", from: "#0f766e", to: "#0d9488" },
  { role: "depo", from: "#c2410c", to: "#ea580c" },
  { role: "sevkiyat", from: "#6d28d9", to: "#7c3aed" },
  { role: "satin_alma", from: "#be185d", to: "#db2777" },
];

/** Rolü olmayan kullanıcının nötr rengi (plan §8 madde 1). */
export const NEUTRAL_BAR: RoleBar = { role: "neutral", from: "#374151", to: "#4b5563" };

/**
 * Kullanıcının üst çubuk rengi (rol görünümü). Rolü olmayan süper kullanıcı sistem yöneticisi
 * rengini, rolü olmayan diğer kullanıcılar nötr rengi alır (plan §8 madde 1).
 */
export function roleBar(user: CurrentUser | null): RoleBar {
  const bar = ROLE_BARS.find((item) => user?.roles.includes(item.role as Role));
  if (bar) return bar;
  return user && !isAdminUser(user) ? NEUTRAL_BAR : ROLE_BARS[0];
}
