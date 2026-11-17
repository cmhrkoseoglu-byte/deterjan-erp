import type { CurrentUser, Role } from "../api/types";

/**
 * Kullanıcı verilen rollerden en az birine sahip mi?
 * `admin` rolü ve süper kullanıcı her role sahip sayılır. Yalnız rolün görünümü içindir (plan
 * §5.9: üst bant rengi, açılış sayfası, rol kılavuzları, rozetler, varsayılan sekme tercih sırası);
 * erişim kararları `auth/access.ts` (`can`, `canRead`, `moduleVisible`) ile verilir.
 */
export function hasAnyRole(user: CurrentUser | null | undefined, roles?: readonly Role[]): boolean {
  if (!user) return false;
  if (!roles || roles.length === 0) return true;
  if (user.is_superuser || user.roles.includes("admin")) return true;
  return roles.some((role) => user.roles.includes(role));
}

export function displayName(user: CurrentUser): string {
  return user.full_name.trim() || user.username;
}
