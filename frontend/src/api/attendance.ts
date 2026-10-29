// /api/v1/personnel/attendance/* (admin ve yönetim): aylık puantaj, tatil takvimi, ayarlar.
// Rapor (sağlık) bilgisi içerir; kişisel veri (docs/KVKK.md). Onaylı ay kilitlidir.
import { api } from "./client";

const BASE = "/personnel/attendance";

export type AttendanceStatus =
  | "WORKED"
  | "WEEKLY_REST"
  | "PUBLIC_HOLIDAY"
  | "ANNUAL_LEAVE"
  | "PAID_LEAVE"
  | "UNPAID_LEAVE"
  | "SICK_LEAVE"
  | "ABSENT";

/** Fazla mesai yalnızca bu günlere girilir (backend `OVERTIME_STATUSES`). */
export const OVERTIME_STATUSES: AttendanceStatus[] = ["WORKED", "WEEKLY_REST", "PUBLIC_HOLIDAY"];

export interface AttendanceColumn {
  date: string;
  /** pazartesi 0 … pazar 6 */
  weekday: number;
  /** Varsayılan hafta tatili günü. */
  rest: boolean;
  holiday_name: string;
  half_day: boolean;
}

export interface AttendanceCell {
  date: string;
  /** Boşsa kişi o gün işte değil. */
  status: AttendanceStatus | "";
  code: string;
  overtime_hours: string;
  note: string;
  /** Kayıtlı gün; değilse takvimden varsayılan. */
  explicit: boolean;
  editable: boolean;
}

export interface AttendanceTotals {
  days: Record<AttendanceStatus, number>;
  /** Ücretsiz izin + rapor + devamsız. */
  missing_days: number;
  overtime: Record<"WORKED" | "WEEKLY_REST" | "PUBLIC_HOLIDAY", string>;
  overtime_total: string;
}

export interface AttendanceEmployee {
  id: number;
  employee_no: string;
  full_name: string;
  department: string;
  is_active: boolean;
}

export interface AttendanceRow {
  employee: AttendanceEmployee;
  cells: AttendanceCell[];
  totals: AttendanceTotals;
}

export interface AttendanceMonthRecord {
  id: number;
  number: string;
  year: number;
  month: number;
  status: "OPEN" | "APPROVED";
  status_display: string;
  approved_at: string | null;
  approved_by_name: string | null;
}

export interface AttendanceGrid {
  year: number;
  month: number;
  period_label: string;
  status: "OPEN" | "APPROVED";
  /** Ay bitti mi (onay ancak ay bitince). */
  finished: boolean;
  /** Ay hiç yazılmadıysa boş. */
  month_record: AttendanceMonthRecord | null;
  days: AttendanceColumn[];
  rows: AttendanceRow[];
}

export interface AttendanceDayInput {
  employee: number;
  date: string;
  status: AttendanceStatus;
  overtime_hours?: string;
  note?: string;
}

/** Tek kişi (`employee`), bir birim (`department`) ya da ikisi de boşsa herkes. */
export interface AttendanceRangeInput {
  employee?: number | null;
  department?: string;
  start: string;
  end: string;
  status: AttendanceStatus;
  note?: string;
}

export interface PublicHoliday {
  id: number;
  date: string;
  name: string;
  half_day: boolean;
}

export type PublicHolidayInput = Omit<PublicHoliday, "id">;

export interface AttendanceSettings {
  /** Hafta tatili günleri: pazartesi 0 … pazar 6. */
  rest_weekdays: number[];
  updated_at: string;
}

export async function getAttendanceGrid(
  year: number,
  month: number,
  department = "",
): Promise<AttendanceGrid> {
  const { data } = await api.get<AttendanceGrid>(`${BASE}/${year}/${month}/`, {
    params: { department: department || undefined },
  });
  return data;
}

/** Hata kodları: not_employed, overtime_not_allowed, invalid_overtime, future_day, month_locked. */
export async function setAttendanceDay(input: AttendanceDayInput): Promise<void> {
  await api.post(`${BASE}/days/`, input);
}

/** Değişen gün sayısını döner. Hata kodları: invalid_range, range_too_long, no_employees,
 * future_day, month_locked. */
export async function setAttendanceRange(input: AttendanceRangeInput): Promise<number> {
  const { data } = await api.post<{ updated: number }>(`${BASE}/ranges/`, input);
  return data.updated;
}

/** Hata kodları: month_not_finished, month_locked. */
export async function approveAttendanceMonth(
  year: number,
  month: number,
): Promise<AttendanceMonthRecord> {
  const { data } = await api.post<AttendanceMonthRecord>(`${BASE}/${year}/${month}/approve/`);
  return data;
}

export async function reopenAttendanceMonth(
  year: number,
  month: number,
  reason: string,
): Promise<AttendanceMonthRecord> {
  const { data } = await api.post<AttendanceMonthRecord>(`${BASE}/${year}/${month}/reopen/`, {
    reason,
  });
  return data;
}

/** Excel çıktısı (indirme bağlantısı; oturum çereziyle). */
export function attendanceExportUrl(year: number, month: number, department = ""): string {
  const query = department ? `?department=${encodeURIComponent(department)}` : "";
  return `/api/v1${BASE}/${year}/${month}/export/${query}`;
}

export async function listHolidays(year: number): Promise<PublicHoliday[]> {
  const { data } = await api.get<PublicHoliday[]>(`${BASE}/holidays/`, { params: { year } });
  return data;
}

/** Hata kodları: holiday_exists, name_required, month_locked. */
export async function saveHoliday(
  id: number | null,
  input: PublicHolidayInput,
): Promise<PublicHoliday> {
  const { data } = id
    ? await api.patch<PublicHoliday>(`${BASE}/holidays/${id}/`, input)
    : await api.post<PublicHoliday>(`${BASE}/holidays/`, input);
  return data;
}

export async function removeHoliday(id: number): Promise<void> {
  await api.post(`${BASE}/holidays/${id}/remove/`);
}

/** Yılın sabit resmi tatillerini ekler; eklenenleri döner (zaten olanlar atlanır). */
export async function addFixedHolidays(year: number): Promise<PublicHoliday[]> {
  const { data } = await api.post<PublicHoliday[]>(`${BASE}/holidays/fixed/`, { year });
  return data;
}

export async function getAttendanceSettings(): Promise<AttendanceSettings> {
  const { data } = await api.get<AttendanceSettings>(`${BASE}/settings/`);
  return data;
}

/** Hata kodu: invalid_rest_weekdays. */
export async function saveAttendanceSettings(restWeekdays: number[]): Promise<AttendanceSettings> {
  const { data } = await api.patch<AttendanceSettings>(`${BASE}/settings/`, {
    rest_weekdays: restWeekdays,
  });
  return data;
}

export const attendanceKeys = {
  all: ["personnel", "attendance"] as const,
  grid: (year: number, month: number, department: string) =>
    ["personnel", "attendance", "grid", year, month, department] as const,
  holidays: (year: number) => ["personnel", "attendance", "holidays", year] as const,
  settings: ["personnel", "attendance", "settings"] as const,
};
