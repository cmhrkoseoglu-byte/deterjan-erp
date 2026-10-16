import { formatNumber } from "../../i18n/format";

const UNITS = ["B", "KB", "MB", "GB", "TB"];

/** Bayt değerini okunur biçimde verir: 1,5 GB. */
export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  let size = Math.max(0, value);
  let unit = 0;
  while (size >= 1024 && unit < UNITS.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${formatNumber(unit === 0 ? Math.round(size) : Number(size.toFixed(1)))} ${UNITS[unit]}`;
}
