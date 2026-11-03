// /api/v1/personnel/payroll/* (admin ve yönetim): ön bordro, bordro parametreleri, mali müşavirde
// hesaplanan kişilerin rakamları, devir, ek ödeme ve kesintiler ve çıktılar (docs/DECISIONS.md
// "Personel bordrosu"). Ücret ve kesinti bilgisi kişisel veridir (docs/KVKK.md).
import axios from "axios";
import { api } from "./client";

const BASE = "/personnel/payroll";

export type PayrollWarning =
  | "missing_wage"
  | "below_minimum_wage"
  | "external_missing"
  | "exit_in_month"
  | "pay_without_sgk_days"
  | "opening_missing"
  | "carry_incomplete"
  | "negative_payable"
  | "ceiling_with_bonus";

export type PayrollItemKind = "EXTRA" | "DEDUCTION";
export type PayrollItemCategory =
  | "PREMIUM"
  | "BONUS"
  | "TRAVEL"
  | "MEAL"
  | "OTHER_EXTRA"
  | "ADVANCE"
  | "GARNISHMENT"
  | "OTHER_DEDUCTION";

export const EXTRA_CATEGORIES: PayrollItemCategory[] = [
  "PREMIUM",
  "BONUS",
  "TRAVEL",
  "MEAL",
  "OTHER_EXTRA",
];
export const DEDUCTION_CATEGORIES: PayrollItemCategory[] = [
  "ADVANCE",
  "GARNISHMENT",
  "OTHER_DEDUCTION",
];
/** Açıklaması zorunlu kategoriler (pusulada ne olduğu yazsın). */
export const DESCRIBED_CATEGORIES: PayrollItemCategory[] = ["OTHER_EXTRA", "OTHER_DEDUCTION"];

export function itemKind(category: PayrollItemCategory): PayrollItemKind {
  return EXTRA_CATEGORIES.includes(category) ? "EXTRA" : "DEDUCTION";
}

export interface PayrollEmployee {
  id: number;
  employee_no: string;
  full_name: string;
  department: string;
  title: string;
  hire_date: string | null;
  termination_date: string | null;
  is_active: boolean;
  payroll_external: boolean;
  bes_enrolled: boolean;
}

/** Hesaptaki kalem (motor): `kind` kalemin kategorisidir. */
export interface PayrollItem {
  kind: string;
  description: string;
  amount: string;
}

/** Ek ödeme ya da kesinti kaydı. */
export interface PayrollItemRecord {
  id: number;
  employee: number;
  employee_name: string;
  year: number;
  month: number;
  kind: PayrollItemKind;
  category: PayrollItemCategory;
  category_label: string;
  description: string;
  amount: string;
  is_active: boolean;
  created_at: string;
  created_by_name: string | null;
  updated_at: string;
  updated_by_name: string | null;
  removed_at: string | null;
  removed_by_name: string | null;
  removal_reason: string;
}

/** Devir: `month` ayından önceki kümülatif GV matrahı ve asgari ücret istisna matrahı. */
export interface PayrollOpening {
  id: number;
  employee: number;
  employee_name: string;
  year: number;
  month: number;
  tax_base: string;
  exemption_months: number;
  exemption_base: string;
  note: string;
  is_active: boolean;
  created_at: string;
  created_by_name: string | null;
  updated_at: string;
  updated_by_name: string | null;
  removed_at: string | null;
  removed_by_name: string | null;
  removal_reason: string;
}

/** Ay başı kümülatifin halkası. */
export interface CarryMonth {
  month: number;
  /** opening: devir (tutarlar o aydan önceki kümülatif); erp: o ayın eklenenleri; external: mali
   * müşavirdeydi (zincir kopar). */
  kind: "opening" | "erp" | "external";
  tax_base: string;
  exemption_base: string;
  flags: string[];
}

