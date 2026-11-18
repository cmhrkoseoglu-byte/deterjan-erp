// Yetkiler ekranının saf hesabı (docs/plan/kisi-yetkileri.md §5.3, §6.1): rol varsayılanı, taslağın
// ön izlemesi, hücre durumu, tıklama ve toplu işlemler. React içermez.
//
// Ön izleme backend'deki `compute_access`'in aynısıdır ama yalnız canlı ipucu içindir; kaydetmeden
// önceki özet her zaman sunucunun ön izlemesidir (`dry_run`).
import type { Effect, OverrideSpec } from "../../../api/access";
import { ROLES, type Role } from "../../../api/types";
import {
  HOLDER_LABELS,
  LEVEL_LABELS,
  MODULES,
  PACKAGES,
  READERS,
  ROLE_ACCESS,
  SECTIONS,
  type AccessLevel,
  type SectionMeta,
} from "../../../auth/access.gen";

export type GrantLevel = Exclude<AccessLevel, "read">;
export type Letters = Record<string, string>;
/** `${bölüm}|${düzey}` → ekleme ya da kaldırma. */
export type OverrideMap = ReadonlyMap<string, Effect>;
export interface Draft {
  roles: Role[];
  overrides: OverrideMap;
}

export type CellState = "role" | "granted" | "revoked" | "none" | "locked" | "absent";
export type LockReason = "everyone" | "any_role" | "admin_only" | "kvkk";
export type Ineffective = "redundant" | "dropped_prereq" | "dropped_view" | "dropped_kvkk";

export interface CellInfo {
  state: CellState;
  lockReason?: LockReason;
  /** Varsayılanı veren paket sahipleri ("Herkes", "Depo", …). */
  sources: string[];
  /** Ön izlemede (ön koşullar, KVKK, Görür bağı uygulanmış) var mı? */
  effective: boolean;
  /** Taslaktaki ayar kayıtlı olandan farklı (sarı nokta). */
  dirty: boolean;
  ineffective?: Ineffective;
}

export interface Note {
  /** Notun gösterileceği bölüm satırı. */
  key: string;
  text: string;
  error?: boolean;
}

export interface ChangeResult {
  draft: Draft;
  notes: Note[];
}

const LETTER: Readonly<Record<AccessLevel, string>> = {
  read: "r",
  view: "v",
  change: "c",
  approve: "a",
};
const ORDER = "rvca";
const ALL_LEVELS: readonly AccessLevel[] = ["read", "view", "change", "approve"];
export const GRANT_LEVELS: readonly GrantLevel[] = ["view", "change", "approve"];
const HOLDER_ROLES: readonly string[] = ROLES.filter((role) => role !== "admin");

export function cellId(key: string, level: string): string {
  return `${key}|${level}`;
}

export function parseCellId(id: string): { key: string; level: AccessLevel } {
  const at = id.lastIndexOf("|");
  return { key: id.slice(0, at), level: id.slice(at + 1) as AccessLevel };
}

export function section(key: string): SectionMeta | undefined {
  return (SECTIONS as Readonly<Record<string, SectionMeta>>)[key];
}

export function moduleLabel(moduleKey: string): string {
  return MODULES.find((item) => item.key === moduleKey)?.label ?? moduleKey;
}

/** "Satın alma › Satın alma siparişleri: Değiştirir" */
export function cellLabel(key: string, level: AccessLevel): string {
  const meta = section(key);
  if (!meta) return `${key}: ${level}`;
  return `${moduleLabel(meta.module)} › ${meta.label}: ${LEVEL_LABELS[level]}`;
}

/** Ön koşulun kısa adı: hassas veride bölümün adı ("Fiyatları görür"), ötekilerde "Bölüm (Düzey)". */
function needLabel(key: string, level: AccessLevel): string {
  const meta = section(key);
  if (!meta) return key;
  return meta.kind === "sensitive" ? meta.label : `${meta.label} (${LEVEL_LABELS[level]})`;
}

export function hasLetter(letters: Readonly<Letters>, key: string, level: AccessLevel): boolean {
  return (letters[key] ?? "").includes(LETTER[level]);
}

