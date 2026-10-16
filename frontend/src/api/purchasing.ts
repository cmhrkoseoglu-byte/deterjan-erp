// /api/v1/purchasing/* uç noktaları (Faz 4, Adım 4.2). Miktarlar metin olarak gelir; `base_quantity`,
// teslim alınan ve bekleyen miktarlar malzemenin temel biriminde. Depo rolünde tutar alanları
// (birim fiyat, toplamlar, kur) yanıtta yoktur.
import { api } from "./client";
import type { ListParams } from "./masterdata";
import type { Currency } from "./sales";
import type { Paginated } from "./types";

export type PurchaseOrderStatus =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "SENT"
  | "PARTIALLY_RECEIVED"
  | "RECEIVED"
  | "CANCELLED";
export type PurchaseRequestStatus = "OPEN" | "ORDERED" | "CANCELLED";
export type PurchaseRequestSource = "MANUAL" | "AUTO";

export interface PurchaseRequest {
  id: number;
  number: string;
  status: PurchaseRequestStatus;
  status_display: string;
  source: PurchaseRequestSource;
  source_display: string;
  material: number;
  material_code: string;
  material_name: string;
  unit_code: string;
  quantity: string;
  need_date: string;
  reason: string;
  order_id: number | null;
  order_number: string | null;
  cancel_reason: string;
  cancelled_at: string | null;
  created_at: string;
  created_by: number | null;
  created_by_name: string | null;
}

export interface PurchaseRequestPayload {
  material: number;
  quantity: string;
  need_date: string;
  reason: string;
}

export interface PurchaseOrderLine {
  id?: number;
  line_no?: number;
  material: number;
  material_code?: string;
  material_name?: string;
  quantity: string;
  unit: number;
  unit_code?: string;
  base_quantity?: string;
  base_unit_code?: string;
  unit_price?: string;
  line_total?: string | null;
  expected_date: string;
  note?: string;
  requests?: number[];
  request_numbers?: string[];
  received_quantity?: string | null;
  pending_quantity?: string | null;
}

export interface PurchaseOrder {
  id: number;
  number: string;
  status: PurchaseOrderStatus;
  status_display: string;
  supplier: number;
  supplier_code: string;
  supplier_name: string;
  supplier_email: string;
  order_date: string;
  currency: Currency;
  exchange_rate?: string;
  notes: string;
  total?: string;
  total_try?: string;
  expected_date: string | null;
  approval_total_try?: string | null;
  approval_limit_try?: string | null;
  approved_at: string | null;
  approved_by_name: string | null;
  sent_at: string | null;
  sent_by_name: string | null;
  sent_to: string;
  closed_note: string;
  cancel_reason: string;
  cancelled_at: string | null;
  created_at: string;
  created_by_name: string | null;
}

export interface OrderReceipt {
  id: number;
  number: string;
  status: "DRAFT" | "POSTED" | "CANCELLED";
  receipt_date: string;
}

export interface PurchaseOrderDetail extends PurchaseOrder {
  lines: PurchaseOrderLine[];
  can_approve: boolean;
  receipts: OrderReceipt[];
}

export interface PurchaseOrderPayload {
  supplier: number | null;
  order_date: string;
  currency: Currency;
  exchange_rate: string;
  notes: string;
  lines: PurchaseOrderLine[];
}

export interface ReceivePayload {
  receipt_date: string;
  delivery_note_no: string;
  quarantine_location: number | null;
  storage_location: number | null;
  note: string;
  lines: {
    order_line: number;
    quantity: string;
    supplier_lot_no: string;
    manufactured_at: string | null;
    expiry_date: string | null;
  }[];
}

export interface ExpectedDelivery {
  order_line: number;
  order_id: number;
  order_number: string;
  order_status: PurchaseOrderStatus;
  supplier_id: number;
  supplier_name: string;
  material: number;
  material_code: string;
  material_name: string;
  quantity: string;
  unit_code: string;
  base_unit_code: string;
  base_quantity: string;
  received_quantity: string;
  pending_quantity: string;
  expected_date: string;
  is_late: boolean;
}

export interface Suggestion {
  material: number;
  material_code: string;
  material_name: string;
  unit_code: string;
  demand: string;
  min_stock: string;
  free_stock: string;
  open_orders: string;
  open_requests: string;
  suggested: string;
  need_date: string;
  sources: { order_number: string; planned_date: string; quantity: string }[];
}

export interface SupplierPerformance {
  supplier: number;
  supplier_code: string;
  supplier_name: string;
  due_lines: number;
  on_time_lines: number;
  on_time_rate: string | null;
  received_lots: number;
  rejected_lots: number;
  reject_rate: string | null;
}

export interface PurchasingSettings {
  approval_limit_try: string | null;
  over_receipt_tolerance_pct: string;
  updated_at: string;
  updated_by_name: string | null;
}

