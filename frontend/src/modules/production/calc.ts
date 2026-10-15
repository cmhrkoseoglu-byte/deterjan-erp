import type { LineState } from "../../api/production";

const num = (value: string | number | null | undefined) => {
  const n = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
};

/** Plana göre sapma yüzdesi (işaretli, 2 ondalık). Backend `services.deviation_pct` ile aynı. */
export function deviationPct(planned: string | number, actual: string | number): number {
  const p = num(planned);
  if (p === 0) return 0;
  return Math.round(((num(actual) - p) / p) * 10000) / 100;
}

/** Satır durumu: tartılmadı / eksik / tolerans içinde / fazla. */
export function lineState(
  planned: string | number,
  actual: string | number,
  tolerancePct: string | number,
): LineState {
  if (num(actual) === 0) return "pending";
  const pct = deviationPct(planned, actual);
  const tolerance = num(tolerancePct);
  if (pct > tolerance) return "over";
  if (pct < -tolerance) return "under";
  return "ok";
}

/** Satırı tolerans içinde tamamlamak için kalan miktar (negatifse sıfır). */
export function remaining(planned: string | number, actual: string | number): number {
  return Math.max(0, Math.round((num(planned) - num(actual)) * 10000) / 10000);
}

/** Gösterge çubuğu doluluğu (%): planın %0–120 aralığı 0–100'e oturtulur. */
export function gaugeValue(planned: string | number, actual: string | number): number {
  const p = num(planned);
  if (p === 0) return 0;
  return Math.min(100, (num(actual) / p / 1.2) * 100);
}