/** Harf kümelerini birleştirir ("rv" + "vc" → "rvc"). */
export function unionLetters(tables: readonly Readonly<Record<string, string>>[]): Letters {
  const merged: Letters = {};
  for (const table of tables) {
    for (const [key, text] of Object.entries(table)) {
      const letters = new Set([...(merged[key] ?? ""), ...text]);
      merged[key] = [...ORDER].filter((letter) => letters.has(letter)).join("");
    }
  }
  return merged;
}

export function isAdminDraft(roles: readonly string[]): boolean {
  return roles.includes("admin");
}

/** Rol varsayılanı (kişiye özel ayar yokken `me.access`). */
export function defaultLetters(roles: readonly Role[]): Letters {
  if (isAdminDraft(roles)) return { ...ROLE_ACCESS.admin };
  return unionLetters([ROLE_ACCESS[""], ...roles.map((role) => ROLE_ACCESS[role] ?? {})]);
}

function entriesOf(table: Readonly<Record<string, string>> | undefined): string[] {
  const result: string[] = [];
  for (const [key, text] of Object.entries(table ?? {})) {
    for (const level of ALL_LEVELS) {
      if (text.includes(LETTER[level])) result.push(cellId(key, level));
    }
  }
  return result;
}

function openRecordsKey(moduleKey: string): string | undefined {
  return MODULES.find((item) => item.key === moduleKey)?.sections.find(
    (key) => SECTIONS[key].kind === "open_records",
  );
}

/**
 * Taslağın geçerli yetkisi: backend `compute_access` ile aynı sıra (plan §5.3). Admin taslağı admin
 * harflerini alır.
 */
export function previewAccess(roles: readonly Role[], overrides: OverrideMap): Letters {
  if (isAdminDraft(roles)) return { ...ROLE_ACCESS.admin };
  const held = new Set(roles.filter((role) => HOLDER_ROLES.includes(role)));
  const entries = new Set(entriesOf(PACKAGES["*"]));
  if (held.size > 0) entriesOf(PACKAGES["+"]).forEach((id) => entries.add(id));
  for (const role of held) entriesOf(PACKAGES[role]).forEach((id) => entries.add(id));

  const revokedView = new Set<string>();
  for (const [id, effect] of overrides) {
    const { key, level } = parseCellId(id);
    const meta = section(key);
    if (!meta || !meta.levels.includes(level)) continue;
    if (effect === "grant") {
      if (!meta.adminOnly.includes(level) && meta.kind !== "open_records") entries.add(id);
    }
  }
  for (const [id, effect] of overrides) {
    const { key, level } = parseCellId(id);
    const meta = section(key);
    if (effect !== "revoke" || !meta || !meta.levels.includes(level)) continue;
    if (meta.locked.includes(level)) continue;
    entries.delete(id);
    if (level === "view") revokedView.add(key);
  }
  for (const id of [...entries]) {
    const { key, level } = parseCellId(id);
    if ((level === "change" || level === "approve") && section(key)?.levels.includes("view"))
      entries.add(cellId(key, "view"));
  }
  for (const key of revokedView) {
    for (const level of GRANT_LEVELS) entries.delete(cellId(key, level));
  }
  for (const id of [...entries]) {
    const restricted = section(parseCellId(id).key)?.restrictedToRole;
    if (restricted && !held.has(restricted as Role)) entries.delete(id);
  }
  applyRequirements(entries);

  for (const meta of Object.values(SECTIONS) as SectionMeta[]) {
    if (meta.kind === "open_records" || !meta.levels.includes("view")) continue;
    if (reads(meta, entries, held.size > 0)) entries.add(cellId(meta.key, "read"));
  }
  const result: Letters = {};
  for (const key of Object.keys(SECTIONS)) {
    const text = ALL_LEVELS.filter((level) => entries.has(cellId(key, level)))
      .map((level) => LETTER[level])
      .join("");
    if (text) result[key] = text;
  }
  return result;
}

function requirementsOf(meta: SectionMeta, level: AccessLevel): string[] {
  return meta.requires
    .filter((item) => item.level === "*" || item.level === level)
    .map((item) => cellId(item.key, item.need));
}

