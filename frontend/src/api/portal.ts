// /api/v1/portal/* uç noktaları: müşteri ve tedarikçi portalı ile admin'in portal hesapları
// (docs/plan/musteri-siparis-takibi.md §4). Miktarlar metin olarak gelir ("24.0000").
import axios from "axios";
import { api } from "./client";
import { saveBlob } from "./reporting";
import type { Paginated } from "./types";

export type PortalKind = "customer" | "supplier";

export interface PortalMe {
  kind: PortalKind;
  firm_code: string;
  firm_name: string;
}

export interface Money {
  currency: string;
  amount: string;
}

// --- müşteri ------------------------------------------------------------------------------

export interface PortalOrderLine {
  line_no: number;
  product_code: string;
  product_name: string;
  quantity: string;
  unit_code: string;
  base_quantity: string;
  base_unit_code: string;
  shipped_quantity: string;
  remaining_quantity: string;
  shipped_in_unit: string;
  remaining_in_unit: string;
  unit_price: string | null;
  currency: string;
  line_total: string | null;
}

export interface PortalOrder {
  id: number;
  number: string;
  customer_po_no: string;
  order_date: string;
  requested_delivery_date: string | null;
  promised_date: string | null;
  due_date: string | null;
  status: string;
  status_display: string;
  delivery_address: string;
  lines: PortalOrderLine[];
  totals: Money[];
}

export interface PortalShipmentLine {
  line_no: number;
  product_code: string;
  product_name: string;
  quantity: string;
  base_unit_code: string;
  quantity_in_unit: string;
  unit_code: string;
}

export interface PortalShipment {
  id: number;
  number: string;
  status: string;
  status_display: string;
  order_id: number;
  order_number: string;
  customer_po_no: string;
  planned_date: string;
  dispatched_at: string | null;
  vehicle_plate: string;
  carrier: string;
  has_waybill: boolean;
  lines?: PortalShipmentLine[];
}

// --- tedarikçi ----------------------------------------------------------------------------

export interface SupplierOrderLine {
  line_no: number;
  material_code: string;
  material_name: string;
  quantity: string;
  unit_code: string;
  base_quantity: string;
  base_unit_code: string;
  unit_price: string;
  line_total: string;
  expected_date: string;
  received_quantity: string;
  remaining_quantity: string;
  received_in_unit: string;
  remaining_in_unit: string;
}

export interface SupplierOrder {
  id: number;
  number: string;
  order_date: string;
  sent_at: string | null;
  currency: string;
  status: string;
  status_display: string;
  notes: string;
  lines: SupplierOrderLine[];
  total: string;
}

export interface ReceiptLine {
  line_no: number;
  material_code: string;
  material_name: string;
  quantity: string;
  unit_code: string;
  supplier_lot_no: string;
  order_number: string | null;
}

export interface Receipt {
  id: number;
  number: string;
  receipt_date: string;
  delivery_note_no: string;
  lines: ReceiptLine[];
}

// --- cari ---------------------------------------------------------------------------------

export type AgingBucket = "not_due" | "d1_30" | "d31_60" | "d61_90" | "d90_plus";

export interface PortalBalance {
  currency: string;
  debit: string;
  credit: string;
  /** Borç − alacak: artı firma borçlu (B), eksi alacaklı (A). */
  balance: string;
  overdue: string;
  last_date: string | null;
  aging: Record<AgingBucket, string>;
}

export interface StatementRow {
  number: string;
  entry_date: string;
  kind_display: string;
  document: string;
  description: string;
  debit: string;
  credit: string;
  balance: string;
  due_date: string | null;
  is_reversed: boolean;
}

export interface StatementCurrency {
  currency: string;
  opening: string;
  rows: StatementRow[];
  total_debit: string;
  total_credit: string;
  closing: string;
}

export interface PortalStatement {
  date_from: string | null;
  date_to: string | null;
  currencies: StatementCurrency[];
}

export interface StatementParams {
  date_from?: string;
  date_to?: string;
}

export interface ListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: string;
  sales_order?: number;
}

function clean<T extends object>(params: T): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== "" && value !== null,
    ),
  );
}

const BASE = "/portal";
const side = (kind: PortalKind) => `${BASE}/${kind}`;

export async function fetchPortalMe(): Promise<PortalMe> {
  const { data } = await api.get<PortalMe>(`${BASE}/me/`);
  return data;
}

