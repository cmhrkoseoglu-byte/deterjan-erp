// /api/v1/hse/* uç noktaları (Faz 4, Adım 4.5): tehlike / önlem ifadeleri, malzeme tehlike bilgisi,
// GBF arşivi ve eksik GBF raporu, depolama limitleri ve doluluk, atık firmaları ve atık kayıtları
// (`AT-`), olay / kaza kayıtları (`OL-`), özet ve ayarlar. Miktarlar metin olarak gelir (kg).
import { api } from "./client";
import type { ListParams } from "./masterdata";
import type { Paginated } from "./types";

export type HazardClass =
  "GHS01" | "GHS02" | "GHS03" | "GHS04" | "GHS05" | "GHS06" | "GHS07" | "GHS08" | "GHS09";
export type SignalWord = "DANGER" | "WARNING";
export type StatementKind = "H" | "P" | "EUH";
export type SdsState = "OK" | "MISSING" | "NO_FILE" | "EXPIRED" | "OUTDATED";
export type IncidentStatus = "OPEN" | "INVESTIGATING" | "CLOSED" | "CANCELLED";
export type IncidentType = "WORK_ACCIDENT" | "NEAR_MISS" | "ENVIRONMENTAL" | "FIRE" | "OTHER";
export type Severity = "LOW" | "MEDIUM" | "HIGH";
export type WasteStatus = "RECORDED" | "CANCELLED";

export interface HazardStatement {
  id: number;
  code: string;
  kind: StatementKind;
  kind_display: string;
  text: string;
  is_active: boolean;
}

export interface StatementBrief {
  id: number;
  code: string;
  kind: StatementKind;
  text: string;
}

export interface MaterialHazard {
  /** Tehlike bilgisi girilmemiş malzemede null (boş profil). */
  id: number | null;
  material: number;
  material_code: string;
  material_name: string;
  is_hazardous: boolean;
  pictograms: HazardClass[];
  pictogram_labels: string[];
  signal_word: SignalWord | "";
  signal_word_display: string;
  statements: number[];
  statement_rows: StatementBrief[];
  note: string;
}

export interface MaterialHazardPayload {
  pictograms: HazardClass[];
  signal_word: SignalWord | "";
  statements: number[];
  note: string;
}

export interface SafetyDataSheet {
  id: number;
  material: number;
  material_code: string;
  material_name: string;
  supplier: number | null;
  supplier_name: string | null;
  revision_no: string;
  revision_date: string;
  valid_until: string | null;
  language: string;
  note: string;
  superseded_at: string | null;
  is_current: boolean;
  file_count: number;
  created_at: string;
  created_by_name: string | null;
}

export interface SdsPayload {
  material: number;
  supplier: number | null;
  revision_no: string;
  revision_date: string;
  valid_until: string | null;
  language: string;
  note: string;
}

export interface SdsGap {
  material_id: number;
  material_code: string;
  material_name: string;
  material_type: string;
  material_type_display: string;
  is_hazardous: boolean;
  status: SdsState;
  status_display: string;
  sds_id: number | null;
  revision_no: string;
  revision_date: string | null;
  valid_until: string | null;
  has_file: boolean;
}

export interface StorageLimit {
  id: number;
  location: number;
  location_code: string;
  location_name: string;
  hazard_class: HazardClass;
  hazard_class_display: string;
  max_kg: string;
  note: string;
  is_active: boolean;
}

export interface StorageLimitPayload {
  location: number;
  hazard_class: HazardClass;
  max_kg: string;
  note: string;
}

export interface StorageUtilisation {
  limit_id: number;
  location_id: number;
  location_code: string;
  location_name: string;
  hazard_class: HazardClass;
  hazard_class_display: string;
  limit_kg: string;
  quantity_kg: string;
  pct: string;
  exceeded: boolean;
}

export interface WasteContractor {
  id: number;
  name: string;
  license_no: string;
  license_valid_until: string;
  license_expired: boolean;
  phone: string;
  note: string;
  is_active: boolean;
}

export interface WasteContractorPayload {
  name: string;
  license_no: string;
  license_valid_until: string;
  phone: string;
  note: string;
}

export interface WasteRecord {
  id: number;
  number: string;
  status: WasteStatus;
  status_display: string;
  waste_code: string;
  description: string;
  is_hazardous: boolean;
  quantity_kg: string;
  contractor: number;
  contractor_name: string;
  contractor_license_no: string;
  delivered_on: string;
  document_no: string;
  note: string;
  cancel_reason: string;
  created_at: string;
  created_by_name: string | null;
}