function applyRequirements(entries: Set<string>): void {
  let changed = true;
  while (changed) {
    changed = false;
    for (const id of [...entries].sort()) {
      const { key, level } = parseCellId(id);
      const meta = section(key);
      if (!meta) continue;
      const missing = requirementsOf(meta, level).some((need) => !entries.has(need));
      const blind =
        (level === "change" || level === "approve") &&
        meta.levels.includes("view") &&
        !entries.has(cellId(key, "view"));
      if (missing || blind) {
        entries.delete(id);
        changed = true;
      }
    }
  }
}

function reads(meta: SectionMeta, entries: Set<string>, hasRole: boolean): boolean {
  if (entries.has(cellId(meta.key, "view"))) return true;
  if (meta.read === "shared") return true;
  if (meta.read === "any_role") return hasRole;
  if (meta.read === "open") {
    const records = openRecordsKey(meta.module);
    return records !== undefined && entries.has(cellId(records, "read"));
  }
  return false;
}

/** Varsayılanı veren paket sahipleri: "Herkes", "Rolü olan herkes" ya da rollerin adları. */
export function defaultSources(key: string, level: AccessLevel, roles: readonly Role[]): string[] {
  if (isAdminDraft(roles)) return [];
  if (hasLetter(ROLE_ACCESS[""], key, level)) return [HOLDER_LABELS["*"]];
  const held = roles.filter((role) => HOLDER_ROLES.includes(role));
  const plus = unionLetters([PACKAGES["+"]]);
  const plusGives =
    hasLetter(plus, key, level) ||
    (level === "view" && (hasLetter(plus, key, "change") || hasLetter(plus, key, "approve")));
  if (held.length > 0 && plusGives) return [HOLDER_LABELS["+"]];
  return held
    .filter((role) => hasLetter(ROLE_ACCESS[role] ?? {}, key, level))
    .map((role) => HOLDER_LABELS[role] ?? role);
}

function kvkkLocked(meta: SectionMeta, roles: readonly Role[]): boolean {
  return Boolean(meta.restrictedToRole) && !roles.includes(meta.restrictedToRole as Role);
}

/** Ayar hiçbir şeyi değiştirmiyor mu (rol zaten veriyor / rol zaten vermiyor; plan §5.2)? */
export function isRedundant(
  key: string,
  level: AccessLevel,
  effect: Effect,
  defaults: Readonly<Letters>,
): boolean {
  const meta = section(key);
  if (!meta || !meta.levels.includes(level)) return false;
  const given = hasLetter(defaults, key, level);
  if (effect === "grant") return given;
  // KVKK bölümündeki kaldırma kalır (rol yeniden verilirse geçerli olur).
  return !given && !meta.restrictedToRole;
}

/** Hücrenin durumu (plan §6.1 "Hücre durumları"). */
export function cellInfo(
  draft: Draft,
  saved: OverrideMap,
  key: string,
  level: AccessLevel,
  defaults: Readonly<Letters> = defaultLetters(draft.roles),
  preview: Readonly<Letters> = previewAccess(draft.roles, draft.overrides),
): CellInfo {
  const meta = section(key);
  const id = cellId(key, level);
  const override = draft.overrides.get(id);
  const dirty = override !== saved.get(id);
  const effective = hasLetter(preview, key, level);
  const sources = defaultSources(key, level, draft.roles);
  const base = { sources, effective, dirty };
  if (!meta || !meta.levels.includes(level)) return { ...base, state: "absent" };
  if (meta.adminOnly.includes(level)) return { ...base, state: "locked", lockReason: "admin_only" };
  const given = hasLetter(defaults, key, level);
  if (kvkkLocked(meta, draft.roles)) {
    if (override === "revoke") return { ...base, state: "revoked" };
    return { ...base, state: "locked", lockReason: "kvkk" };
  }
  if (meta.locked.includes(level) && given) {
    const everyone = hasLetter(ROLE_ACCESS[""], key, level);
    return { ...base, state: "locked", lockReason: everyone ? "everyone" : "any_role" };
  }
  let ineffective: Ineffective | undefined;
  if (override && isRedundant(key, level, override, defaults)) ineffective = "redundant";
  else if ((override === "grant" || (!override && given)) && !effective) {
    // Eklenen ya da rolden gelen düzey ön izlemede düştü: Görür kaldırıldı ya da ön koşul eksik.
    if (level !== "view" && meta.levels.includes("view") && !hasLetter(preview, key, "view"))
      ineffective = "dropped_view";
    else ineffective = "dropped_prereq";
  }
  if (override === "grant") return { ...base, state: "granted", ineffective };
  if (override === "revoke") return { ...base, state: "revoked", ineffective };
  return { ...base, state: given ? "role" : "none", ineffective };
}

