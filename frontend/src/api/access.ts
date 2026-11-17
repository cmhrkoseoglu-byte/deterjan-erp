// Kişiye özel yetkiler (docs/plan/kisi-yetkileri.md §5.10, §6): kişinin Yetkiler ekranı (yalnız
// admin), Geçmiş, "Kimde var?" raporu, Excel ve herkesin Yetkilerim sayfası. Alan adları backend'le
// aynıdır (9. adımın arayüz sözleşmesi).
import type { AccessLevel } from "../auth/access.gen";
import { api } from "./client";
import type { Paginated, Role } from "./types";

export type Effect = "grant" | "revoke";
/** Kişiye özel ayarın bitiş nedeni. */
export type EndReason = "reset" | "replaced" | "ineffective" | "role_removed" | "admin" | "retired";
/** Kişiye özel ayar: bölüm, düzey, ekleme ya da kaldırma. */
export interface OverrideSpec {
  key: string;
  level: AccessLevel;
  effect: Effect;
}
/** Hücre: bölüm ve düzey. */
export interface Cell {
  key: string;
  level: AccessLevel;
}
/** `me.access` biçiminde yetki harfleri, ör. `{"production.prep": "rvc"}`. */
export type Letters = Record<string, string>;

/** Etkin kişiye özel ayar (Yetkiler ekranı). Not ve değiştiren yalnız admine döner. */
export interface SavedOverride extends OverrideSpec {
  id: number;
  note: string;
  created_at: string;
  created_by_name: string | null;
  /** `false`: bölüm ya da düzey katalogdan kaldırılmış; kaydedince "katalogdan kaldırıldı" diye biter. */
  known: boolean;
  /** Etkisiz: rol zaten veriyor ya da rol zaten vermiyor (plan §5.2). */
  ineffective: boolean;
}

/** `GET /users/{id}/access/`: kişinin rolleri, rol varsayılanı, geçerli yetkisi ve ayarları. */
export interface UserAccess {
  user: {
    id: number;
    username: string;
    full_name: string;
    is_active: boolean;
    is_superuser: boolean;
    otp_enabled: boolean;
  };
  roles: Role[];
  is_admin: boolean;
  is_self: boolean;
  /** Eşzamanlı değişiklik denetimi: kaydederken geri gönderilir (`access_changed`). */
  version: string;
  catalog_hash: string;
  /** Yalnız rollerle (kişi etkinmiş gibi). */
  default: Letters;
  /** Kişiye özel ayarlarla (kişi etkinmiş gibi). */
  effective: Letters;
  overrides: SavedOverride[];
  /** Modül → "Açık kayıtlar" kapatılınca etkilenebilecek öteki ekranlar. */
  open_records_effects: Record<string, string[]>;
}

/** `PUT /users/{id}/access/` gövdesi: `overrides` istenen etkin ayarların tamamıdır. */
export interface AccessSaveInput {
  version: string;
  dry_run?: boolean;
  note?: string;
  /** Verilmezse roller değişmez. */
  roles?: Role[];
  overrides: OverrideSpec[];
}

export type AccessWarningCode =
  | "coverage_gap"
  | "task_not_routed"
  | "no_role_no_tasks"
  | "segregation"
  | "kvkk_role_removed"
  | "admin_granted"
  | "user_inactive"
  | "sensitive_without_otp"
  | "open_records_closed"
  | "dependent_dropped"
  | "override_ineffective";

export interface AccessWarning {
  code: AccessWarningCode;
  text: string;
}

/** Ön izleme (`dry_run`) ve kayıt yanıtı. */
export interface AccessSaveResult {
  dry_run: boolean;
  changed: boolean;
  saved: boolean;
  roles: { before: Role[]; after: Role[] };
  overrides: {
    created: OverrideSpec[];
    ended: (OverrideSpec & { id: number; reason: EndReason })[];
  };
  access: { before: Letters; after: Letters; granted: Cell[]; removed: Cell[] };
  warnings: AccessWarning[];
  /** Kaydedilince ekranın yeni hâli (yeni `version` ile); ön izlemede `null`. */
  matrix: UserAccess | null;
}