/** Bordro satırının kalemleri (TL, kuruşa yuvarlanmış). */
export interface PayrollLine {
  employed_days: number;
  /** Fiilen çalışılan gün (Ç, fazla mesaili hafta tatili ve resmî tatil). */
  worked_days: number;
  paid_days: number;
  unpaid_days: number;
  sick_days: number;
  unpaid_leave_days: number;
  absent_days: number;
  sgk_days: number;
  monthly_wage: string | null;
  missing_wage: boolean;
  salary: string;
  overtime_worked_hours: string;
  overtime_worked_pay: string;
  overtime_rest_hours: string;
  overtime_rest_pay: string;
  holiday_days: number;
  holiday_half_days: number;
  holiday_hours: string;
  holiday_extra_hours: string;
  holiday_pay: string;
  extras: PayrollItem[];
  extras_total: string;
  gross_total: string;
  /** Nakit yemeğin SGK matrahına girmeyen kısmı. */
  meal_exemption: string;
  /** SGK'ya tabi brüt (brüt − yemek istisnası). */
  sgk_gross: string;
  sgk_base: string;
  floor_applied: boolean;
  ceiling_applied: boolean;
  employee_sgk: string;
  employee_unemployment: string;
  // Brütten nete kalemler: başlangıç ayından önce boş (bordro mali müşavirde).
  tax_base: string | null;
  cumulative_tax_base_before: string | null;
  cumulative_tax_base_after: string | null;
  income_tax_computed: string | null;
  income_tax_exemption: string | null;
  income_tax: string | null;
  exemption_base_before: string | null;
  exemption_base_added: string | null;
  stamp_tax_computed: string | null;
  stamp_tax_exemption: string | null;
  stamp_tax: string | null;
  net_pay: string | null;
  bes_deduction: string | null;
  deductions: PayrollItem[];
  deductions_total: string | null;
  payable: string | null;
  employer_sgk_gross: string;
  incentive: string;
  employer_sgk: string;
  employer_unemployment: string;
  floor_gap: string;
  employer_cost: string;
}

export interface ExternalFigure {
  id: number;
  employee: number;
  year: number;
  month: number;
  gross_total: string;
  employer_cost: string;
  note: string;
  updated_at: string;
  updated_by_name: string | null;
}

export interface PayrollRow {
  employee: PayrollEmployee;
  /** Bordrosu mali müşavirde: tutarlar `figure`'dan gelir (girilmemişse boş). */
  external: boolean;
  figure: ExternalFigure | null;
  warnings: PayrollWarning[];
  line: PayrollLine;
  gross_total: string;
  employer_cost: string;
  /** Ayın ek ödeme ve kesintileri. */
  items: PayrollItemRecord[];
  /** Zincirin çapası olan devir (bu ay ya da önceki bir ay). */
  opening: PayrollOpening | null;
  /** Kişinin bu yıl bu aya kadarki etkin devirleri (ay sırasıyla). */
  openings: PayrollOpening[];
  /** Devrin beklendiği giriş ayı (zincir buradan başlar); brütten nete hesap yoksa boş. */
  entry_month: number | null;
  /** Giriş ayının devri girilmedi. */
  opening_needed: boolean;
  /** Giriş ayı devri için asgari ücret istisnası ay önerisi ve matrahı. */
  suggestion_months: number;
  suggestion_base: string;
  /** Ay başı kümülatifin kuruluşu. */
  carry_months: CarryMonth[];
}

export interface PayrollValues {
  minimum_wage: string;
  daily_floor: string;
  daily_ceiling: string;
  ceiling_multiplier: string;
  employee_sgk_rate: string;
  employee_unemployment_rate: string;
  employer_sgk_rate: string;
  employer_unemployment_rate: string;
  incentive_points: string;
  /** SGK işveren − teşvik + işsizlik işveren. */
  employer_rate: string;
  stamp_tax_per_mille: string;
  tax_brackets: string[];
  tax_rates: string[];
  exemption_base: string;
  bes_rate: string;
  /** Nakit yemek SGK istisnası (günlük TL). */
  meal_exemption_daily: string;
}

/** Hesapta kullanılan parametrelerin kaynağı. */
export type ParametersOrigin = "saved" | "legal_default" | "fallback";

export interface PayrollParametersInfo {
  origin: ParametersOrigin;
  /** Değerlerin ait olduğu yıl (tahminde başka yıl olabilir). */
  year: number;
  record: number | null;
  valid_from: string | null;
  values: PayrollValues;
}

export interface PayrollTotals {
  employee_count: number;
  external_count: number;
  /** Mali müşavirde hesaplananların rakamları dahil. */
  gross_total: string;
  /** Mali müşavirde hesaplananların rakamları dahil. */
  employer_cost: string;
  /** Yalnızca ERP'de hesaplanan satırlar. */
  computed_gross_total: string;
  computed_employer_cost: string;
  salary: string;
  overtime_worked_pay: string;
  overtime_rest_pay: string;
  holiday_pay: string;
  extras_total: string;
  sgk_base: string;
  employee_sgk: string;
  employee_unemployment: string;
  income_tax: string | null;
  stamp_tax: string | null;
  net_pay: string | null;
  bes_deduction: string | null;
  deductions_total: string | null;
  payable: string | null;
  employer_sgk_gross: string;
  incentive: string;
  employer_sgk: string;
  employer_unemployment: string;
  floor_gap: string;
}