/** Kişiye verilebilir mi (yalnız admin ya da KVKK kilidi yok)? */
function grantableFor(key: string, level: AccessLevel, roles: readonly Role[]): string | null {
  const meta = section(key);
  if (!meta || !meta.levels.includes(level)) return "absent";
  if (meta.adminOnly.includes(level)) return "admin_only";
  if (kvkkLocked(meta, roles)) return "kvkk";
  return null;
}

/** Kaydedilmemiş ekleme mi? Sunucu yalnız yeni satırları denetler (`_check_new_row`). */
function isNewGrant(id: string, effect: Effect, saved: OverrideMap): boolean {
  return effect === "grant" && saved.get(id) !== "grant";
}

interface DroppedGrant {
  id: string;
  /** Eksik ön koşul (`${bölüm}|${düzey}`); KVKK yüzünden kalkan eklemede yok. */
  need?: string;
}

/**
 * Sunucunun reddedeceği kaydedilmemiş eklemeleri taslaktan çıkarır (yerinde): rolü olmayan KVKK
 * bölümündeki eklemeler (`access_requires_role`) ve ön izlemede düşüp ön koşulu eksik kalanlar
 * (`access_requires`; birinin kalkması ötekini düşürebilir, sabit noktaya kadar). Kayıtlı satırlar
 * kalır: onları sunucu bitirir (`role_removed`) ya da uyararak düşürür (`dependent_dropped`).
 */
function dropRejectedGrants(
  roles: readonly Role[],
  overrides: Map<string, Effect>,
  saved: OverrideMap,
): DroppedGrant[] {
  const dropped: DroppedGrant[] = [];
  if (isAdminDraft(roles)) return dropped;
  for (const [id, effect] of [...overrides]) {
    const meta = section(parseCellId(id).key);
    if (isNewGrant(id, effect, saved) && meta && kvkkLocked(meta, roles)) {
      overrides.delete(id);
      dropped.push({ id });
    }
  }
  let changed = true;
  while (changed) {
    changed = false;
    const preview = previewAccess(roles, overrides);
    for (const [id, effect] of [...overrides]) {
      if (!isNewGrant(id, effect, saved)) continue;
      const { key, level } = parseCellId(id);
      const meta = section(key);
      if (!meta || !meta.levels.includes(level) || hasLetter(preview, key, level)) continue;
      const need = requirementsOf(meta, level).find((item) => {
        const { key: needKey, level: needLevel } = parseCellId(item);
        return !hasLetter(preview, needKey, needLevel);
      });
      if (!need) continue;
      overrides.delete(id);
      dropped.push({ id, need });
      changed = true;
    }
  }
  return dropped;
}

function droppedText(item: DroppedGrant, also: boolean): string {
  const { key, level } = parseCellId(item.id);
  const head = `${cellLabel(key, level)} eklemesi ${also ? "de " : ""}kaldırıldı`;
  if (!item.need) return `${head}: yalnız yönetim rolündekilere verilebilir (KVKK).`;
  const need = parseCellId(item.need);
  return `${head} (${needLabel(need.key, need.level)} gerekir).`;
}

/**
 * Taslağı sunucunun kabul edeceği hâle getirir (her değişiklikten sonra): reddedilecek kaydedilmemiş
 * eklemeler kalkar ve kendi satırlarının altında yazılır. Örnek: aynı taslakta eklenen KVKK yetkisi,
 * yönetim rolü kaldırılınca kalkar; kayıtlı KVKK eklemesi kalır ve kaydedince biter.
 */
