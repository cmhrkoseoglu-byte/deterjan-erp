// Ön bordro ekran yardımcıları: kalem adları, ay karşılaştırması, devir önerisi.
import type {
  PayrollEmployee,
  PayrollItemCategory,
  PayrollItemRecord,
  PayrollMonth,
  PayrollRow,
} from "../../api/payroll";
import { DEDUCTION_CATEGORIES, EXTRA_CATEGORIES } from "../../api/payroll";
import { today } from "../inventory/config";
import { pa, pn, py } from "./strings";

export const CATEGORY_LABELS: Record<PayrollItemCategory, string> = {
  PREMIUM: "Prim",
  BONUS: "İkramiye",
  TRAVEL: "Yol (nakit)",
  MEAL: "Yemek (nakit)",
  OTHER_EXTRA: "Diğer ek ödeme",
  ADVANCE: "Avans",
  GARNISHMENT: "İcra / nafaka",
  OTHER_DEDUCTION: "Diğer kesinti",
};

/** Kalemin adı ve açıklaması: "İcra / nafaka (2026/1234 E.)". */
export function itemLabel(item: PayrollItemRecord): string {
  const name = CATEGORY_LABELS[item.category];
  return item.description ? `${name} (${item.description})` : name;
}

/** Kalem seçimi: türe göre gruplu (yalnızca bir tür istenebilir: düzeltmede tür değişmez). */
export function categoryOptions(kind?: "EXTRA" | "DEDUCTION") {
  const groups = [
    { group: pn.groupExtra, kind: "EXTRA", codes: EXTRA_CATEGORIES },
    { group: pn.groupDeduction, kind: "DEDUCTION", codes: DEDUCTION_CATEGORIES },
  ];
  return groups
    .filter((item) => !kind || item.kind === kind)
    .map((item) => ({
      group: item.group,
      items: item.codes.map((code) => ({ value: code, label: CATEGORY_LABELS[code] })),
    }));
}

/** Ay bugünün ayından önce mi (değişiklik sonraki ayların kümülatifini de değiştirir)? */
export function isPastMonth(year: number, month: number): boolean {
  const [currentYear, currentMonth] = today().split("-").map(Number);
  return year * 12 + month < currentYear * 12 + currentMonth;
}

/** Ay bugünün ayından sonra mı (gelecek aya ek ödeme ve kesinti girilmez; sunucuyla aynı kural)? */
export function isFutureMonth(year: number, month: number): boolean {
  const [currentYear, currentMonth] = today().split("-").map(Number);
  return year * 12 + month > currentYear * 12 + currentMonth;
}

/** Kişinin bu yıl `month` ayından önce bu işyerinde işte olduğu ay sayısı (işe giriş ayı tam;
 * sunucudaki kuralla aynı): devirde istisna ay sayısının önerisi ve üst sınırı. */
export function monthsEmployedBefore(
  employee: PayrollEmployee,
  year: number,
  month: number,
): number {
  const hire = employee.hire_date;
  const hireYear = hire ? Number(hire.slice(0, 4)) : null;
  if (hireYear !== null && hireYear > year) return 0;
  const first = hire && hireYear === year ? Number(hire.slice(5, 7)) : 1;
  return Math.max(0, month - first);
}

/** Satırın bütün uyarı adları (2. ve 3. adım uyarıları). */
export function warningLabel(code: string): string {
  return pn.warning[code] ?? py.warning[code] ?? code;
}

export function warningHelp(code: string): string | undefined {
  return pn.warningHelp[code] ?? py.warningHelp[code];
}

/** Ayın bütün etkin kalemleri (kişi satırlarındakiler ve işte olmayanlara girilenler). */
export function monthItems(rows: PayrollRow[], orphans: PayrollItemRecord[]): PayrollItemRecord[] {
  return [...rows.flatMap((row) => row.items), ...orphans];
}

/** Bordrosu mali müşavirde olan kişilere girilmiş kalemler: ERP bordrosunda hesaplanmaz. */
export function externalItems(rows: PayrollRow[]): PayrollItemRecord[] {
  return rows.filter((row) => row.external).flatMap((row) => row.items);
}

/** Devri eksik kişilerin giriş ayları ve sayıları (ay sırasıyla). */
export function missingOpenings(payroll: PayrollMonth): [month: number, count: number][] {
  const counts = new Map<number, number>();
  for (const row of payroll.rows)
    if (!row.external && row.opening_needed && row.entry_month !== null)
      counts.set(row.entry_month, (counts.get(row.entry_month) ?? 0) + 1);
  return [...counts.entries()].sort(([a], [b]) => a - b);
}

/** Kaydedildikten sonra parametreleri değişen devirlerin ayları ve kişi sayıları (zincirin
 * çapası olan devirler; ay sırasıyla). */
export function staleOpenings(payroll: PayrollMonth): [month: number, count: number][] {
  const counts = new Map<number, number>();
  for (const row of payroll.rows) {
    if (row.external) continue;
    for (const link of row.carry_months)
      if (link.kind === "opening" && link.flags.includes("opening_stale"))
        counts.set(link.month, (counts.get(link.month) ?? 0) + 1);
  }
  return [...counts.entries()].sort(([a], [b]) => a - b);
}

/** Devir ayı: devri eksik kişilerin en erken giriş ayı; yoksa bu ay. */
export function openingTarget(payroll: PayrollMonth): number {
  const missing = missingOpenings(payroll);
  return missing.length ? missing[0][0] : payroll.month;
}

// Ödeme tarihi en geç bordro ayından üç ay sonrasının son günü (sunucuyla aynı kural); ay sonundan
// 20 günden sonrası uyarılır.
const PAYMENT_MONTHS_AFTER = 3;
const LATE_PAYMENT_DAYS = 20;

const iso = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

/** Ödeme tarihinin sınırları: ayın ilk günü, üç ay sonrasının son günü ve "geç" eşiği. */
export function paymentBounds(year: number, month: number) {
  const first = new Date(year, month - 1, 1);
  const last = new Date(year, month - 1 + PAYMENT_MONTHS_AFTER + 1, 0);
  const late = new Date(year, month, LATE_PAYMENT_DAYS);
  return { first: iso(first), last: iso(last), late: iso(late) };
}

/** Onay denetiminin adı (ay düzeyi denetimler ya da satır uyarısı). */
export function gateLabel(code: string): string {
  return pa.gate[code] ?? warningLabel(code);
}
