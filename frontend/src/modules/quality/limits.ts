import type { SpecLine, TestResult } from "../../api/quality";
import { formatNumber } from "../../i18n/format";
import { normalizeDecimal } from "../common/forms";
import { qt } from "./strings";

/** Spesifikasyon sınırı metni: "6–8", "≥ 12", "≤ 50" ya da beklenen değer. */
export function limitText(line: SpecLine): string {
  if (line.result_type !== "NUMERIC") {
    if (line.text_expected) return line.text_expected;
    return line.result_type === "PASS_FAIL" ? qt.pass : "";
  }
  const places = line.decimal_places;
  const low = line.min_value !== null ? formatNumber(line.min_value, places) : "";
  const high = line.max_value !== null ? formatNumber(line.max_value, places) : "";
  const unit = line.unit ? ` ${line.unit}` : "";
  if (low && high) return `${low} – ${high}${unit}`;
  return low ? `≥ ${low}${unit}` : `≤ ${high}${unit}`;
}

/** Sonuç metni (test türüne göre). */
export function resultText(line: SpecLine, result: TestResult): string {
  if (line.result_type === "NUMERIC")
    return `${formatNumber(result.numeric_value, line.decimal_places)}${line.unit ? ` ${line.unit}` : ""}`;
  if (line.result_type === "PASS_FAIL") return result.passed ? qt.pass : qt.fail;
  return result.text_value;
}

/**
 * Girilmekte olan sayısal değer sınırların dışında mı? Kaydetmeden önce kırmızı göstermek
 * içindir; asıl değerlendirme backend'dedir. Boş ya da sayı olmayan girişte `null`.
 */
export function numericOutOfSpec(line: SpecLine, input: string): boolean | null {
  if (line.result_type !== "NUMERIC" || !input.trim()) return null;
  const value = Number(normalizeDecimal(input));
  if (!Number.isFinite(value)) return null;
  if (line.min_value !== null && value < Number(line.min_value)) return true;
  if (line.max_value !== null && value > Number(line.max_value)) return true;
  return false;
}
