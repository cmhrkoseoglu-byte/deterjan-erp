import type { LedgerSide } from "../../api/ledger";
import { formatMoney } from "../../i18n/format";
import { lt } from "./strings";

export const LEDGER_BASE = "/cari-hesaplar";
export const PRICES = "sensitive.prices";

export interface SideConfig {
  slug: "musteriler" | "tedarikciler";
  side: LedgerSide;
  section: "ledger.customers" | "ledger.suppliers";
  label: string;
}

export const SIDES: readonly SideConfig[] = [
  { slug: "musteriler", side: "customers", section: "ledger.customers", label: lt.customers },
  { slug: "tedarikciler", side: "suppliers", section: "ledger.suppliers", label: lt.suppliers },
];

export function sideBySlug(slug: string | undefined): SideConfig | undefined {
  return SIDES.find((item) => item.slug === slug);
}

export const partnerLedgerPath = (slug: string, id: number) => `${LEDGER_BASE}/${slug}/${id}`;

/** Bakiye: tutar, para birimi ve (B) borçlu / (A) alacaklı. */
export function balanceText(value: string | undefined, currency: string): string {
  if (value === undefined) return "";
  const amount = Number(value);
  if (!amount) return formatMoney(0, currency);
  return `${formatMoney(Math.abs(amount), currency)} (${amount > 0 ? "B" : "A"})`;
}
