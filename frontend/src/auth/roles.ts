import type { CurrentUser, Role } from "../api/types";

/**
 * Kullanıcı verilen rollerden en az birine sahip mi?
 * `admin` rolü ve süper kullanıcı her role sahip sayılır. Bu yalnızca arayüz içindir;
 * asıl yetki kontrolü backend'dedir (CLAUDE.md §4.12).
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
