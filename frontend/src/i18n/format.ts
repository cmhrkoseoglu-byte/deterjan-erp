// Türkçe sayı ve tarih biçimleri: 1.234,56 ve 15.10.2026 (Europe/Istanbul).
const LOCALE = "tr-TR";
export const TIME_ZONE = "Europe/Istanbul";

type Numeric = number | string | null | undefined;

function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === "") return null;
  // API Decimal değerleri metin olarak döner ("1234.5600").
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Sayıyı Türkçe biçimler. `fractionDigits` verilmezse 0–4 arası ondalık gösterilir. */
export function formatNumber(value: Numeric, fractionDigits?: number): string {
  const n = toNumber(value);
  if (n === null) return "";
  return new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: fractionDigits ?? 0,
    maximumFractionDigits: fractionDigits ?? 4,
  }).format(n);
}

/** Para tutarı: her zaman 2 ondalık (CLAUDE.md §4.8). */
export function formatMoney(value: Numeric, currency?: string): string {
  const n = toNumber(value);
  if (n === null) return "";
  const text = formatNumber(n, 2);
  return currency ? `${text} ${currency}` : text;
}

function toDate(value: Date | string | null | undefined): Date | null {
  if (!value) return null;
  // Yalnızca tarih ("2026-10-15") yerel gün olarak ele alınır, UTC kaymasın.
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d, 12));
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 15.10.2026 */
export function formatDate(value: Date | string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "";
  return new Intl.DateTimeFormat(LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: TIME_ZONE,
  }).format(date);
}

/** 15.10.2026 14:30 */
export function formatDateTime(value: Date | string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "";
  const time = new Intl.DateTimeFormat(LOCALE, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: TIME_ZONE,
  }).format(date);
  return `${formatDate(date)} ${time}`;
}