export interface PayrollMonth {
  year: number;
  month: number;
  period_label: string;
  attendance_status: "OPEN" | "APPROVED";
  attendance_number: string;
  attendance_approved: boolean;
  attendance_finished: boolean;
  /** Brütten nete hesaplandı mı (başlangıç ayından önce hayır; net alanları boş). */
  net: boolean;
  net_available: boolean;
  /** Brütten nete bordronun ilk ayı ("2026-10"). */
  start: string;
  parameters: PayrollParametersInfo;
  rows: PayrollRow[];
  /** Bu ay işte olmayan kişilere girilmiş kalemler. */
  orphan_items: PayrollItemRecord[];
  totals: PayrollTotals;
}

/** Parametre setinin girilen değerleri (tutarlar ve oranlar metin, nokta ondalıklı). */
export interface ParameterSetValues {
  minimum_wage: string;
  ceiling_multiplier: string;
  employee_sgk_rate: string;
  employee_unemployment_rate: string;
  employer_sgk_rate: string;
  employer_unemployment_rate: string;
  incentive_points: string;
  stamp_tax_per_mille: string;
  tax_bracket_1: string;
  tax_bracket_2: string;
  tax_bracket_3: string;
  tax_bracket_4: string;
  tax_rate_1: string;
  tax_rate_2: string;
  tax_rate_3: string;
  tax_rate_4: string;
  tax_rate_5: string;
  bes_rate: string;
  meal_exemption_daily: string;
}

export interface ParameterSet extends ParameterSetValues {
  id: number;
  valid_from: string;
  source: string;
  note: string;
  year: number;
  /** Setten hesaplanan değerler (günlük sınırlar, etkin işveren oranı, istisna matrahı). */
  derived: PayrollValues;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  updated_by_name: string | null;
}

export type ParameterSetInput = ParameterSetValues & {
  /** "2026-01" ya da tarih; ayın ilk gününe çekilir. */
  valid_from: string;
  source: string;
  note: string;
};

export interface ParameterDefaults {
  year: number;
  /** Yılın yasal değerleri biliniyor mu? Bilinmiyorsa en yakın yılın değerleri döner. */
  known: boolean;
  values_year: number;
  legal_source: string;
  values: PayrollValues;
}

export const payrollKeys = {
  all: ["personnel", "payroll"] as const,
  month: (year: number, month: number) => ["personnel", "payroll", "month", year, month] as const,
  parameters: ["personnel", "payroll", "parameters"] as const,
  defaults: (year: number) => ["personnel", "payroll", "defaults", year] as const,
  items: (filters: Record<string, unknown>) => ["personnel", "payroll", "items", filters] as const,
  openings: (filters: Record<string, unknown>) =>
    ["personnel", "payroll", "openings", filters] as const,
};

const monthPath = (year: number, month: number) => `${BASE}/${year}/${month}`;

export async function getPayrollMonth(year: number, month: number): Promise<PayrollMonth> {
  const { data } = await api.get<PayrollMonth>(`${monthPath(year, month)}/`);
  return data;
}

export function employerCostPdfUrl(year: number, month: number): string {
  return `/api/v1${monthPath(year, month)}/employer-cost.pdf`;
}

export function payrollExcelUrl(year: number, month: number): string {
  return `/api/v1${monthPath(year, month)}/xlsx/`;
}

export function registerPdfUrl(year: number, month: number): string {
  return `/api/v1${monthPath(year, month)}/register.pdf`;
}

/** Hata kodları: not_external, not_employed, invalid_amount, invalid_employer_cost,
 * external_incomplete, invalid_period. */
export async function setExternalFigure(
  year: number,
  month: number,
  payload: { employee: number; gross_total: string; employer_cost: string; note: string },
): Promise<ExternalFigure> {
  const { data } = await api.post<ExternalFigure>(`${monthPath(year, month)}/external/`, payload);
  return data;
}

export async function listParameterSets(): Promise<ParameterSet[]> {
  const { data } = await api.get<ParameterSet[]>(`${BASE}/parameters/`);
  return data;
}

export async function getParameterDefaults(year: number): Promise<ParameterDefaults> {
  const { data } = await api.get<ParameterDefaults>(`${BASE}/parameters/defaults/`, {
    params: { year },
  });
  return data;
}

/** Hata kodları: parameters_incomplete, invalid_valid_from, invalid_minimum_wage, invalid_ceiling,
 * invalid_rate, invalid_incentive, invalid_stamp_tax, invalid_brackets, duplicate_parameters,
 * parameters_removed. */
export async function saveParameterSet(
  id: number | null,
  payload: ParameterSetInput,
): Promise<ParameterSet> {
  if (id === null) {
    const { data } = await api.post<ParameterSet>(`${BASE}/parameters/`, payload);
    return data;
  }
  const { data } = await api.patch<ParameterSet>(`${BASE}/parameters/${id}/`, payload);
  return data;
}

