import type { CurrentUser, RequiredAccess } from "../api/types";
import { tr } from "../i18n/tr";
import { useAuth } from "./AuthContext";
import { LEVEL_LABELS, MODULES, SECTIONS, type AccessLevel, type PermKey } from "./access.gen";

/**
 * Arayüzün yetki yardımcıları (docs/plan/kisi-yetkileri.md §5.9).
 *
 * `me.access` sunucuda hesaplanmış geçerli yetkidir (rol paketleri, ön koşullar, KVKK kısıtı ve
 * kişiye özel ayarlar uygulanmış): bölüm → "rvca" harfleri. Burada yalnız okunur; ön koşul ya da
 * paket yeniden hesaplanmaz. Admin (admin rolü ya da süper kullanıcı) bölümün her düzeyine
 * sahiptir; yalnız admin düzeyleri (ör. elle serbest bırakma) bu yüzden yalnız ona açılır.
 * Asıl yetki denetimi backend'dedir (CLAUDE.md §4.12).
 */

export type Level = AccessLevel;

const LETTERS: Readonly<Record<Level, string>> = {
  read: "r",
  view: "v",
  change: "c",
  approve: "a",
};

type MaybeUser = CurrentUser | null | undefined;

/** Admin mi (admin rolü ya da süper kullanıcı)? `me.is_admin`. */
export function isAdminUser(user: MaybeUser): boolean {
  return Boolean(user && (user.is_admin || user.is_superuser || user.roles.includes("admin")));
}

function meta(key: string) {
  return (SECTIONS as Readonly<Record<string, (typeof SECTIONS)[PermKey]>>)[key];
}

/** Admin bölümün kayıtlarını okur mu (Görür düzeyi olan ya da "Açık kayıtlar" bölümleri)? */
function adminReads(key: string): boolean {
  const section = meta(key);
  return Boolean(section && (section.levels.includes("view") || section.kind === "open_records"));
}

/** Bölümün düzeyine sahip mi? Varsayılan düzey Görür. Tanımsız bölüm ya da düzey `false`. */
export function can(
  user: MaybeUser,
  key: PermKey | string,
  level: Exclude<Level, "read"> = "view",
): boolean {
  if (!user) return false;
  if (isAdminUser(user)) return Boolean(meta(key)?.levels.includes(level));
  return (user.access?.[key] ?? "").includes(LETTERS[level]);
}

/** Bölümlerden birinin kayıtlarını okur mu (`r` ya da `v`)? */
export function canRead(user: MaybeUser, ...keys: (PermKey | string)[]): boolean {
  if (!user) return false;
  if (isAdminUser(user)) return keys.some(adminReads);
  return keys.some((key) => /[rv]/.test(user.access?.[key] ?? ""));
}

/** Verilen (bölüm, düzey) çiftlerinden birine sahip mi? */
export function canAny(
  user: MaybeUser,
  ...pairs: [PermKey | string, Exclude<Level, "read">][]
): boolean {
  return pairs.some(([key, level]) => can(user, key, level));
}

/**
 * Kendi sekmesi ya da sayfası olmayan, yalnız başka bir ekranın içinde görünen bölümler. Bunlar
 * modülün menüsünü ve sayfasını tek başına açmaz; açsaydı sayfa "Yetkiniz yok" gösterirdi.
 * Varsayılan paketlerde bu bölümlere sahip her rolün modülde sekmesi olan başka bir bölümü vardır.
 */
export const PANEL_ONLY_SECTIONS: ReadonlySet<string> = new Set([
  "golive.settings", // Hazırlık listesindeki canlıya geçiş tarihi kartı
  "maintenance.cleanings", // Üretim şarjını başlatırken temizlik kaydı
  "personnel.settings", // Puantaj, tatil ve bordro sayfalarındaki ayarlar
  "sales.shipped_lots", // Müşteri kartındaki sevk edilen lotlar
]);

/** Modülün ekranı olan bölümleri (menü ve modül sayfası bunların birleşimiyle açılır). */
export function moduleSections(moduleKey: string): PermKey[] {
  const module = MODULES.find((item) => item.key === moduleKey);
  if (!module) throw new Error(`Tanımsız modül: ${moduleKey}`);
  return module.sections.filter(
    (key) => SECTIONS[key].kind === "section" && !PANEL_ONLY_SECTIONS.has(key),
  );
}

/**
 * Menüde modül görünür, modül sayfası açılır mı: ekranı olan bölümlerinden birinde Görür
 * (plan §2, §5.9). Okuma (`r`) sayılmaz: açık okumalı bölümler o zaman herkese açılırdı.
 */
export function moduleVisible(user: MaybeUser, moduleKey: string): boolean {
  return moduleSections(moduleKey).some((key) => can(user, key, "view"));
}

/** Oturumdaki kullanıcıya bağlı yardımcılar. */
export function useCan() {
  const { user } = useAuth();
  return {
    user,
    can: (key: PermKey | string, level: Exclude<Level, "read"> = "view") => can(user, key, level),
    canRead: (...keys: (PermKey | string)[]) => canRead(user, ...keys),
    canAny: (...pairs: [PermKey | string, Exclude<Level, "read">][]) => canAny(user, ...pairs),
    moduleVisible: (moduleKey: string) => moduleVisible(user, moduleKey),
    isAdmin: isAdminUser(user),
  };
}

/**
 * Gereken yetkinin okunur adı: "Üretim › Üretim emirleri (Görür)". Anahtar bir modülse (modül
 * sayfası, bölümlerinden birinde Görür) "Üretim › bölümlerinden biri (Görür)". Tanımsız anahtar
 * `null`.
 */
export function describeAccess(need: RequiredAccess): string | null {
  const label = LEVEL_LABELS[need.level as Level];
  if (!label) return null;
  const section = meta(need.key);
  if (section) {
    const module = MODULES.find((item) => item.key === section.module);
    return `${module?.label ?? section.module} › ${section.label} (${label})`;
  }
  const module = MODULES.find((item) => item.key === need.key);
  if (module) return `${module.label} › ${tr.errors.anySection} (${label})`;
  return null;
}
