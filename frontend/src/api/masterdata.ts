// /api/v1/masterdata/* uç noktaları. Ondalıklar metin olarak gelir ("12.5000").
import { api } from "./client";
import type { Paginated } from "./types";

export interface Audited {
  id: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type UnitKind = "MASS" | "VOLUME" | "COUNT";

export interface Unit extends Audited {
  code: string;
  name: string;
  kind: UnitKind;
  kind_display: string;
  factor_to_kind_base: string | null;
}

export interface Category extends Audited {
  code: string;
  name: string;
}

export type MaterialType = "RAW" | "PACKAGING" | "BULK" | "FINISHED";

export interface Conversion extends Audited {
  material: number;
  material_code: string;
  unit: number;
  unit_code: string;
  factor_to_base: string;
  base_unit_code: string;
}

export interface Material extends Audited {
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
  requires_incoming_qc: boolean;
  is_hazardous: boolean;
  storage_notes: string;
  conversions?: Conversion[];
}

export interface Warehouse extends Audited {
  code: string;
  name: string;
}

export type LocationType = "STORAGE" | "QUARANTINE" | "PRODUCTION" | "SHIPPING" | "TANK";

export interface Location extends Audited {
  warehouse: number;
  warehouse_code: string;
  code: string;
  name: string;
  location_type: LocationType;
  location_type_display: string;
}

export type EquipmentType = "MIXING_TANK" | "STORAGE_TANK" | "FILLING_LINE" | "SCALE" | "OTHER";

export interface Equipment extends Audited {
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

export interface Partner extends Audited {
  code: string;
  name: string;
  tax_office: string;
  tax_number: string;
  address: string;
  phone: string;
  email: string;
  contact_person: string;
}

/** Ana veri uç noktaları (`/masterdata/<endpoint>/`). */
export type MasterDataEndpoint =
  | "units"
  | "categories"
  | "materials"
  | "conversions"
  | "warehouses"
  | "locations"
  | "equipment"
  | "suppliers"
  | "customers";

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
  const { data } = await api.get<Paginated<T>>(`/masterdata/${endpoint}/`, {
    params: clean(params),
  });
  return data;
}

export async function getRecord<T>(endpoint: MasterDataEndpoint, id: number): Promise<T> {
  const { data } = await api.get<T>(`/masterdata/${endpoint}/${id}/`);
  return data;
}

export async function saveRecord<T>(
  endpoint: MasterDataEndpoint,
  id: number | null,
  payload: Record<string, unknown>,
): Promise<T> {
  const { data } = id
    ? await api.patch<T>(`/masterdata/${endpoint}/${id}/`, payload)
    : await api.post<T>(`/masterdata/${endpoint}/`, payload);
  return data;
}

export async function setRecordActive<T>(
  endpoint: MasterDataEndpoint,
  id: number,
  active: boolean,
): Promise<T> {
  const { data } = await api.post<T>(
    `/masterdata/${endpoint}/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

// --- içe aktarma --------------------------------------------------------------------------

export type ImportKind = "materials" | "suppliers" | "customers";

export interface ImportRow {
  row: number;
  code: string;
  action: "create" | "update";
  errors: { column: string; message: string }[];
}

export interface ImportReport {
  kind: ImportKind;
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
