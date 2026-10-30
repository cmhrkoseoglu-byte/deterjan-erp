// /api/v1/costing/* uç noktaları (lot maliyeti, gider oranları, standart maliyet, raporlar;
// Faz 4 Adım 4.1). Yalnızca yonetim ve admin erişir. Tutarlar TL, metin olarak gelir.
import { api } from "./client";
import type { MaterialType } from "./masterdata";
import type { Paginated } from "./types";

export type CostMethod = "PURCHASE" | "PRODUCTION" | "FILLING" | "ESTIMATE";
export type CostCategory =
  | "PURCHASE"
  | "EXTRA"
  | "MATERIAL"
  | "BULK"
  | "PACKAGING"
  | "SCRAP"
  | "ENERGY"
  | "LABOR"
  | "DEPRECIATION"
  | "ESTIMATE";
export type CostStage = "PRODUCTION" | "FILLING";
export type RateKind = "ENERGY" | "LABOR" | "DEPRECIATION";

export interface LotCost {
  id: number;
  lot: number;
  lot_no: string;
  lot_source: string;
  material: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  version: number;
  is_current: boolean;
  method: CostMethod;
  quantity: string;
  total_cost: string;
  unit_cost: string | null;
  finished_scrap_cost: string;
  is_estimated: boolean;
  has_missing: boolean;
  cost_date: string;
  calculated_at: string;
  calculated_by_name: string | null;
  note: string;
}

export interface LotCostLine {
  line_no: number;
  category: CostCategory;
  description: string;
  material: number | null;
  material_code: string | null;
  source_lot: number | null;
  source_lot_no: string | null;
  quantity: string | null;
  unit: string | null;
  unit_cost: string | null;
  amount: string;
  is_estimated: boolean;
  is_missing: boolean;
}

export interface LotCostDetail extends LotCost {
  lines: LotCostLine[];
}

export interface LotCostHistory {
  lot: number;
  lot_no: string;
  material_code: string;
  material_name: string;
  is_costable: boolean;
  versions: LotCostDetail[];
}

export interface CostRate {
  id: number;
  stage: CostStage;
  kind: RateKind;
  rate_per_kg: string;
  valid_from: string;
  note: string;
  created_at: string;
  created_by_name: string | null;
}

export interface StandardCost {
  id: number;
  material: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  unit_cost: string;
  note: string;
  is_active: boolean;
  updated_at: string;
}

export interface CostTrendRow {
  material_id: number;
  material_code: string;
  material_name: string;
  unit: string;
  month: string;
  lot_count: number;
  quantity: string;
  total_cost: string;
  unit_cost: string | null;
  has_estimated: boolean;
}

export interface BatchVarianceRow {
  lot_cost_id: number;
  lot_id: number;
  lot_no: string;
  order_number: string;
  product_code: string;
  product_name: string;
  unit: string;
  cost_date: string;
  planned_quantity: string;
  actual_quantity: string;
  theoretical_material_cost: string;
  actual_material_cost: string;
  overhead_cost: string;
  total_cost: string;
  theoretical_unit_cost: string | null;
  actual_material_unit_cost: string | null;
  unit_cost: string | null;
  variance_pct: string | null;
  is_estimated: boolean;
}

export interface ScrapCostRow {
  lot_cost_id: number;
  lot_id: number;
  lot_no: string;
  product_code: string;
  product_name: string;
  cost_date: string;
  good_units: string;
  material_scrap_cost: string;
  finished_scrap_cost: string;
  total_scrap_cost: string;
  total_cost: string;
  scrap_pct: string | null;
}

export interface TopMaterialRow {
  material_id: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  quantity: string;
  amount: string;
  average_unit_cost: string | null;
  share_pct: string | null;
  has_missing: boolean;
}

export interface StockValueRow {
  material_id: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  quantity: string;
  value: string;
  average_unit_cost: string | null;
  uncosted_quantity: string;
  estimated_quantity: string;
}

export interface StockValue {
  total_value: string;
  by_type: { material_type: MaterialType; value: string }[];
  rows: StockValueRow[];
}

export type ReportName =
  "cost-trend" | "batch-variance" | "scrap-cost" | "top-materials" | "stock-value";

export type ReportParams = Record<string, string | number | undefined>;

function clean(params: ReportParams): ReportParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

export async function listLotCosts(params: ReportParams = {}): Promise<Paginated<LotCost>> {
  const { data } = await api.get<Paginated<LotCost>>("/costing/lot-costs/", {
    params: clean(params),
  });
  return data;
}