export interface WasteRecordPayload {
  waste_code: string;
  description: string;
  is_hazardous: boolean;
  quantity_kg: string;
  contractor: number;
  delivered_on: string;
  document_no: string;
  note: string;
}

export interface Incident {
  id: number;
  number: string;
  status: IncidentStatus;
  status_display: string;
  incident_type: IncidentType;
  incident_type_display: string;
  occurred_at: string;
  place: string;
  location: number | null;
  location_code: string | null;
  equipment: number | null;
  equipment_code: string | null;
  description: string;
  injury: boolean;
  injured_person: string;
  severity: Severity;
  severity_display: string;
  root_cause: string;
  corrective_action: string;
  action_owner: string;
  action_due: string | null;
  closed_note: string;
  cancel_reason: string;
  created_at: string;
  created_by_name: string | null;
  allowed_transitions: IncidentStatus[];
}

export interface IncidentPayload {
  incident_type: IncidentType;
  occurred_at: string;
  place: string;
  location: number | null;
  equipment: number | null;
  description: string;
  injury: boolean;
  injured_person: string;
  severity: Severity;
}

export interface InvestigationPayload {
  severity?: Severity;
  root_cause?: string;
  corrective_action?: string;
  action_owner?: string;
  action_due?: string | null;
}

export interface ClosePayload extends InvestigationPayload {
  closed_note?: string;
}

export interface CountRow {
  code: string;
  label: string;
  count: number;
}

export interface WasteSummaryRow {
  waste_code: string;
  description: string;
  is_hazardous: boolean;
  count: number;
  quantity_kg: string;
}

export interface HseSummary {
  date_from: string;
  date_to: string;
  incidents: {
    total: number;
    injury_count: number;
    open_count: number;
    by_type: CountRow[];
    by_severity: CountRow[];
  };
  waste: WasteSummaryRow[];
}

export interface HseSettings {
  sds_max_age_months: number;
}

const BASE = "/hse";
const STATEMENTS = `${BASE}/hazard-statements`;
const SDS = `${BASE}/sds`;
const LIMITS = `${BASE}/storage-limits`;
const CONTRACTORS = `${BASE}/waste-contractors`;
const WASTE = `${BASE}/waste-records`;
const INCIDENTS = `${BASE}/incidents`;

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

async function list<T>(path: string, params: ListParams): Promise<Paginated<T>> {
  const { data } = await api.get<Paginated<T>>(`${path}/`, { params: clean(params) });
  return data;
}

async function toggle<T>(path: string, id: number, active: boolean): Promise<T> {
  const { data } = await api.post<T>(`${path}/${id}/${active ? "activate" : "deactivate"}/`);
  return data;
}

// --- tehlike ifadeleri ---

export const listStatements = (params: ListParams = {}) =>
  list<HazardStatement>(STATEMENTS, params);

export async function createStatement(payload: {
  code: string;
  kind: StatementKind;
  text: string;
}): Promise<HazardStatement> {
  const { data } = await api.post<HazardStatement>(`${STATEMENTS}/`, payload);
  return data;
}

export async function updateStatement(id: number, text: string): Promise<HazardStatement> {
  const { data } = await api.patch<HazardStatement>(`${STATEMENTS}/${id}/`, { text });
  return data;
}

export const setStatementActive = (id: number, active: boolean) =>
  toggle<HazardStatement>(STATEMENTS, id, active);

// --- malzeme tehlike bilgisi ---

export async function getMaterialHazard(materialId: number): Promise<MaterialHazard> {
  const { data } = await api.get<MaterialHazard>(`${BASE}/materials/${materialId}/hazard/`);
  return data;
}

export async function saveMaterialHazard(
  materialId: number,
  payload: MaterialHazardPayload,
): Promise<MaterialHazard> {
  const { data } = await api.put<MaterialHazard>(
    `${BASE}/materials/${materialId}/hazard/`,
    payload,
  );
  return data;
}

export const listMaterialHazards = (params: ListParams = {}) =>
  list<MaterialHazard>(`${BASE}/material-hazards`, params);

// --- GBF ---

export const listSds = (params: ListParams = {}) => list<SafetyDataSheet>(SDS, params);

export async function getSds(id: number): Promise<SafetyDataSheet> {
  const { data } = await api.get<SafetyDataSheet>(`${SDS}/${id}/`);
  return data;
}

export async function createSds(payload: SdsPayload): Promise<SafetyDataSheet> {
  const { data } = await api.post<SafetyDataSheet>(`${SDS}/`, payload);
  return data;
}