export async function listCustomerOrders(params: ListParams = {}): Promise<Paginated<PortalOrder>> {
  const { data } = await api.get<Paginated<PortalOrder>>(`${side("customer")}/orders/`, {
    params: clean(params),
  });
  return data;
}

export async function getCustomerOrder(id: number): Promise<PortalOrder> {
  const { data } = await api.get<PortalOrder>(`${side("customer")}/orders/${id}/`);
  return data;
}

export async function listCustomerShipments(
  params: ListParams = {},
): Promise<Paginated<PortalShipment>> {
  const { data } = await api.get<Paginated<PortalShipment>>(`${side("customer")}/shipments/`, {
    params: clean(params),
  });
  return data;
}

export async function getCustomerShipment(id: number): Promise<PortalShipment> {
  const { data } = await api.get<PortalShipment>(`${side("customer")}/shipments/${id}/`);
  return data;
}

export async function listSupplierOrders(
  params: ListParams = {},
): Promise<Paginated<SupplierOrder>> {
  const { data } = await api.get<Paginated<SupplierOrder>>(`${side("supplier")}/orders/`, {
    params: clean(params),
  });
  return data;
}

export async function getSupplierOrder(id: number): Promise<SupplierOrder> {
  const { data } = await api.get<SupplierOrder>(`${side("supplier")}/orders/${id}/`);
  return data;
}

export async function listReceipts(params: ListParams = {}): Promise<Paginated<Receipt>> {
  const { data } = await api.get<Paginated<Receipt>>(`${side("supplier")}/receipts/`, {
    params: clean(params),
  });
  return data;
}

export async function getReceipt(id: number): Promise<Receipt> {
  const { data } = await api.get<Receipt>(`${side("supplier")}/receipts/${id}/`);
  return data;
}

export async function fetchBalances(kind: PortalKind): Promise<PortalBalance[]> {
  const { data } = await api.get<PortalBalance[]>(`${side(kind)}/ledger/`);
  return data;
}

export async function fetchStatement(
  kind: PortalKind,
  params: StatementParams,
): Promise<PortalStatement> {
  const { data } = await api.get<PortalStatement>(`${side(kind)}/ledger/statement/`, {
    params: clean(params),
  });
  return data;
}

function fileNameFrom(disposition: string | undefined, fallback: string): string {
  const match = disposition?.match(/filename="?([^"]+)"?/);
  return match ? match[1] : fallback;
}

/** PDF'i indirir; hata gövdesi JSON'a çevrilir (Türkçe mesaj okunsun). */
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

export function downloadWaybill(shipment: PortalShipment): Promise<void> {
  return download(
    `${side("customer")}/shipments/${shipment.id}/waybill-pdf/`,
    {},
    `irsaliye-${shipment.number}.pdf`,
  );
}

export function downloadSupplierOrder(order: SupplierOrder): Promise<void> {
  return download(`${side("supplier")}/orders/${order.id}/pdf/`, {}, `${order.number}.pdf`);
}

export function downloadStatementPdf(kind: PortalKind, params: StatementParams): Promise<void> {
  return download(`${side(kind)}/ledger/statement-pdf/`, params, "ekstre.pdf");
}

// --- admin: portal hesapları -------------------------------------------------------------

export interface PortalAccount {
  id: number;
  kind: PortalKind;
  username: string;
  full_name: string;
  email: string;
  phone: string;
  is_active: boolean;
  last_login: string | null;
  password_change_required: boolean;
  firm_id: number;
  firm_code: string;
  firm_name: string;
  firm_is_active: boolean;
  created_at: string;
}

export interface PortalAccountPayload {
  username: string;
  full_name: string;
  email?: string;
  phone?: string;
  customer?: number | null;
  supplier?: number | null;
}

export interface IssuedAccountPassword {
  account: PortalAccount;
  temporary_password: string;
}

export interface AccountFilters {
  page?: number;
  search?: string;
  kind?: PortalKind | "";
}

const ACCOUNTS = `${BASE}/accounts`;

export async function listPortalAccounts(
  params: AccountFilters = {},
): Promise<Paginated<PortalAccount>> {
  const { data } = await api.get<Paginated<PortalAccount>>(`${ACCOUNTS}/`, {
    params: clean(params),
  });
  return data;
}

