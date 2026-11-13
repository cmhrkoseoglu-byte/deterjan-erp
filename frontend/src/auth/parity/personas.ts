import { ROLES, type CurrentUser, type Role } from "../../api/types";
import { userWith } from "../../test/fixtures";

/**
 * Ön yüz eşlik testinin kullanıcı tipleri (persona); backend sözleşme testindeki 14 personayla
 * aynı ad ve sırada (`backend/apps/core/tests/access_contract/personas.py`). Persona eklemek ya da
 * çıkarmak anlık görüntüyü değiştirir; bu da sahibin onayını ister.
 */

/** Admin dışındaki 8 rol, `ROLES` sırasıyla. */
export const PERSONA_ROLES: readonly Role[] = ROLES.filter((role) => role !== "admin");

export const PERSONAS: readonly string[] = [
  "anonymous",
  "inactive",
  "no_role",
  ...PERSONA_ROLES,
  "admin",
  "superuser",
  "depo+sevkiyat",
];

/**
 * Her persona için `me` yanıtı (anonim: `null`).
 *
 * - `inactive`: depo rolündeki pasif kullanıcı. Pasif kullanıcının oturumu açılmaz; ön yüz
 *   `is_active`'i görmez, bu yüzden depo kullanıcısı gibi davranır.
 * - `no_role`: rolü olmayan etkin kullanıcı;
 * - `superuser`: rolü olmayan süper kullanıcı;
 * - `depo+sevkiyat`: iki rollü kullanıcı.
 *
 * `me` yanıtına alan eklenirse (ör. kişiye özel yetkiler) `userWith` onları da doldurmalıdır.
 */
export function makePersonas(): Map<string, CurrentUser | null> {
  const users = new Map<string, CurrentUser | null>();
  users.set("anonymous", null);
  users.set("inactive", userWith("depo"));
  users.set("no_role", userWith());
  for (const role of PERSONA_ROLES) users.set(role, userWith(role));
  users.set("admin", userWith("admin"));
  users.set("superuser", { ...userWith(), is_superuser: true });
  users.set("depo+sevkiyat", userWith("depo", "sevkiyat"));
  if ([...users.keys()].join() !== PERSONAS.join()) {
    throw new Error("Persona listesi ile kullanıcılar aynı sırada değil.");
  }
  return users;
}