export function settle(draft: Draft, saved: OverrideMap): ChangeResult {
  const overrides = new Map(draft.overrides);
  const dropped = dropRejectedGrants(draft.roles, overrides, saved);
  if (dropped.length === 0) return { draft, notes: [] };
  return {
    draft: { roles: draft.roles, overrides },
    notes: dropped.map((item) => ({
      key: parseCellId(item.id).key,
      text: droppedText(item, false),
    })),
  };
}

/** Düzeyin istenen durumu: açık, kapalı ya da rol varsayılanı. */
type Target = boolean | "default";

function setCell(
  overrides: Map<string, Effect>,
  key: string,
  level: AccessLevel,
  target: Target,
  defaults: Readonly<Letters>,
): boolean {
  const id = cellId(key, level);
  const given = hasLetter(defaults, key, level);
  if (target === "default") {
    overrides.delete(id);
    return given;
  }
  if (target) {
    if (given) overrides.delete(id);
    else overrides.set(id, "grant");
    return true;
  }
  if (given) overrides.set(id, "revoke");
  else overrides.delete(id);
  return false;
}

/**
 * Bir hücreyi istenen duruma getirir; bağlı düzeyleri ve ön koşulları uygular (plan §6.1 "Bağlı
 * yetkiler"). Ön koşul bu kişiye verilemiyorsa taslak değişmez ve hata notu döner. `saved` kayıtlı
 * ayarlardır: kapatılan düzeye bağlı kaydedilmemiş eklemeler kalkar, ötekiler yalnız yazılır.
 */
function applyCell(
  draft: Draft,
  key: string,
  level: AccessLevel,
  target: Target,
  saved: OverrideMap,
): ChangeResult {
  const meta = section(key);
  if (!meta) return { draft, notes: [] };
  const defaults = defaultLetters(draft.roles);
  const before = previewAccess(draft.roles, draft.overrides);
  const overrides = new Map(draft.overrides);
  const notes: Note[] = [];
  if (meta.kind === "open_records") {
    // Açık kayıtlar yalnız kapatılır (open_records_revoke_only).
    if (target === true || target === "default") overrides.delete(cellId(key, level));
    else overrides.set(cellId(key, level), "revoke");
    return { draft: { roles: draft.roles, overrides }, notes: [] };
  }
  const on = setCell(overrides, key, level, target, defaults);
  const queue: [string, AccessLevel][] = [[key, level]];
  if (on && level !== "view" && meta.levels.includes("view")) {
    // Değiştirir ya da Onaylar açılınca Görür de açılır.
    setCell(overrides, key, "view", true, defaults);
    queue.push([key, "view"]);
  }
  if (!on && level === "view") {
    // Görür kapanınca öteki düzeylerin eklemeleri de kalkar (kaldırma yazılmaz; Görür'ün kaldırılması
    // onları zaten düşürür).
    for (const other of ["change", "approve"] as const) {
      if (overrides.get(cellId(key, other)) === "grant") overrides.delete(cellId(key, other));
    }
  }
  if (on) {
    // Eksik ön koşul verilir ve satırın altında açıklanır.
    const seen = new Set<string>();
    while (queue.length > 0) {
      const [itemKey, itemLevel] = queue.shift()!;
      const itemMeta = section(itemKey);
      if (!itemMeta || seen.has(cellId(itemKey, itemLevel))) continue;
      seen.add(cellId(itemKey, itemLevel));
      for (const need of requirementsOf(itemMeta, itemLevel)) {
        const preview = previewAccess(draft.roles, overrides);
        const { key: needKey, level: needLevel } = parseCellId(need);
        if (hasLetter(preview, needKey, needLevel)) continue;
        const blocked = grantableFor(needKey, needLevel, draft.roles);
        if (blocked) {
          return {
            draft,
            notes: [
              {
                key,
                error: true,
                text: blockedText(
                  cellLabel(itemKey, itemLevel),
                  needLabel(needKey, needLevel),
                  blocked,
                ),
              },
            ],
          };
        }
        setCell(overrides, needKey, needLevel, true, defaults);
        notes.push({
          key,
          text: `${cellLabel(itemKey, itemLevel)} için ${needLabel(needKey, needLevel)} de verildi.`,
        });
        queue.push([needKey, needLevel]);
        const needMeta = section(needKey);
        if (needLevel !== "view" && needMeta?.levels.includes("view")) {
          setCell(overrides, needKey, "view", true, defaults);
          queue.push([needKey, "view"]);
        }
      }
    }
  } else {
    // Kapatılan düzeye bağlı kaydedilmemiş eklemeler kalkar (sunucu ön koşulu eksik yeni satırı
    // `access_requires` ile reddeder). Rolden ya da kayıtlı satırdan gelenler düşer; kendiliğinden
    // kaldırılmaz, yalnız yazılır (sunucu `dependent_dropped` ile uyarır).
    const dropped = dropRejectedGrants(draft.roles, overrides, saved);
    for (const item of dropped) notes.push({ key, text: droppedText(item, true) });
    const removed = new Set(dropped.map((item) => item.id));
    const after = previewAccess(draft.roles, overrides);
    for (const other of Object.keys(SECTIONS)) {
      if (other === key) continue;
      for (const otherLevel of GRANT_LEVELS) {
        if (removed.has(cellId(other, otherLevel))) continue;
        if (hasLetter(before, other, otherLevel) && !hasLetter(after, other, otherLevel)) {
          notes.push({
            key,
            text: `${cellLabel(other, otherLevel)} de düşer (${cellLabel(key, level)} gerekir).`,
          });
        }
      }
    }
  }
  return { draft: { roles: draft.roles, overrides }, notes };
}

