// /api/v1/sales/* uç noktaları. Miktarlar metin olarak gelir ("720.0000"); `base_quantity` ve
// rezervasyon miktarları mamulün temel biriminde (ADET).
import { api } from "./client";
import type { ListParams } from "./masterdata";
import type { Paginated } from "./types";

export type SalesOrderStatus =
  "DRAFT" | "CONFIRMED" | "PARTIALLY_SHIPPED" | "SHIPPED" | "CLOSED" | "CANCELLED";
export type Currency = "TRY" | "EUR" | "USD";
export type ReservationStatus = "ACTIVE" | "CONSUMED" | "RELEASED";

export interface SalesOrderLine {
  id?: number;
  line_no?: number;
  product: number;
  product_code?: string;
  product_name?: string;
  quantity: string;
  unit: number;
  unit_code?: string;
  base_quantity?: string;
  base_unit_code?: string;
  unit_price?: string | null;
  currency?: Currency | "";
  line_total?: string | null;
  note?: string;
  reserved_quantity?: string | null;
  shipped_quantity?: string | null;
  shortage_quantity?: string | null;
}

export interface SalesOrder {
  id: number;
  number: string;
  status: SalesOrderStatus;
  status_display: string;
  customer: number;
  customer_code: string;
  customer_name: string;
  order_date: string;
  requested_delivery_date: string | null;
  delivery_address: string;
  customer_po_no: string;
  notes: string;
  line_count: number | null;
  has_shortage: boolean | null;
  confirmed_at: string | null;
  confirmed_by_name: string | null;
  closed_at: string | null;
  cancel_reason: string;
  cancelled_at: string | null;
  created_at: string;
  created_by_name: string | null;
}

export interface Reservation {
  id: number;
  line: number | null;
  line_no: number | null;
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  location: number;
  location_code: string;
  quantity: string;
  unit: string;
  status: ReservationStatus;
  status_display: string;
  note: string;
  created_at: string;
  created_by_name: string | null;
  closed_at: string | null;
}

export interface OrderTotal {
  currency: Currency;
  amount: string;
}

export interface SalesOrderDetail extends SalesOrder {
  min_remaining_shelf_life_days: number | null;
  is_editable: boolean;
  lines: SalesOrderLine[];
  totals: OrderTotal[];
  reservations: Reservation[];
}

export interface SalesOrderPayload {
  customer: number | null;
  order_date: string;
  requested_delivery_date: string | null;
  delivery_address: string;
  customer_po_no: string;
  notes: string;
  lines: SalesOrderLine[];
}

export interface ReservationCandidate {
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  location: number;
  location_code: string;
  quantity: string;
  reserved_quantity: string;
  available_quantity: string;
  unit: string;
  meets_shelf_life: boolean;
}

const ORDERS = "/sales/orders";

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

export async function listSalesOrders(
  params: ListParams = {},
  statuses: SalesOrderStatus[] = [],
): Promise<Paginated<SalesOrder>> {
  const { data } = await api.get<Paginated<SalesOrder>>(`${ORDERS}/`, {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function getSalesOrder(id: number): Promise<SalesOrderDetail> {
  const { data } = await api.get<SalesOrderDetail>(`${ORDERS}/${id}/`);
  return data;
}

export async function saveSalesOrder(
  id: number | null,
  payload: SalesOrderPayload,
): Promise<SalesOrderDetail> {
  const { data } = id
    ? await api.patch<SalesOrderDetail>(`${ORDERS}/${id}/`, payload)
    : await api.post<SalesOrderDetail>(`${ORDERS}/`, payload);
  return data;
}

async function action(id: number, name: string, body: object = {}): Promise<SalesOrderDetail> {
  const { data } = await api.post<SalesOrderDetail>(`${ORDERS}/${id}/${name}/`, body);
  return data;
}

export const confirmSalesOrder = (id: number, note = "") => action(id, "confirm", { note });
export const cancelSalesOrder = (id: number, reason: string) => action(id, "cancel", { reason });
export const closeSalesOrder = (id: number, note = "") => action(id, "close", { note });
export const reserveShortages = (id: number) => action(id, "reserve-shortages");
export const reserveLot = (
  id: number,
  body: { line: number; lot: number; location: number; quantity: string; note?: string },
) => action(id, "reserve", body);
export const releaseReservation = (id: number, reservation: number, note = "") =>
  action(id, "release", { reservation, note });

export async function listCandidates(id: number, line: number): Promise<ReservationCandidate[]> {
  const { data } = await api.get<ReservationCandidate[]>(`${ORDERS}/${id}/candidates/`, {
    params: { line },
  });
  return data;
}
