// /api/v1/personnel/payroll/* (admin ve yönetim): ön bordro, bordro parametreleri, mali müşavirde
// hesaplanan kişilerin rakamları ve çıktılar (docs/DECISIONS.md "Personel bordrosu"). Ücret ve
// kesinti bilgisi kişisel veridir (docs/KVKK.md).
import { api } from "./client";

const BASE = "/personnel/payroll";

export type PayrollWarning =
  | "missing_wage"
  | "below_minimum_wage"
  | "external_missing"
  | "exit_in_month"
  | "pay_without_sgk_days";

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

export interface PayrollItem {
  kind: string;
  description: string;
  amount: string;
}

/** Bordro satırının kalemleri (TL, kuruşa yuvarlanmış). */
export interface PayrollLine {
  employed_days: number;
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
  sgk_base: string;
  floor_applied: boolean;
  ceiling_applied: boolean;
  employee_sgk: string;
  employee_unemployment: string;
  tax_base: string;
  cumulative_tax_base_before: string;
  cumulative_tax_base_after: string;
  income_tax_computed: string;
  income_tax_exemption: string;
  income_tax: string;
  exemption_base_before: string;
  exemption_base_added: string;
  stamp_tax_computed: string;
  stamp_tax_exemption: string;
  stamp_tax: string;
  net_pay: string;
  bes_deduction: string;
  deductions: PayrollItem[];
  deductions_total: string;
  payable: string;
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
  salary: string;
  overtime_worked_pay: string;
  overtime_rest_pay: string;
  holiday_pay: string;
  extras_total: string;
  sgk_base: string;
  employee_sgk: string;
  employee_unemployment: string;
  income_tax: string;
  stamp_tax: string;
  net_pay: string;
  bes_deduction: string;
  deductions_total: string;
  payable: string;
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
  parameters: PayrollParametersInfo;
  rows: PayrollRow[];
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