function blockedText(cell: string, need: string, reason: string): string {
  const why =
    reason === "kvkk"
      ? "yalnız yönetim rolündekilere verilebilir (KVKK)"
      : reason === "admin_only"
        ? "yalnız sistem yöneticisindedir"
        : "bu bölümde yok";
  return `${cell} için ${need} gerekir; ${need} ${why}. Bu yetki verilemedi.`;
}

/** Hücre tıklanabilir mi (yok, yalnız admin, KVKK ya da kilitli değil)? */
export function isClickable(info: CellInfo): boolean {
  return info.state !== "absent" && info.state !== "locked";
}

/**
 * Tıklama (plan §6.1): ayarı olan hücre rol varsayılanına döner; olmayan tersine çevrilir. Açık
 * kayıtlar satırı yalnız kapatılır ya da yeniden açılır. `saved` kayıtlı ayarlardır (yoksa hepsi
 * kaydedilmemiş sayılır).
 */
export function toggle(
  draft: Draft,
  key: string,
  level: AccessLevel,
  saved: OverrideMap = new Map(),
): ChangeResult {
  const id = cellId(key, level);
  if (draft.overrides.has(id)) return applyCell(draft, key, level, "default", saved);
  const meta = section(key);
  if (meta?.kind === "open_records") return applyCell(draft, key, level, false, saved);
  const given = hasLetter(defaultLetters(draft.roles), key, level);
  return applyCell(draft, key, level, !given, saved);
}

function moduleKeys(moduleKey: string): string[] {
  return [...(MODULES.find((item) => item.key === moduleKey)?.sections ?? [])];
}

function withoutKeys(draft: Draft, keys: readonly string[]): Draft {
  const overrides = new Map(draft.overrides);
  for (const id of draft.overrides.keys()) {
    if (keys.includes(parseCellId(id).key)) overrides.delete(id);
  }
  return { roles: draft.roles, overrides };
}

/** "Rol varsayılanına dön": modüldeki bütün ayarlar (açık kayıtlar dahil) kalkar. */
export function resetModule(draft: Draft, moduleKey: string): Draft {
  return withoutKeys(draft, moduleKeys(moduleKey));
}

/** Kapatılabilen (kilitli, yalnız admin ya da KVKK kilidi olmayan) düzeyler. */
function editableLevels(
  meta: SectionMeta,
  roles: readonly Role[],
  defaults: Letters,
): GrantLevel[] {
  if (meta.kind === "open_records" || kvkkLocked(meta, roles)) return [];
  return GRANT_LEVELS.filter(
    (level) =>
      meta.levels.includes(level) &&
      !meta.adminOnly.includes(level) &&
      !(meta.locked.includes(level) && hasLetter(defaults, meta.key, level)),
  );
}

/**
 * "Yalnız görsün" (sahibin kararı, 2026-11-17): kişinin bir yetkisi olan bölümde Görür kalır,
 * Değiştirir ve Onaylar kapanır; yeni Görür açılmaz.
 */
