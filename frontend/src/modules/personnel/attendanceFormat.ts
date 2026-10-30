// Puantaj yardımcıları: durum seçenekleri, takvim durumu, saat ve gün biçimleri.
import type { AttendanceColumn, AttendanceStatus } from "../../api/attendance";
import { formatDate } from "../../i18n/format";
import { at } from "./strings";

const STATUSES = Object.keys(at.labels) as AttendanceStatus[];
export const STATUS_OPTIONS = STATUSES.map((value) => ({
  value,
  label: `${at.codes[value]} · ${at.labels[value]}`,
}));

/** Değiştirilmemiş günün takvimdeki durumu (backend `default_status` ile aynı kural). */
export function calendarStatus(column: AttendanceColumn): AttendanceStatus {
  if (column.holiday_name && !column.half_day) return "PUBLIC_HOLIDAY";
  return column.rest ? "WEEKLY_REST" : "WORKED";
}

/** "2,5" → "2.5"; boş → "0"; geçersizse null. */
export function parseHours(text: string): string | null {
  const value = text.trim().replace(",", ".");
  if (!value) return "0";
  if (!/^\d{1,2}(\.\d{1,2})?$/.test(value) || Number(value) > 24) return null;
  return value;
}

/** "2.50" → "2,5" (sıfırsa boş). */
export function formatHours(value: string): string {
  const hours = Number(value);
  return hours ? String(hours).replace(".", ",") : "";
}

/** Puantaj sayfasının `?ay=` değeri: "2026-10". */
export function monthParam(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

/** Günden sonraki günün ayı: "2026-09-30" → "2026-10" (çıkıştan sonraki ilk gün). */
export function monthAfterDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1, day + 1));
  return monthParam(next.getUTCFullYear(), next.getUTCMonth() + 1);
}

/** "05.10.2026 Pazartesi" */
export function dayLabel(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const weekday = (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
  return `${formatDate(iso)} ${at.weekdayNames[weekday]}`;
}
