// /api/v1/ledger/* uç noktaları: müşteri ve tedarikçi cari hesapları (docs/plan/cari-hesaplar.md).
// Tutar alanları yalnız "Fiyatları görür" hakkıyla gelir; yoksa yanıtta yoktur (isteğe bağlı).
import axios from "axios";
import { api } from "./client";
import { saveBlob } from "./reporting";
import type { Paginated } from "./types";

export type LedgerSide = "customers" | "suppliers";
export type Currency = "TRY" | "EUR" | "USD";
export type EntryKind =
  | "SALE"
  | "PURCHASE"
  | "COLLECTION"
  | "PAYMENT"
  | "RETURN_CREDIT"
  | "DEBIT_NOTE"
  | "CREDIT_NOTE"
  | "OPENING"
  | "REVERSAL";
export type PaymentMethod = "CASH" | "TRANSFER" | "CHECK" | "NOTE" | "CARD" | "OFFSET" | "OTHER";
export type AgingBucket = "not_due" | "d1_30" | "d31_60" | "d61_90" | "d90_plus";

export interface LedgerPartner {
  id: number;
  code: string;
  name: string;
  payment_term_days: number | null;
  vat_exempt: boolean;
  is_active: boolean;
}

export interface LedgerBalance {
  currency: Currency;
  last_date: string | null;
  debit?: string;
  credit?: string;
  /** Borç − alacak: artı cari borçlu (B), eksi cari alacaklı (A). */
  balance?: string;
  overdue?: string;
  aging?: Record<AgingBucket, string>;
}

export interface PartnerRow {
  partner: LedgerPartner;
  balances: LedgerBalance[];
  /** Tutarı eksik belge sayısı. */
  missing: number;
}

export interface LedgerTotal {
  currency: Currency;
  /** Müşteride alacağımız, tedarikçide borcumuz. */
  open: string;
  advance: string;
  overdue: string;
}

export interface PartnerList extends Paginated<PartnerRow> {
  totals?: LedgerTotal[];
}

export interface LedgerEntry {
  id: number;
  number: string;
  entry_date: string;
  kind: EntryKind;
  kind_display: string;
  currency: Currency;
  debit?: string;
  credit?: string;
  net_amount?: string | null;
  vat_amount?: string | null;
  exchange_rate?: string | null;
  method: PaymentMethod | "";
  method_display: string;
  reference: string;
  description: string;
  shipment: number | null;
  shipment_number: string | null;
  goods_receipt: number | null;
  goods_receipt_number: string | null;
  customer_return: number | null;
  customer_return_number: string | null;
  reversal_of: number | null;
  reversal_of_number: string | null;
  created_by_name: string;
  created_at: string;
}

export interface StatementRow {
  entry: LedgerEntry;
  balance?: string;
  due_date: string | null;
  is_reversed: boolean;
}

export interface StatementCurrency {
  currency: Currency;
  rows: StatementRow[];
  opening?: string;
  total_debit?: string;
  total_credit?: string;
  closing?: string;
}

export interface ReturnInfo {
  id: number;
  number: string;
  return_date: string;
  status: string;
  shipment_number: string | null;
  has_credit: boolean;
}

export interface Statement {
  partner: LedgerPartner;
  date_from: string | null;
  date_to: string | null;
  currencies: StatementCurrency[];
  returns: ReturnInfo[];
}

export interface PartnerSummary {
  partner: LedgerPartner;
  balances: LedgerBalance[];
  missing: number;
}

export interface MissingPrice {
  kind: "shipment" | "goods_receipt";
  line_id: number;
  document_id: number;
  document_number: string;
  document_date: string | null;
  partner: LedgerPartner;
  material_code: string;
  material_name: string;
  quantity: string;
  unit_code: string;
}

export interface ManualEntryPayload {
  kind: EntryKind;
  entry_date: string;
  currency: Currency;
  amount: string;
  direction?: "debit" | "credit" | null;
  method?: PaymentMethod | "";
  reference?: string;
  description?: string;
  exchange_rate?: string | null;
  customer_return?: number | null;
}

