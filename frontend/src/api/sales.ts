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
  /** Açık (sevk edilmemiş) sevkiyatlarda planlanan miktar (temel birim). */
  planned_quantity?: string | null;
  /** Yeni sevkiyata alınabilecek miktar: sipariş − sevk edilen − planlanan. */
  plannable_quantity?: string | null;
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
  shipments: Shipment[];
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

// --- Sevkiyat (Adım 3.2) ---------------------------------------------------------------------
// Şoför TC kimlik no yalnızca yazılır; okurken maskeli gelir (`driver_id_no_masked`). Tam numara
// yalnızca irsaliye PDF'inde yer alır.

export type ShipmentStatus = "PLANNED" | "PICKING" | "LOADED" | "DISPATCHED" | "CANCELLED";

export interface Shipment {
  id: number;
  number: string;
  status: ShipmentStatus;
  status_display: string;
  sales_order: number;
  order_number: string;
  customer: number;
  customer_code: string;
  customer_name: string;
  planned_date: string;
  loading_location: number;
  loading_location_code: string;
  vehicle_plate: string;
  driver_name: string;
  driver_id_no_masked: string;
  carrier: string;
  notes: string;
  loaded_at: string | null;
  loaded_by_name: string | null;
  dispatched_at: string | null;
  dispatched_by_name: string | null;
  cancel_reason: string;
  cancelled_at: string | null;
  created_at: string;
  created_by_name: string | null;
}

export interface ShipmentLine {
  id: number;
  order_line: number;
  line_no: number;
  product: number;
  product_code: string;
  product_name: string;
  quantity: string;
  unit: string;
  picked_quantity: string | null;
}

export interface ShipmentPick {
  id: number;
  line: number;
  line_no: number;
  product_code: string;
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  quantity: string;
  from_location_code: string;
  to_location_code: string;
  picked_by_name: string | null;
  picked_at: string;
  deviation_reason: string;
  returned_at: string | null;
  is_shipped: boolean;
}

export interface ShipmentDetail extends Shipment {
  delivery_address: string;
  min_remaining_shelf_life_days: number | null;
  lines: ShipmentLine[];
  picks: ShipmentPick[];
}

/** Sevkiyat başlığı (planlama ve güncelleme). `driver_id_no` boş bırakılırsa değişmez. */
export interface ShipmentHeaderPayload {
  planned_date: string;
  vehicle_plate: string;
  driver_name: string;
  driver_id_no?: string;
  carrier: string;
  notes: string;
}

export interface ShipmentPlanPayload extends ShipmentHeaderPayload {
  sales_order: number;
  lines?: { order_line: number; quantity: string }[];
}

export interface PickSuggestionRow {
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  location: number;
  location_code: string;
  quantity: string;
  reserved: boolean;
  meets_shelf_life: boolean;
}

export interface PickSuggestion {
  line: number;
  line_no: number;
  product: number;
  product_code: string;
  product_name: string;
  unit: string;
  quantity: string;
  picked_quantity: string;
  remaining_quantity: string;
  suggestions: PickSuggestionRow[];
}

export interface PickPayload {
  lot?: number;
  lot_no?: string;
  quantity?: string | null;
  reason?: string;
}

export interface ShippedLot {
  id: number;
  shipment: number;
  shipment_number: string;
  order_number: string;
  dispatched_at: string | null;
  product_code: string;
  product_name: string;
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  quantity: string;
}

const SHIPMENTS = "/sales/shipments";

export async function listShipments(
  params: ListParams = {},
  statuses: ShipmentStatus[] = [],
): Promise<Paginated<Shipment>> {
  const { data } = await api.get<Paginated<Shipment>>(`${SHIPMENTS}/`, {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function getShipment(id: number): Promise<ShipmentDetail> {
  const { data } = await api.get<ShipmentDetail>(`${SHIPMENTS}/${id}/`);
  return data;
}

export async function planShipment(payload: ShipmentPlanPayload): Promise<ShipmentDetail> {
  const { data } = await api.post<ShipmentDetail>(`${SHIPMENTS}/`, payload);
  return data;
}

export async function updateShipment(
  id: number,
  payload: Partial<ShipmentHeaderPayload>,
): Promise<ShipmentDetail> {
  const { data } = await api.patch<ShipmentDetail>(`${SHIPMENTS}/${id}/`, payload);
  return data;
}

async function shipmentAction(
  id: number,
  name: string,
  body: object = {},
): Promise<ShipmentDetail> {
  const { data } = await api.post<ShipmentDetail>(`${SHIPMENTS}/${id}/${name}/`, body);
  return data;
}

export const pickLot = (id: number, body: PickPayload) => shipmentAction(id, "pick", body);
export const undoPick = (id: number, pick: number) => shipmentAction(id, "undo-pick", { pick });
export const loadShipment = (id: number) => shipmentAction(id, "load");
export const dispatchShipment = (id: number) => shipmentAction(id, "dispatch");
export const cancelShipment = (id: number, reason: string) =>
  shipmentAction(id, "cancel", { reason });

export async function shipmentSuggestions(id: number): Promise<PickSuggestion[]> {
  const { data } = await api.get<PickSuggestion[]>(`${SHIPMENTS}/${id}/suggestions/`);
  return data;
}

/** İrsaliye PDF'i (oturumla aynı origin'den açılır). */
export function waybillPdfUrl(id: number): string {
  return `/api/v1${SHIPMENTS}/${id}/waybill.pdf`;
}

export async function listShippedLots(customer: number): Promise<Paginated<ShippedLot>> {
  const { data } = await api.get<Paginated<ShippedLot>>("/sales/shipped-lots/", {
    params: { customer, page_size: 200 },
  });
  return data;
}
