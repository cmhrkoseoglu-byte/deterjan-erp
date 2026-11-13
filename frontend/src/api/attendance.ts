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
  /** Günün çalışma saati (yarım gün tatilde yarısı); günlük çalışma saati yoksa boş. */
  expected_hours: string | null;
}

export interface AttendanceCell {
  date: string;
  /** Boşsa kişi o gün işte değil. */
  status: AttendanceStatus | "";
  /** Yarım gün çalışılan günde "YG". */
  code: string;
  overtime_hours: string;
  /** Yarım gün tatilde (28 Ekim, arife) öğleden sonra da çalıştı (bordroda yarım günlük ilave). */
  holiday_half_worked: boolean;
  /** Sayılan çalışılan saat: kayıtlı saat günün çalışma saatinin altındaysa; tam günde boş. */
  worked_hours: string | null;
  /** Sayılan yarım gün işareti (YG): yalnızca sayılan saati olan günde. */
  short_day: boolean;
  note: string;
  /** Kayıtlı gün; değilse takvimden varsayılan. */
  explicit: boolean;
  editable: boolean;
}

export interface AttendanceTotals {
  /** Yarım gün çalışılan günler `WORKED` içinde sayılır. */
  days: Record<AttendanceStatus, number>;
  /** Yarım gün çalışılan günler (YG). */
  short_days: number;
  /** Tam gün çalışılan günler: `days.WORKED` − `short_days`. */
  full_days: number;
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
  /** Ayın bordrosu (yoksa boş): onaylıyken puantaj yeniden açılamaz. */
  payroll: { number: string; status: "OPEN" | "APPROVED" } | null;
  /**
   * Ayın günlük çalışma saati: ilk onayda kaydedilen değer (yeniden açılınca da korunur); kayıtlı
   * değer yoksa açık ayda güncel ayar, onaylı ayda boş. Ayar hiç belirlenmediyse de boş.
   */
  daily_hours: string | null;
  days: AttendanceColumn[];
  rows: AttendanceRow[];
}

export interface AttendanceDayInput {
  employee: number;
  date: string;
  status: AttendanceStatus;
  /** Yalnızca çalışılan güne (Ç), en çok günün çalışma saati; boşsa tam gün. */
  worked_hours: string | null;
  /** Yarım gün çalıştı (YG): yalnızca çalışılan saati günün çalışma saatinin altındaki güne. */
  short_day: boolean;
  overtime_hours?: string;
  /** Yalnızca yarım gün tatil olan çalışılan güne (Ç). */
  holiday_half_worked?: boolean;
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
  /** Günlük çalışma saati (herkes ve her iş günü için aynı); belirlenmediyse boş. */
  daily_hours: string | null;
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

/** Hata kodları: not_employed, overtime_not_allowed, invalid_overtime, future_day, month_locked,
 * short_day_not_allowed, worked_hours_not_allowed, daily_hours_not_set, invalid_worked_hours,
 * short_day_requires_hours, short_day_not_short, overtime_with_short_hours,
 * half_holiday_with_short_hours. */
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

/** Günlük çalışma saati yalnızca gönderilirse değişir. Hata kodları: invalid_rest_weekdays,
 * invalid_daily_hours, daily_hours_required. */
export async function saveAttendanceSettings(input: {
  rest_weekdays: number[];
  daily_hours?: string;
}): Promise<AttendanceSettings> {
  const { data } = await api.patch<AttendanceSettings>(`${BASE}/settings/`, input);
  return data;
}

export const attendanceKeys = {
  all: ["personnel", "attendance"] as const,
  grid: (year: number, month: number, department: string) =>
    ["personnel", "attendance", "grid", year, month, department] as const,
  holidays: (year: number) => ["personnel", "attendance", "holidays", year] as const,
  settings: ["personnel", "attendance", "settings"] as const,
};