export async function updateSds(
  id: number,
  payload: Partial<Omit<SdsPayload, "material">>,
): Promise<SafetyDataSheet> {
  const { data } = await api.patch<SafetyDataSheet>(`${SDS}/${id}/`, payload);
  return data;
}

export async function getSdsGaps(): Promise<SdsGap[]> {
  const { data } = await api.get<SdsGap[]>(`${BASE}/sds-gaps/`);
  return data;
}

/** Eksik GBF raporunun Excel çıktısı (indirme bağlantısı). */
export const SDS_GAPS_EXPORT_URL = "/api/v1/hse/sds-gaps/export/";

// --- depolama limitleri ---

export const listStorageLimits = (params: ListParams = {}) => list<StorageLimit>(LIMITS, params);

export async function saveStorageLimit(
  id: number | null,
  payload: StorageLimitPayload,
): Promise<StorageLimit> {
  const { data } = id
    ? await api.patch<StorageLimit>(`${LIMITS}/${id}/`, payload)
    : await api.post<StorageLimit>(`${LIMITS}/`, payload);
  return data;
}

export const setStorageLimitActive = (id: number, active: boolean) =>
  toggle<StorageLimit>(LIMITS, id, active);

export async function getStorageUtilisation(location?: number): Promise<StorageUtilisation[]> {
  const { data } = await api.get<StorageUtilisation[]>(`${BASE}/storage-utilisation/`, {
    params: location ? { location } : {},
  });
  return data;
}

// --- atık ---

export const listContractors = (params: ListParams = {}) =>
  list<WasteContractor>(CONTRACTORS, params);

export async function saveContractor(
  id: number | null,
  payload: WasteContractorPayload,
): Promise<WasteContractor> {
  const { data } = id
    ? await api.patch<WasteContractor>(`${CONTRACTORS}/${id}/`, payload)
    : await api.post<WasteContractor>(`${CONTRACTORS}/`, payload);
  return data;
}

export const setContractorActive = (id: number, active: boolean) =>
  toggle<WasteContractor>(CONTRACTORS, id, active);

export const listWasteRecords = (params: ListParams = {}) => list<WasteRecord>(WASTE, params);

export async function createWasteRecord(payload: WasteRecordPayload): Promise<WasteRecord> {
  const { data } = await api.post<WasteRecord>(`${WASTE}/`, payload);
  return data;
}

export async function cancelWasteRecord(id: number, reason: string): Promise<WasteRecord> {
  const { data } = await api.post<WasteRecord>(`${WASTE}/${id}/cancel/`, { reason });
  return data;
}

// --- olay / kaza ---

export async function listIncidents(
  params: ListParams = {},
  statuses: IncidentStatus[] = [],
): Promise<Paginated<Incident>> {
  const { data } = await api.get<Paginated<Incident>>(`${INCIDENTS}/`, {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function getIncident(id: number): Promise<Incident> {
  const { data } = await api.get<Incident>(`${INCIDENTS}/${id}/`);
  return data;
}

export async function reportIncident(payload: IncidentPayload): Promise<Incident> {
  const { data } = await api.post<Incident>(`${INCIDENTS}/`, payload);
  return data;
}

async function incidentAction(id: number, name: string, body: object): Promise<Incident> {
  const { data } = await api.post<Incident>(`${INCIDENTS}/${id}/${name}/`, body);
  return data;
}

export const startInvestigation = (id: number, payload: InvestigationPayload = {}) =>
  incidentAction(id, "investigate", payload);
export const saveInvestigation = (id: number, payload: InvestigationPayload) =>
  incidentAction(id, "investigation", payload);
export const closeIncident = (id: number, payload: ClosePayload) =>
  incidentAction(id, "close", payload);
export const cancelIncident = (id: number, reason: string) =>
  incidentAction(id, "cancel", { reason });

// --- özet, ayarlar ---

export async function getHseSummary(
  params: { date_from?: string; date_to?: string } = {},
): Promise<HseSummary> {
  const { data } = await api.get<HseSummary>(`${BASE}/summary/`, {
    params: clean(params as ListParams),
  });
  return data;
}

export async function getHseSettings(): Promise<HseSettings> {
  const { data } = await api.get<HseSettings>(`${BASE}/settings/`);
  return data;
}

export async function saveHseSettings(payload: Partial<HseSettings>): Promise<HseSettings> {
  const { data } = await api.patch<HseSettings>(`${BASE}/settings/`, payload);
  return data;
}