export async function removeParameterSet(id: number, reason: string): Promise<ParameterSet> {
  const { data } = await api.post<ParameterSet>(`${BASE}/parameters/${id}/remove/`, { reason });
  return data;
}

export async function removeExternalFigure(id: number, reason: string): Promise<ExternalFigure> {
  const { data } = await api.post<ExternalFigure>(`${BASE}/external/${id}/remove/`, { reason });
  return data;
}

// --- devir, ek ödeme ve kesintiler ----------------------------------------------------------------

interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Toplu kaydın satır hatası (hiçbir satır kaydedilmedi). */
export interface BatchErrorRow {
  index: number;
  employee: number | null;
  code: string;
  detail: string;
}

/** Toplu kaydın reddindeki satır hataları; başka bir hataysa boş. */
export function getBatchErrors(error: unknown): BatchErrorRow[] {
  if (!axios.isAxiosError(error)) return [];
  const data = error.response?.data as { code?: string; rows?: BatchErrorRow[] } | undefined;
  return data?.code === "batch_rejected" && Array.isArray(data.rows) ? data.rows : [];
}

export interface PayrollItemInput {
  employee: number;
  category: PayrollItemCategory;
  description: string;
  amount: string;
}

export async function listPayrollItems(params: {
  year?: number;
  month?: number;
  employee?: number;
  is_active?: boolean;
  page?: number;
  /** En çok 500. */
  page_size?: number;
}): Promise<Page<PayrollItemRecord>> {
  const { data } = await api.get<Page<PayrollItemRecord>>(`${BASE}/items/`, { params });
  return data;
}

/** Hata kodları: before_start, future_month, not_employed, not_computed, invalid_category,
 * description_required, invalid_amount. */
export async function addPayrollItem(
  year: number,
  month: number,
  payload: PayrollItemInput,
): Promise<PayrollItemRecord> {
  const { data } = await api.post<PayrollItemRecord>(`${BASE}/items/`, {
    ...payload,
    year,
    month,
  });
  return data;
}

/** Toplu ekleme (hepsi ya da hiçbiri; satır hataları `getBatchErrors`). */
export async function addPayrollItems(
  year: number,
  month: number,
  items: PayrollItemInput[],
): Promise<PayrollItemRecord[]> {
  const { data } = await api.post<PayrollItemRecord[]>(`${BASE}/items/batch/`, {
    year,
    month,
    items,
  });
  return data;
}

/** Hata kodları: item_removed, invalid_category, description_required, invalid_amount. */
export async function updatePayrollItem(
  id: number,
  payload: Partial<Pick<PayrollItemInput, "category" | "description" | "amount">>,
): Promise<PayrollItemRecord> {
  const { data } = await api.patch<PayrollItemRecord>(`${BASE}/items/${id}/`, payload);
  return data;
}

export async function removePayrollItem(id: number, reason: string): Promise<PayrollItemRecord> {
  const { data } = await api.post<PayrollItemRecord>(`${BASE}/items/${id}/remove/`, { reason });
  return data;
}

export interface OpeningInput {
  employee: number;
  tax_base: string;
  exemption_months: number;
  note: string;
  /** Kişi önceki ay ERP'de hesaplandıysa devrin o ayların yerine geçtiği onayı. */
  confirm_override: boolean;
}

export async function listOpenings(params: {
  year?: number;
  month?: number;
  employee?: number;
  is_active?: boolean;
}): Promise<Page<PayrollOpening>> {
  const { data } = await api.get<Page<PayrollOpening>>(`${BASE}/openings/`, { params });
  return data;
}

/** Hata kodları: before_start, opening_not_needed, not_computed, not_employed, invalid_tax_base,
 * invalid_exemption_months, opening_overrides_chain. */
export async function saveOpening(
  year: number,
  month: number,
  payload: OpeningInput,
): Promise<PayrollOpening> {
  const { data } = await api.post<PayrollOpening>(`${BASE}/openings/`, {
    ...payload,
    year,
    month,
  });
  return data;
}

/** Ayın devirleri toplu (hepsi ya da hiçbiri; satır hataları `getBatchErrors`). */
export async function saveOpenings(
  year: number,
  month: number,
  rows: OpeningInput[],
): Promise<PayrollOpening[]> {
  const { data } = await api.post<PayrollOpening[]>(`${BASE}/openings/batch/`, {
    year,
    month,
    rows,
  });
  return data;
}

export async function removeOpening(id: number, reason: string): Promise<PayrollOpening> {
  const { data } = await api.post<PayrollOpening>(`${BASE}/openings/${id}/remove/`, { reason });
  return data;
}