export async function createPortalAccount(
  payload: PortalAccountPayload,
): Promise<IssuedAccountPassword> {
  const { data } = await api.post<IssuedAccountPassword>(`${ACCOUNTS}/`, payload);
  return data;
}

export async function resetPortalPassword(id: number): Promise<IssuedAccountPassword> {
  const { data } = await api.post<IssuedAccountPassword>(`${ACCOUNTS}/${id}/reset-password/`);
  return data;
}

export async function setPortalAccountActive(id: number, active: boolean): Promise<PortalAccount> {
  const { data } = await api.post<PortalAccount>(
    `${ACCOUNTS}/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

export async function unlockPortalAccount(id: number): Promise<PortalAccount> {
  const { data } = await api.post<PortalAccount>(`${ACCOUNTS}/${id}/unlock/`);
  return data;
}

// --- sipariş talebi (docs/plan/musteri-siparis-takibi.md §4.4) ---------------------------

export type RequestStatus = "SUBMITTED" | "CONVERTED" | "REJECTED" | "WITHDRAWN";

export interface RequestLine {
  line_no: number;
  product: number;
  product_code: string;
  product_name: string;
  quantity: string;
  unit: number;
  unit_code: string;
}

export interface OrderRequest {
  id: number;
  number: string;
  status: RequestStatus;
  status_display: string;
  requested_delivery_date: string | null;
  customer_po_no: string;
  delivery_address: string;
  note: string;
  lines: RequestLine[];
  reject_reason: string;
  /** Sipariş onaylanınca dolu (Siparişlerim'de açılır). */
  order_id: number | null;
  order_number: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface StaffOrderRequest extends OrderRequest {
  customer: number;
  customer_code: string;
  customer_name: string;
  created_by_name: string;
  decided_by_name: string;
  /** Çevrildiği satış siparişi (taslak olsa da). */
  sales_order: number | null;
}

export interface OrderableProduct {
  id: number;
  code: string;
  name: string;
  units: { id: number; code: string; name: string }[];
}

export interface RequestPayload {
  requested_delivery_date: string | null;
  customer_po_no: string;
  delivery_address: string;
  note: string;
  lines: { product: number; quantity: string; unit: number }[];
}

const CUSTOMER_REQUESTS = `${BASE}/customer/requests`;
const STAFF_REQUESTS = `${BASE}/requests`;

export async function listOrderableProducts(): Promise<OrderableProduct[]> {
  const { data } = await api.get<Paginated<OrderableProduct>>(`${BASE}/customer/products/`, {
    params: { page_size: 500 },
  });
  return data.results;
}

export async function listRequests(params: ListParams = {}): Promise<Paginated<OrderRequest>> {
  const { data } = await api.get<Paginated<OrderRequest>>(`${CUSTOMER_REQUESTS}/`, {
    params: clean(params),
  });
  return data;
}

export async function getRequest(id: number): Promise<OrderRequest> {
  const { data } = await api.get<OrderRequest>(`${CUSTOMER_REQUESTS}/${id}/`);
  return data;
}

export async function createRequest(payload: RequestPayload): Promise<OrderRequest> {
  const { data } = await api.post<OrderRequest>(`${CUSTOMER_REQUESTS}/`, payload);
  return data;
}

export async function withdrawRequest(id: number): Promise<OrderRequest> {
  const { data } = await api.post<OrderRequest>(`${CUSTOMER_REQUESTS}/${id}/withdraw/`);
  return data;
}

export async function listStaffRequests(
  params: ListParams = {},
): Promise<Paginated<StaffOrderRequest>> {
  const { data } = await api.get<Paginated<StaffOrderRequest>>(`${STAFF_REQUESTS}/`, {
    params: clean(params),
  });
  return data;
}

export async function getStaffRequest(id: number): Promise<StaffOrderRequest> {
  const { data } = await api.get<StaffOrderRequest>(`${STAFF_REQUESTS}/${id}/`);
  return data;
}

export async function convertRequest(id: number): Promise<StaffOrderRequest> {
  const { data } = await api.post<StaffOrderRequest>(`${STAFF_REQUESTS}/${id}/convert/`);
  return data;
}

export async function rejectRequest(id: number, reason: string): Promise<StaffOrderRequest> {
  const { data } = await api.post<StaffOrderRequest>(`${STAFF_REQUESTS}/${id}/reject/`, {
    reason,
  });
  return data;
}