export async function getLotCostHistory(lotId: number): Promise<LotCostHistory> {
  const { data } = await api.get<LotCostHistory>(`/costing/lots/${lotId}/`);
  return data;
}

export async function recalculateLotCost(
  lotId: number,
  note: string,
  cascade: boolean,
): Promise<LotCostHistory> {
  const { data } = await api.post<LotCostHistory>(`/costing/lots/${lotId}/recalculate/`, {
    note,
    cascade,
  });
  return data;
}

export async function listRates(): Promise<Paginated<CostRate>> {
  const { data } = await api.get<Paginated<CostRate>>("/costing/rates/", {
    params: { page_size: 500 },
  });
  return data;
}

export async function createRate(
  payload: Pick<CostRate, "stage" | "kind" | "rate_per_kg" | "valid_from" | "note">,
): Promise<CostRate> {
  const { data } = await api.post<CostRate>("/costing/rates/", payload);
  return data;
}

export async function listStandardCosts(
  params: ReportParams = {},
): Promise<Paginated<StandardCost>> {
  const { data } = await api.get<Paginated<StandardCost>>("/costing/standard-costs/", {
    params: clean(params),
  });
  return data;
}

export async function saveStandardCost(
  payload: { material: number; unit_cost: string; note: string },
  id?: number,
): Promise<StandardCost> {
  const { data } = id
    ? await api.patch<StandardCost>(`/costing/standard-costs/${id}/`, payload)
    : await api.post<StandardCost>("/costing/standard-costs/", payload);
  return data;
}

export async function setStandardCostActive(id: number, isActive: boolean): Promise<StandardCost> {
  const { data } = await api.patch<StandardCost>(`/costing/standard-costs/${id}/`, {
    is_active: isActive,
  });
  return data;
}

export async function getReport<T>(name: ReportName, params: ReportParams = {}): Promise<T> {
  const { data } = await api.get<T>(`/costing/reports/${name}/`, { params: clean(params) });
  return data;
}

export function reportExcelUrl(name: ReportName, params: ReportParams = {}): string {
  const query = new URLSearchParams(
    Object.entries(clean(params)).map(([key, value]) => [key, String(value)]),
  ).toString();
  return `/api/v1/costing/reports/${name}/xlsx/${query ? `?${query}` : ""}`;
}

// --- personel maliyeti -----------------------------------------------------------------------
// Brüt ücret + puantajdan aylık maliyet ve işçilik oranı önerisi (docs/DECISIONS.md "Personel
// maliyeti"). Ücretler kişisel veridir (docs/KVKK.md); yalnızca yönetim ve admin erişir.

/** Birimin maliyet aşaması; boş = genel gider. */
export type CostCenterStage = CostStage | "";

export interface CostEmployee {
  id: number;
  employee_no: string;
  full_name: string;
  department: string;
  hire_date: string | null;
  /** Ayrılmışsa çıkış tarihi. */
  termination_date: string | null;
  is_active: boolean;
}

export interface PersonnelCostRow {
  employee: CostEmployee;
  stage: CostCenterStage;
  /** Ayda işte olunan son gün geçerli brüt aylık ücret; o gün için ücret yoksa boş. */
  gross_monthly: string | null;
  employed_days: number;
  unpaid_days: number;
  /** 30 gün usulü: tam ayda 30 − ücretsiz gün (hiç ücretli gün yoksa 0; 30 ya da daha çok
   * ücretsiz günde ücretli takvim günü); ay içinde giren ya da ayrılanda ücretli takvim günü. */
  paid_days: number;
  overtime_hours: string;
  gross_salary: string;
  overtime_pay: string;
  gross_total: string;
  employer_share: string;
  total_cost: string;
  /** Ayın en az bir günü için ücret yok (o günler sıfır sayıldı). */
  missing_wage: boolean;
}

export interface StageCost {
  stage: CostCenterStage;
  cost: string;
  employee_count: number;
  /** Ay içinde üretilen kg (genel giderde boş). */
  kg: string | null;
  /** Yoğunluğu girilmediği için üretimi kg'a çevrilemeyen malzeme sayısı. */
  unconverted: number;
  current_rate: string | null;
  /** Gerçekleşen işçilik (TL/kg); genel giderde, üretim ya da maliyet yokken boş. */
  suggested_rate: string | null;
  /** Aşamada ücreti eksik kişi sayısı. */
  missing_wage_count: number;
}