export interface ReceiptLink {
  receipt_line: number;
  order_line: number;
  order_id: number;
  order_number: string;
}

const BASE = "/purchasing";
const ORDERS = `${BASE}/orders`;
const REQUESTS = `${BASE}/requests`;

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

function listParams(params: ListParams, statuses: string[]) {
  return {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  };
}

// --- talep ---

export async function listPurchaseRequests(
  params: ListParams = {},
  statuses: PurchaseRequestStatus[] = [],
): Promise<Paginated<PurchaseRequest>> {
  const { data } = await api.get<Paginated<PurchaseRequest>>(
    `${REQUESTS}/`,
    listParams(params, statuses),
  );
  return data;
}

export async function savePurchaseRequest(
  id: number | null,
  payload: PurchaseRequestPayload,
): Promise<PurchaseRequest> {
  const { data } = id
    ? await api.patch<PurchaseRequest>(`${REQUESTS}/${id}/`, payload)
    : await api.post<PurchaseRequest>(`${REQUESTS}/`, payload);
  return data;
}

export async function cancelPurchaseRequest(id: number, reason: string): Promise<PurchaseRequest> {
  const { data } = await api.post<PurchaseRequest>(`${REQUESTS}/${id}/cancel/`, { reason });
  return data;
}

// --- sipariş ---

export async function listPurchaseOrders(
  params: ListParams = {},
  statuses: PurchaseOrderStatus[] = [],
): Promise<Paginated<PurchaseOrder>> {
  const { data } = await api.get<Paginated<PurchaseOrder>>(
    `${ORDERS}/`,
    listParams(params, statuses),
  );
  return data;
}

export async function getPurchaseOrder(id: number): Promise<PurchaseOrderDetail> {
  const { data } = await api.get<PurchaseOrderDetail>(`${ORDERS}/${id}/`);
  return data;
}

export async function savePurchaseOrder(
  id: number | null,
  payload: PurchaseOrderPayload,
): Promise<PurchaseOrderDetail> {
  const { data } = id
    ? await api.patch<PurchaseOrderDetail>(`${ORDERS}/${id}/`, payload)
    : await api.post<PurchaseOrderDetail>(`${ORDERS}/`, payload);
  return data;
}

async function action(id: number, name: string, body: object = {}): Promise<PurchaseOrderDetail> {
  const { data } = await api.post<PurchaseOrderDetail>(`${ORDERS}/${id}/${name}/`, body);
  return data;
}

export const submitPurchaseOrder = (id: number) => action(id, "submit");
export const approvePurchaseOrder = (id: number) => action(id, "approve");
export const returnPurchaseOrder = (id: number, note: string) =>
  action(id, "return-to-draft", { note });
export const sendPurchaseOrder = (id: number, email: string) => action(id, "send", { email });
export const cancelPurchaseOrder = (id: number, reason: string) => action(id, "cancel", { reason });
export const closePurchaseOrder = (id: number, note: string) => action(id, "close", { note });

export async function receivePurchaseOrder(
  id: number,
  payload: ReceivePayload,
): Promise<{ id: number; number: string }> {
  const { data } = await api.post<{ id: number; number: string }>(
    `${ORDERS}/${id}/receive/`,
    payload,
  );
  return data;
}

export function purchaseOrderPdfUrl(id: number): string {
  return `/api/v1${ORDERS}/${id}/pdf/`;
}

// --- okuma ---

export async function listExpectedDeliveries(
  params: { supplier?: number; material?: number } = {},
): Promise<ExpectedDelivery[]> {
  const { data } = await api.get<ExpectedDelivery[]>(`${BASE}/expected-deliveries/`, { params });
  return data;
}

export async function listSuggestions(): Promise<Suggestion[]> {
  const { data } = await api.get<Suggestion[]>(`${BASE}/suggestions/`);
  return data;
}

export async function getSupplierPerformance(params: {
  date_from?: string;
  date_to?: string;
  supplier?: number;
}): Promise<SupplierPerformance[]> {
  const { data } = await api.get<SupplierPerformance[]>(`${BASE}/supplier-performance/`, {
    params: clean(params as ListParams),
  });
  return data;
}

export async function listReceiptLinks(receipt: number): Promise<ReceiptLink[]> {
  const { data } = await api.get<ReceiptLink[]>(`${BASE}/receipt-links/`, {
    params: { receipt },
  });
  return data;
}

export async function getPurchasingSettings(): Promise<PurchasingSettings> {
  const { data } = await api.get<PurchasingSettings>(`${BASE}/settings/`);
  return data;
}

export async function savePurchasingSettings(
  payload: Partial<Pick<PurchasingSettings, "approval_limit_try" | "over_receipt_tolerance_pct">>,
): Promise<PurchasingSettings> {
  const { data } = await api.patch<PurchasingSettings>(`${BASE}/settings/`, payload);
  return data;
}
