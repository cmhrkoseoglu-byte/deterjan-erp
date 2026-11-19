import type { AccessSaveResult, Letters } from "../../../api/access";
import type { CurrentUser, Role } from "../../../api/types";
import { visibleMenu } from "../../../layout/menu";

/** Menü kuralı için kişinin rolleri ve yetki harfleriyle bir `me` benzeri. */
export function menuUser(roles: Role[], letters: Letters, superuser = false): CurrentUser {
  return {
    id: 0,
    username: "",
    full_name: "",
    email: "",
    roles,
    is_superuser: superuser,
    is_admin: superuser || roles.includes("admin"),
    access: letters,
    account_type: "staff",
    otp_enabled: true,
    password_change_required: false,
    otp_setup_required: false,
    field_device: false,
    idle_timeout_seconds: 0,
  };
}

/**
 * Menüye eklenecek ve menüden kalkacak modüller: istemcide, sunucunun ön izlemesindeki önceki ve
 * sonraki harflerden `visibleMenu` ile (plan §6.1; menü kuralı yalnız ön yüzdedir).
 */
export function menuDiff(
  result: AccessSaveResult,
  superuser: boolean,
): { added: string[]; removed: string[] } {
  const before = visibleMenu(menuUser(result.roles.before, result.access.before, superuser));
  const after = visibleMenu(menuUser(result.roles.after, result.access.after, superuser));
  const beforeKeys = new Set(before.map((item) => item.key));
  const afterKeys = new Set(after.map((item) => item.key));
  return {
    added: after.filter((item) => !beforeKeys.has(item.key)).map((item) => item.label),
    removed: before.filter((item) => !afterKeys.has(item.key)).map((item) => item.label),
  };
}
