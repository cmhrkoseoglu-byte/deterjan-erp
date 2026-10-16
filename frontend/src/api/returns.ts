// /api/v1/returns/* uç noktaları (müşteri iadesi, Faz 3 Adım 3.3).
import { api } from "./client";
import type { LotStatus } from "./inventory";
import type { ListParams } from "./masterdata";
import type { Paginated } from "./types";

export type ReturnStatus = "DRAFT" | "RECEIVED" | "CLOSED" | "CANCELLED";
export type ReturnDisposition = "PENDING" | "RESTOCK" | "REWORK" | "SCRAP";

export interface ReturnLine {
  id?: number;
  line_no?: number;
  product: number;
  product_code?: string;
  product_name?: string;
  lot: number;
  lot_no?: string;
  lot_status?: LotStatus;
  lot_status_display?: string;
  expiry_date?: string | null;
  quantity: string;
  unit: number;
  unit_code?: string;
  base_quantity?: string | null;
  base_unit_code?: string;
  sample?: number | null;
  sample_number?: string | null;
  sample_status?: string | null;
  disposition?: ReturnDisposition;
  disposition_display?: string;
  decided_at?: string | null;
  is_scrapped?: boolean;
  is_settled?: boolean;
}

export interface CustomerReturn {
  id: number;
  number: string;
  status: ReturnStatus;
  status_display: string;
  cancel_reason: string;
  cancelled_at: string | null;
  received_at: string | null;
  received_by_name: string | null;
  closed_at: string | null;
  created_at: string;
  created_by_name: string | null;
  customer: number;
  customer_code: string;
  customer_name: string;
  /** İadenin geldiği sevkiyat (isteğe bağlı): iade o sevkiyatta sevk edilenden fazla olamaz. */
  shipment: number | null;
  shipment_number: string | null;
  return_date: string;
  reason: string;
  quarantine_location: number;
  quarantine_location_code: string;
  note: string;
  line_count: number | null;
}

export interface CustomerReturnDetail extends CustomerReturn {
  lines: ReturnLine[];
}

export interface ReturnPayload {
  customer: number | null;
  shipment: number | null;
  return_date: string;
  reason: string;
  quarantine_location: number | null;
  note: string;
  lines: ReturnLine[];
}

export async function listReturns(params: ListParams = {}): Promise<Paginated<CustomerReturn>> {
  const clean = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
  const { data } = await api.get<Paginated<CustomerReturn>>("/returns/", { params: clean });
  return data;
}

export async function getReturn(id: number): Promise<CustomerReturnDetail> {
  const { data } = await api.get<CustomerReturnDetail>(`/returns/${id}/`);
  return data;
}

export async function saveReturn(
  id: number | null,
  payload: ReturnPayload,
): Promise<CustomerReturnDetail> {
  const { data } = id
    ? await api.patch<CustomerReturnDetail>(`/returns/${id}/`, payload)
    : await api.post<CustomerReturnDetail>("/returns/", payload);
  return data;
}

export async function receiveReturn(id: number): Promise<CustomerReturnDetail> {
  const { data } = await api.post<CustomerReturnDetail>(`/returns/${id}/receive/`);
  return data;
}

export async function cancelReturn(id: number, reason: string): Promise<CustomerReturnDetail> {
  const { data } = await api.post<CustomerReturnDetail>(`/returns/${id}/cancel/`, { reason });
  return data;
}

export async function scrapReturnLine(
  id: number,
  lineId: number,
  note: string,
): Promise<CustomerReturnDetail> {
  const { data } = await api.post<CustomerReturnDetail>(`/returns/${id}/lines/${lineId}/scrap/`, {
    note,
  });
  return data;
}