export function viewOnlyModule(draft: Draft, moduleKey: string): Draft {
  const defaults = defaultLetters(draft.roles);
  const preview = previewAccess(draft.roles, draft.overrides);
  const overrides = new Map(draft.overrides);
  for (const key of moduleKeys(moduleKey)) {
    const meta = section(key)!;
    if (meta.kind === "open_records" || kvkkLocked(meta, draft.roles)) continue;
    const some = GRANT_LEVELS.some((level) => hasLetter(preview, key, level));
    if (!some) continue;
    // Görür, Değiştirir ya da Onaylar'dan geliyor olsa bile açık yazılır: onlar kapanınca düşmesin.
    if (meta.levels.includes("view")) setCell(overrides, key, "view", true, defaults);
    for (const level of editableLevels(meta, draft.roles, defaults)) {
      if (level === "view") continue;
      setCell(overrides, key, level, false, defaults);
    }
  }
  return { roles: draft.roles, overrides };
}

/**
 * "Modüldeki bütün yetkileri kaldır": Görür, Değiştirir ve Onaylar kapanır; Açık kayıtlar satırı
 * değişmez (plan §6.1). Görür kaldırılabiliyorsa yalnız Görür'ün kaldırması yazılır.
 */
export function removeAllInModule(draft: Draft, moduleKey: string): Draft {
  const defaults = defaultLetters(draft.roles);
  const overrides = new Map(draft.overrides);
  for (const key of moduleKeys(moduleKey)) {
    const meta = section(key)!;
    const levels = editableLevels(meta, draft.roles, defaults);
    if (levels.length === 0) continue;
    if (levels.includes("view")) {
      for (const other of ["change", "approve"] as const) overrides.delete(cellId(key, other));
      setCell(overrides, key, "view", false, defaults);
      continue;
    }
    for (const level of levels) setCell(overrides, key, level, false, defaults);
  }
  return { roles: draft.roles, overrides };
}

/** Modül başlığındaki üç durumlu kutu: sütundaki uygulanabilir hücreler. */
export function columnCells(draft: Draft, moduleKey: string, level: GrantLevel): string[] {
  const defaults = defaultLetters(draft.roles);
  return moduleKeys(moduleKey).filter((key) => {
    const meta = section(key)!;
    if (!meta.levels.includes(level) || meta.kind === "open_records") return false;
    if (meta.adminOnly.includes(level) || kvkkLocked(meta, draft.roles)) return false;
    return !(meta.locked.includes(level) && hasLetter(defaults, key, level));
  });
}

export function columnState(
  draft: Draft,
  moduleKey: string,
  level: GrantLevel,
  preview: Readonly<Letters> = previewAccess(draft.roles, draft.overrides),
): "all" | "some" | "none" | "empty" {
  const keys = columnCells(draft, moduleKey, level);
  if (keys.length === 0) return "empty";
  const on = keys.filter((key) => hasLetter(preview, key, level)).length;
  return on === keys.length ? "all" : on === 0 ? "none" : "some";
}

/** Sütunu açar ya da kapatır (bağlı düzeyler ve ön koşullarla); verilemeyen hücre atlanır. */
export function setColumn(
  draft: Draft,
  moduleKey: string,
  level: GrantLevel,
  on: boolean,
  saved: OverrideMap = new Map(),
): ChangeResult {
  let current = draft;
  const notes: Note[] = [];
  for (const key of columnCells(draft, moduleKey, level)) {
    const preview = previewAccess(current.roles, current.overrides);
    if (hasLetter(preview, key, level) === on) continue;
    const result = applyCell(current, key, level, on, saved);
    notes.push(...result.notes);
    if (!result.notes.some((note) => note.error)) current = result.draft;
  }
  return { draft: current, notes };
}

/** "Tümünü rol varsayılanına döndür": bütün ayarlar kalkar, roller değişmez. */
export function resetAll(draft: Draft): Draft {
  return { roles: draft.roles, overrides: new Map() };
}