export interface PersonnelCostReport {
  year: number;
  month: number;
  period_label: string;
  attendance_status: "OPEN" | "APPROVED";
  attendance_number: string;
  attendance_approved: boolean;
  employer_rate: string;
  missing_wage_count: number;
  gross_salary: string;
  overtime_pay: string;
  employer_share: string;
  total_cost: string;
  stages: StageCost[];
  rows: PersonnelCostRow[];
}

export interface EmployeeWage {
  id: number;
  employee: number;
  employee_name: string;
  gross_monthly: string;
  valid_from: string;
  note: string;
  is_active: boolean;
  removal_reason: string;
  created_at: string;
  created_by_name: string | null;
}

export interface WageSummaryRow {
  employee: CostEmployee;
  stage: CostCenterStage;
  /** Bugün geçerli ücret; yoksa (hiç girilmedi ya da gelecek tarihli) boş. */
  current_wage: string | null;
  current_valid_from: string | null;
  /** Kaldırılmamış ücretler, en yenisi önce. */
  history: EmployeeWage[];
}

export interface CostCenter {
  department: string;
  stage: CostCenterStage;
}

export interface PersonnelCostSettings {
  employer_rate: string;
  /** Ayar hiç kaydedilmediyse boş (varsayılan oran). */
  updated_at: string | null;
}

export const personnelCostKeys = {
  all: ["costing", "personnel-cost"] as const,
  report: (year: number, month: number) => ["costing", "personnel-cost", year, month] as const,
  wages: ["costing", "wages"] as const,
  wageList: (includeFormer: boolean) => ["costing", "wages", includeFormer] as const,
  costCenters: ["costing", "cost-centers"] as const,
  settings: ["costing", "personnel-cost-settings"] as const,
};

const personnelMonth = (year: number, month: number) => `/costing/personnel-costs/${year}/${month}`;

export async function getPersonnelCost(year: number, month: number): Promise<PersonnelCostReport> {
  const { data } = await api.get<PersonnelCostReport>(`${personnelMonth(year, month)}/`);
  return data;
}

export function personnelCostExcelUrl(year: number, month: number): string {
  return `/api/v1${personnelMonth(year, month)}/xlsx/`;
}

/** Onaylı ayın gerçekleşen işçiliğinden yeni işçilik oranı. Hata kodları: invalid_stage,
 * attendance_not_approved, no_labor_rate, duplicate_rate. */
export async function addLaborRateFromPersonnelCost(
  year: number,
  month: number,
  payload: { stage: CostStage; valid_from: string },
): Promise<CostRate> {
  const { data } = await api.post<CostRate>(`${personnelMonth(year, month)}/labor-rate/`, payload);
  return data;
}

/** Çalışanlar (çıkış tarihi bugün ya da sonra olanlar dahil); `includeFormer` ile ayrılanlar da. */
export async function getWageSummary(includeFormer = false): Promise<WageSummaryRow[]> {
  const { data } = await api.get<WageSummaryRow[]>("/costing/wages/summary/", {
    params: includeFormer ? { include_former: true } : undefined,
  });
  return data;
}

/** Hata kodları: employee_required, valid_from_required, invalid_valid_from, invalid_wage,
 * duplicate_wage. */
export async function addWage(payload: {
  employee: number;
  gross_monthly: string;
  valid_from: string;
  note: string;
}): Promise<EmployeeWage> {
  const { data } = await api.post<EmployeeWage>("/costing/wages/", payload);
  return data;
}

export async function removeWage(id: number, reason: string): Promise<EmployeeWage> {
  const { data } = await api.post<EmployeeWage>(`/costing/wages/${id}/remove/`, { reason });
  return data;
}

export async function listCostCenters(): Promise<CostCenter[]> {
  const { data } = await api.get<CostCenter[]>("/costing/cost-centers/");
  return data;
}

export async function setCostCenter(payload: CostCenter): Promise<CostCenter> {
  const { data } = await api.put<CostCenter>("/costing/cost-centers/", payload);
  return data;
}

export async function getPersonnelCostSettings(): Promise<PersonnelCostSettings> {
  const { data } = await api.get<PersonnelCostSettings>("/costing/personnel-cost-settings/");
  return data;
}

export async function updatePersonnelCostSettings(
  employerRate: string,
): Promise<PersonnelCostSettings> {
  const { data } = await api.patch<PersonnelCostSettings>("/costing/personnel-cost-settings/", {
    employer_rate: employerRate,
  });
  return data;
}