/** Geçmiş satırı: eklenen, kaldırılan ya da biten ayar. */
export interface AccessHistoryLine {
  kind: "granted" | "revoked" | "ended";
  key: string;
  level: AccessLevel;
  effect?: Effect;
  reason?: EndReason;
  reason_label?: string;
}

/** `GET /users/{id}/access/history/`: rol ve kişiye özel yetki değişiklikleri, yeniden eskiye. */
export interface AccessHistoryEntry {
  id: number;
  timestamp: string;
  actor_name: string | null;
  note: string;
  roles: { before: Role[]; after: Role[] } | null;
  lines: AccessHistoryLine[];
}

export type MySource = "everyone" | "any_role" | "role" | "granted";

/** `GET /auth/me/access/` (Yetkilerim): not, değiştiren ve tarih dönmez. */
export interface MyAccess {
  roles: Role[];
  is_admin: boolean;
  entries: {
    key: string;
    level: AccessLevel;
    source: MySource;
    roles: Role[];
    /** Görür yalnız Değiştirir ya da Onaylar yüzünden var. */
    implied: boolean;
  }[];
  /** Rolden gelip kişiden kaldırılanlar; kapatılan açık kayıtlar `level: "read"`. */
  revoked: { key: string; level: AccessLevel; roles: Role[] }[];
}

export type HolderSource =
  "everyone" | "any_role" | "role" | "granted" | "implied" | "admin" | "revoked";

/** "Kimde var?": yetkiyi etkin olarak taşıyanlar (ve rolde olup kaldırılanlar). */
export interface AccessHolder {
  user: { id: number; username: string; full_name: string; roles: Role[] };
  source: HolderSource;
  roles: Role[];
  /** Görev ayrılığı uyarıları (plan §5.11). */
  segregation: string[];
}

export interface AccessHolders {
  key: string;
  level: AccessLevel;
  holders: AccessHolder[];
}

export const HISTORY_PAGE_SIZE = 50;

export async function fetchUserAccess(id: number): Promise<UserAccess> {
  const { data } = await api.get<UserAccess>(`/users/${id}/access/`);
  return data;
}

/**
 * Ön izleme (`dry_run: true`) ya da kayıt. Hata kodları: access_changed, cannot_edit_own_access,
 * admin_has_all_access, unknown_role, role_not_seeded, cannot_remove_own_admin, last_admin,
 * access_duplicate, unknown_access, open_records_revoke_only, access_not_grantable,
 * access_locked, access_requires_role, access_conflict, access_requires, access_note_required.
 */
export async function saveUserAccess(
  id: number,
  input: AccessSaveInput,
): Promise<AccessSaveResult> {
  const { data } = await api.put<AccessSaveResult>(`/users/${id}/access/`, input);
  return data;
}

export async function fetchUserAccessHistory(
  id: number,
  page = 1,
): Promise<Paginated<AccessHistoryEntry>> {
  const { data } = await api.get<Paginated<AccessHistoryEntry>>(`/users/${id}/access/history/`, {
    params: { page: page > 1 ? page : undefined },
  });
  return data;
}

export async function fetchMyAccess(): Promise<MyAccess> {
  const { data } = await api.get<MyAccess>("/auth/me/access/");
  return data;
}

export async function fetchAccessHolders(key: string, level: string): Promise<AccessHolders> {
  const { data } = await api.get<AccessHolders>("/access/report/holders/", {
    params: { key, level },
  });
  return data;
}

/** Paketler ve kişilerin geçerli yetkileri (Excel, kontrollü belge). */
export const ACCESS_REPORT_EXPORT_URL = "/api/v1/access/report/export/";
