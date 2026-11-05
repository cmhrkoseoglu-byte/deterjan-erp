// /api/v1/masterdata/* uç noktaları. Ondalıklar metin olarak gelir ("12.5000").
import { api } from "./client";
import type { Paginated } from "./types";

export interface Audited {
  id: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** Kodlu ana veri: kodu değişmiş kayıtta eski kodlar, en yeniden eskiye (kodlama sistematiği). */
export interface FormerCodes {
  former_codes?: string[];
}

export type UnitKind = "MASS" | "VOLUME" | "COUNT";

export interface Unit extends Audited {
  code: string;
  name: string;
  kind: UnitKind;
  kind_display: string;
  factor_to_kind_base: string | null;
  /** UN/ECE Rec 20 ortak kodu (KGM, LTR, C62; koli XCT, palet XPX). */
  unece_code: string;
  /** kg, g, L, mL; adet birimlerinde boş. */
  symbol: string;
}

export interface Category extends Audited, FormerCodes {
  code: string;
  name: string;
}

export type MaterialType = "RAW" | "PACKAGING" | "BULK" | "FINISHED";

/**
 * Eski koli GTIN'i: lotu olan mamulde koli içi miktar değişince eski GTIN eski miktarıyla
 * arşivlenir ve bir daha hiçbir ürüne ya da koliye verilmez (CUMHUR, 2026-11-05).
 */
export interface RetiredGtin {
  /** 14 haneli eski koli GTIN'i. */
  gtin: string;
  /** Bu GTIN geçerliyken 1 koli kaç temel birimdi ("12.000000"). */
  factor_to_base: string;
  /** Yerine gelen koli GTIN'i (14 hane). */
  replaced_by: string;
  /** Arşivlendiği an: koli içi miktarın değiştiği kayıt. */
  retired_at: string;
  retired_by_name: string;
}

/**
 * Birim dönüşümü. Kayıt hataları (400, `code`): `invalid_gtin`, `gtin_taken` (arşivdeki eski koli
 * GTIN'i dahil), `gtin_locked`, `case_gtin_not_allowed`, `case_gtin_required` (lotu olan mamulde
 * koli içi miktar yeni koli GTIN'i olmadan değişmez).
 */
export interface Conversion extends Audited {
  material: number;
  material_code: string;
  unit: number;
  unit_code: string;
  factor_to_base: string;
  base_unit_code: string;
  /** Koli GTIN'i: yalnızca birimi KOLI olan dönüşümde (koli dışı birimde dolu GTIN reddedilir). */
  gtin: string;
  /**
   * Malzeme mamul, lotu var ve koli GTIN'i geçerli: koli GTIN'i tek başına değiştirilemez ya da
   * silinemez; koli içi miktar (`factor_to_base`) değişirse yeni koli GTIN'iyle birlikte değişir.
   */
  gtin_locked: boolean;
  /** Eski koli GTIN'leri, en yeniden eskiye. */
  retired_gtins: RetiredGtin[];
}

/** Koli birimi kodu: koli GTIN'i yalnızca bu birimin dönüşümünde tutulur. */
export const CASE_UNIT = "KOLI";

export interface Material extends Audited, FormerCodes {
  code: string;
  name: string;
  material_type: MaterialType;
  material_type_display: string;
  category: number | null;
  category_name: string | null;
  base_unit: number;
  base_unit_code: string;
  density: string | null;
  shelf_life_days: number | null;
  min_stock: string | null;
  gtin: string;
  /**
   * Malzeme mamul, lotu var ve GTIN'i geçerli: GTIN değiştirilemez ve silinemez. Hammadde, ambalaj
   * ve yarı mamulde lot olsa da false (tedarikçi GTIN'i düzeltilebilir).
   */
  gtin_locked: boolean;
  requires_incoming_qc: boolean;
  is_hazardous: boolean;
  storage_notes: string;
  conversions?: Conversion[];
}

export interface Warehouse extends Audited, FormerCodes {
  code: string;
  name: string;
}

export type LocationType = "STORAGE" | "QUARANTINE" | "PRODUCTION" | "SHIPPING" | "TANK";

export interface Location extends Audited, FormerCodes {
  warehouse: number;
  warehouse_code: string;
  code: string;
  name: string;
  location_type: LocationType;
  location_type_display: string;
}

export type EquipmentType = "MIXING_TANK" | "STORAGE_TANK" | "FILLING_LINE" | "SCALE" | "OTHER";

export interface Equipment extends Audited, FormerCodes {
  code: string;
  name: string;
  equipment_type: EquipmentType;
  equipment_type_display: string;
  capacity: string | null;
  capacity_unit: number | null;
  capacity_unit_code: string | null;
  location: number | null;
  location_code: string | null;
}

export interface Partner extends Audited, FormerCodes {
  code: string;
  name: string;
  tax_office: string;
  tax_number: string;
  address: string;
  phone: string;
  email: string;
  contact_person: string;
  /** ISO 3166-1 alpha-2 (TR, DE, IQ …). */
  country_code: string;
}

/**
 * Ana veri uç noktaları (`/masterdata/<endpoint>/`). Başka modülün ana veri benzeri listesi
 * (aktif/pasif, kod + ad) modül önekiyle yazılır, ör. `quality/tests` → `/quality/tests/`.
 */
export type MasterDataEndpoint =
  | "units"
  | "categories"
  | "materials"
  | "conversions"
  | "warehouses"
  | "locations"
  | "equipment"
  | "suppliers"
  | "customers"
  | "printers"
  | "quality/tests";

function basePath(endpoint: MasterDataEndpoint): string {
  return endpoint.includes("/") ? `/${endpoint}` : `/masterdata/${endpoint}`;
}

export type ListParams = Record<string, string | number | boolean | undefined>;

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

export async function listRecords<T>(
  endpoint: MasterDataEndpoint,
  params: ListParams = {},
): Promise<Paginated<T>> {
  const { data } = await api.get<Paginated<T>>(`${basePath(endpoint)}/`, {
    params: clean(params),
  });
  return data;
}

export async function getRecord<T>(endpoint: MasterDataEndpoint, id: number): Promise<T> {
  const { data } = await api.get<T>(`${basePath(endpoint)}/${id}/`);
  return data;
}

export async function saveRecord<T>(
  endpoint: MasterDataEndpoint,
  id: number | null,
  payload: Record<string, unknown>,
): Promise<T> {
  const { data } = id
    ? await api.patch<T>(`${basePath(endpoint)}/${id}/`, payload)
    : await api.post<T>(`${basePath(endpoint)}/`, payload);
  return data;
}

export async function setRecordActive<T>(
  endpoint: MasterDataEndpoint,
  id: number,
  active: boolean,
): Promise<T> {
  const { data } = await api.post<T>(
    `${basePath(endpoint)}/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

// --- GTIN önerisi (GS1) -------------------------------------------------------------------

/**
 * Sıradaki boş GTIN-13 (ön yüz yalnızca mamulde kullanır). `active` yalnızca GS1 firma öneki ve
 * sıradaki ürün referansı girilmişse true; `reason` Türkçe açıklamadır (kapalıysa nedeni).
 */
export interface GtinSuggestion {
  active: boolean;
  gtin: string | null;
  reason: string;
}

/** Malzemenin GTIN'inden türetilen ilk boş koli GTIN'i (GTIN-14); türetilemezse `reason`. */
export interface CaseGtinSuggestion {
  gtin: string | null;
  reason: string;
}

/** Malzeme yazma rolleri (planlama, admin). */
export async function suggestGtin(): Promise<GtinSuggestion> {
  const { data } = await api.get<GtinSuggestion>("/masterdata/gtin-suggestion/");
  return data;
}

/**
 * GTIN önerisinin sorgu anahtarı. Malzeme listesinin anahtarı altındadır: malzeme kaydedilince
 * (yeni ya da düzenleme; ana veri ekranı `["masterdata", "materials"]`i yeniler) öneri de
 * geçersizlenir, kaydedilen GTIN yeniden önerilmez.
 */
export const gtinSuggestionKey = ["masterdata", "materials", "gtin-suggestion"] as const;

/** Malzeme yazma rolleri (planlama, admin). */
export async function suggestCaseGtin(materialId: number): Promise<CaseGtinSuggestion> {
  const { data } = await api.get<CaseGtinSuggestion>(
    `/masterdata/materials/${materialId}/case-gtin-suggestion/`,
  );
  return data;
}

// --- içe aktarma --------------------------------------------------------------------------

export type ImportKind =
  | "materials"
  | "suppliers"
  | "customers"
  | "warehouses"
  | "locations"
  | "equipment"
  | "conversions";

export interface ImportRow {
  row: number;
  code: string;
  action: "create" | "update";
  errors: { column: string; message: string }[];
}

export interface ImportReport {
  kind: ImportKind | "opening" | "recipes" | "stock_comparison";
  total: number;
  valid: number;
  invalid: number;
  to_create: number;
  to_update: number;
  file_errors: string[];
  rows: ImportRow[];
  imported: boolean;
}

/** Dosyayı gönderir: `confirm=false` önizleme, `true` aktarım. Hatalıysa 400 ve gövdede `report`. */
export async function uploadImport(
  kind: ImportKind,
  file: File,
  confirm: boolean,
): Promise<ImportReport> {
  const body = new FormData();
  body.append("file", file);
  body.append("confirm", confirm ? "true" : "false");
  const { data } = await api.post<ImportReport>(`/masterdata/import/${kind}/`, body);
  return data;
}

export function importTemplateUrl(kind: ImportKind): string {
  return `/api/v1/masterdata/import/templates/${kind}/`;
}

/** Firmanın ticari bilgileri (tek kayıt): irsaliyede satıcı, satın alma siparişinde alıcı. */
export interface CompanyProfile {
  legal_name: string;
  address: string;
  tax_office: string;
  /** 10 haneli VKN; şahıs firmasında 11 haneli TCKN. */
  tax_number: string;
  trade_registry_no: string;
  mersis_no: string;
  updated_at: string;
}

export type CompanyProfileInput = Omit<CompanyProfile, "updated_at">;

export async function getCompanyProfile(): Promise<CompanyProfile> {
  const { data } = await api.get<CompanyProfile>("/masterdata/company/");
  return data;
}

/** Yönetim ve admin. Hata kodları: legal_name_required, invalid_tax_number, invalid_mersis_no. */
export async function saveCompanyProfile(input: CompanyProfileInput): Promise<CompanyProfile> {
  const { data } = await api.put<CompanyProfile>("/masterdata/company/", input);
  return data;
}
