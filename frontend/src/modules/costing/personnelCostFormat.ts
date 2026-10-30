// Personel maliyeti yardımcıları: ay seçimi, aşama adı, tutar girişi.
import type { CostCenterStage } from "../../api/costing";
import { normalizeDecimal } from "../common/forms";
import { today } from "../inventory/config";
import { kt } from "./strings";

/** `?ay=2026-09`; yoksa ya da geçersizse geçen ay (ücret maliyeti ay bitince kesinleşir). */
export function parseMonth(text: string | null): { year: number; month: number } {
  const match = text?.match(/^(\d{4})-(\d{2})$/);
  const month = match ? Number(match[2]) : 0;
  if (match && month >= 1 && month <= 12) return { year: Number(match[1]), month };
  const [year, current] = today().split("-").map(Number);
  return current === 1 ? { year: year - 1, month: 12 } : { year, month: current - 1 };
}

export function monthParam(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

/** Ay kaydırma: (2026, 1, -1) → 2025-12. */
export function shiftMonth(year: number, month: number, offset: number): string {
  const index = year * 12 + (month - 1) + offset;
  return monthParam(Math.floor(index / 12), (index % 12) + 1);
}

/** "Eylül 2026" */
export function monthLabel(year: number, month: number): string {
  return new Intl.DateTimeFormat("tr-TR", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

/** İşçilik oranının varsayılan başlangıcı: raporlanan ayın ertesi ayının ilk günü. */
export function nextMonthStart(year: number, month: number): string {
  return `${shiftMonth(year, month, 1)}-01`;
}

/** Zammın varsayılan geçerlilik başlangıcı: bu ayın ilk günü. */
export function currentMonthStart(): string {
  return `${today().slice(0, 7)}-01`;
}

/** Geçen ayın ilk günü (işe giriş tarihi bilinmeyen kişinin ilk ücreti için). */
export function previousMonthStart(): string {
  const [year, month] = today().split("-").map(Number);
  return `${shiftMonth(year, month, -1)}-01`;
}

export function stageLabel(stage: CostCenterStage): string {
  return stage ? kt.stage_[stage] : kt.stageGeneral;
}

/** "30.000", "30000", "30.000,50", "30000,5" → "30000", "30000", "30000.50", "30000.5";
 * geçersiz, sıfır ya da 2'den çok ondalıklıysa null. Noktayla gruplanmış binler tanınır. */
export function parseMoney(text: string): string | null {
  const value = text.trim().replace(/\s/g, "");
  const grouped = /^\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(value);
  const normalized = grouped ? value.replace(/\./g, "").replace(",", ".") : normalizeDecimal(value);
  return /^\d+(\.\d{1,2})?$/.test(normalized) && Number(normalized) > 0 ? normalized : null;
}