export interface PartnerListParams {
  page?: number;
  page_size?: number;
  search?: string;
  with_balance?: boolean;
  overdue?: boolean;
  currency?: Currency | "";
  include_inactive?: boolean;
}

export interface StatementParams {
  date_from?: string;
  date_to?: string;
}

function clean<T extends object>(params: T): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== "" && value !== false && value !== null,
    ),
  );
}

export async function listPartners(
  side: LedgerSide,
  params: PartnerListParams = {},
): Promise<PartnerList> {
  const { data } = await api.get<PartnerList>(`/ledger/${side}/`, { params: clean(params) });
  return data;
}

export async function getPartnerSummary(side: LedgerSide, id: number): Promise<PartnerSummary> {
  const { data } = await api.get<PartnerSummary>(`/ledger/${side}/${id}/`);
  return data;
}

export async function getStatement(
  side: LedgerSide,
  id: number,
  params: StatementParams = {},
): Promise<Statement> {
  const { data } = await api.get<Statement>(`/ledger/${side}/${id}/statement/`, {
    params: clean(params),
  });
  return data;
}

export async function listMissingPrices(
  side: LedgerSide,
  partner?: number,
): Promise<MissingPrice[]> {
  const { data } = await api.get<MissingPrice[]>(`/ledger/${side}/missing-prices/`, {
    params: clean({ partner }),
  });
  return data;
}

export async function postEntry(
  side: LedgerSide,
  id: number,
  payload: ManualEntryPayload,
): Promise<LedgerEntry> {
  const { data } = await api.post<LedgerEntry>(`/ledger/${side}/${id}/entries/`, payload);
  return data;
}

export async function reverseEntry(
  side: LedgerSide,
  id: number,
  entry: number,
  reason: string,
): Promise<LedgerEntry> {
  const { data } = await api.post<LedgerEntry>(`/ledger/${side}/${id}/reverse/`, {
    entry,
    reason,
  });
  return data;
}

export async function setShipmentLinePrice(payload: {
  line: number;
  unit_price: string;
  currency: Currency;
  note?: string;
}): Promise<LedgerEntry[]> {
  const { data } = await api.post<LedgerEntry[]>(
    "/ledger/customers/shipment-line-prices/",
    payload,
  );
  return data;
}

export async function getReturnSuggestion(
  customer: number,
  customerReturn: number,
): Promise<{ currency: Currency; amount: string }[]> {
  const { data } = await api.get<{
    customer_return: number;
    suggestion: { currency: Currency; amount: string }[];
  }>(`/ledger/customers/${customer}/return-suggestion/`, {
    params: { customer_return: customerReturn },
  });
  return data.suggestion;
}

function fileNameFrom(disposition: string | undefined, fallback: string): string {
  const match = disposition?.match(/filename="?([^"]+)"?/);
  return match ? match[1] : fallback;
}

/** Excel / PDF çıktısını indirir; hata gövdesi JSON'a çevrilir (Türkçe mesaj okunsun). */
async function download(url: string, params: object, fallback: string): Promise<void> {
  try {
    const response = await api.get<Blob>(url, { params: clean(params), responseType: "blob" });
    saveBlob(
      response.data,
      fileNameFrom(response.headers["content-disposition"] as string | undefined, fallback),
    );
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
      try {
        error.response.data = JSON.parse(await error.response.data.text());
      } catch {
        // JSON değilse olduğu gibi bırakılır.
      }
    }
    throw error;
  }
}

export function downloadPartners(side: LedgerSide, params: PartnerListParams): Promise<void> {
  return download(`/ledger/${side}/export-xlsx/`, params, "cariler.xlsx");
}

export function downloadStatement(
  side: LedgerSide,
  id: number,
  format: "xlsx" | "pdf",
  params: StatementParams,
): Promise<void> {
  return download(`/ledger/${side}/${id}/statement-${format}/`, params, `ekstre.${format}`);
}