/**
 * "Etkisiz ayarları temizle": sunucunun etkisiz dediği kayıtlı ayarlar ve rol varsayılanıyla aynı
 * olan taslak ayarlar kalkar. KVKK ya da eksik ön koşul yüzünden geçersiz eklemeler kalır
 * (sahibin kararı, 2026-11-17). Sunucunun işareti kayıtlı rollere göredir; taslakta roller
 * değiştiyse yalnız taslağın rol varsayılanı (`isRedundant`) sayılır.
 */
export function cleanIneffective(
  draft: Draft,
  savedIneffective: ReadonlySet<string>,
  savedRoles: readonly Role[],
): Draft {
  const defaults = defaultLetters(draft.roles);
  const sameRoles =
    savedRoles.length === draft.roles.length &&
    savedRoles.every((role) => draft.roles.includes(role));
  const overrides = new Map(draft.overrides);
  for (const [id, effect] of draft.overrides) {
    const { key, level } = parseCellId(id);
    const flagged = sameRoles && savedIneffective.has(`${id}|${effect}`);
    if (flagged || isRedundant(key, level, effect, defaults)) overrides.delete(id);
  }
  return { roles: draft.roles, overrides };
}

export function ineffectiveCount(
  draft: Draft,
  savedIneffective: ReadonlySet<string>,
  savedRoles: readonly Role[],
): number {
  return (
    draft.overrides.size - cleanIneffective(draft, savedIneffective, savedRoles).overrides.size
  );
}

export interface DraftDiff {
  rolesAdded: Role[];
  rolesRemoved: Role[];
  /** Taslakta kayıtlıdan farklı olan hücreler. */
  changed: string[];
  count: number;
}

export function diff(base: Draft, draft: Draft): DraftDiff {
  const rolesAdded = draft.roles.filter((role) => !base.roles.includes(role));
  const rolesRemoved = base.roles.filter((role) => !draft.roles.includes(role));
  const ids = new Set([...base.overrides.keys(), ...draft.overrides.keys()]);
  const changed = [...ids].filter((id) => base.overrides.get(id) !== draft.overrides.get(id));
  return {
    rolesAdded,
    rolesRemoved,
    changed,
    count: rolesAdded.length + rolesRemoved.length + changed.length,
  };
}

export function overridesFrom(rows: readonly OverrideSpec[]): Map<string, Effect> {
  return new Map(rows.map((row) => [cellId(row.key, row.level), row.effect]));
}

/** Kaydetme gövdesi: istenen etkin ayarların tamamı (sıralı). */
export function toOverrides(overrides: OverrideMap): OverrideSpec[] {
  return [...overrides.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([id, effect]) => ({ ...parseCellId(id), effect }));
}

/**
 * Okunmaya devam eden kayıtlar (plan §6.1): bölümün Görür'ü yoksa, aynı kayıt türünü okuyan öteki
 * bölümlerden Görür'ü olanlar ("Emirleri Malzeme hazırlama üzerinden görmeye devam eder.").
 */
export function readThroughNotes(
  preview: Readonly<Letters>,
  key: string,
  nouns: Readonly<Record<string, string>>,
): string[] {
  const meta = section(key);
  if (!meta || !meta.levels.includes("view") || hasLetter(preview, key, "view")) return [];
  const notes: string[] = [];
  for (const [model, keys] of Object.entries(READERS)) {
    if (!(keys as readonly string[]).includes(key)) continue;
    const others = keys.filter((other) => other !== key && hasLetter(preview, other, "view"));
    if (others.length === 0) continue;
    const labels = others.map((other) => section(other)!.label);
    notes.push(`${nouns[model] ?? model} ${joinTr(labels)} üzerinden görmeye devam eder.`);
  }
  return notes;
}

/** "A, B ve C" */
export function joinTr(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} ve ${items[items.length - 1]}`;
}

/** Açık kayıtlar kapalıysa okumaya devam edilen bölümler (plan §5.3, §6.1). */
export function openRecordsReaders(preview: Readonly<Letters>, moduleKey: string): string[] {
  return moduleKeys(moduleKey)
    .filter((key) => SECTIONS[key as keyof typeof SECTIONS].kind !== "open_records")
    .filter((key) => hasLetter(preview, key, "view"))
    .map((key) => section(key)!.label);
}

export { openRecordsKey };
