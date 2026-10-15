// /api/v1/inventory/* uç noktaları. Miktarlar malzemenin temel biriminde, metin olarak gelir.
import { api } from "./client";
import type { ImportReport, ListParams, MaterialType } from "./masterdata";
import type { Paginated } from "./types";

export type LotStatus = "QUARANTINE" | "RELEASED" | "REJECTED" | "BLOCKED";
export type LotSource = "PURCHASE" | "PRODUCTION" | "FILLING" | "OPENING" | "RETURN";
export type DocumentStatus = "DRAFT" | "POSTED" | "CANCELLED";
export type TraceDirection = "backward" | "forward";

export interface Lot {
  id: number;
  lot_no: string;
  material: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  status: LotStatus;
  status_display: string;
  source: LotSource;
  source_display: string;
  supplier: number | null;
  supplier_name: string | null;
  supplier_lot_no: string;
  manufactured_at: string | null;
  expiry_date: string | null;
  is_expired: boolean;
  released_by_name: string | null;
  released_at: string | null;
  status_note: string;
  total_quantity: string | null;
  allowed_transitions: LotStatus[];
  created_at: string;
}

export interface LotBalance {
  location: number;
  location_code: string;
  location_name: string;
  location_type: string;
  quantity: string;
}

export interface LotDetail extends Lot {
  balances: LotBalance[];
  receipt: { model: string; id: number; number: string } | null;
}

export interface TraceNode {
  id: number;
  lot_no: string;
  status: LotStatus;
  status_display: string;
  lot_source: LotSource;
  lot_source_display: string;
  material_id: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  expiry_date: string | null;
  quantity: string | null;
  children: TraceNode[];
}

export interface StockMovement {
  id: number;
  movement_type: string;
  movement_type_display: string;
  material: number;
  material_code: string;
  material_name: string;
  lot: number;
  lot_no: string;
  location: number;
  location_code: string;
  quantity: string;
  unit: string;
  document_number: string;
  source_model: string | null;
  source_object_id: number | null;
  reversal_of: number | null;
  is_reversed: boolean;
  transfer_group: string | null;
  note: string;
  created_at: string;
  created_by_name: string | null;
}

export interface StockBalance {
  id: number;
  material: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  lot: number;
  lot_no: string;
  lot_status: LotStatus;
  lot_status_display: string;
  expiry_date: string | null;
  location: number;
  location_code: string;
  location_name: string;
  location_type: string;
  warehouse_code: string;
  quantity: string;
  unit: string;
}

interface DocumentBase {
  id: number;
  number: string;
  status: DocumentStatus;
  status_display: string;
  cancel_reason: string;
  cancelled_at: string | null;
  posted_at: string | null;
  posted_by_name: string | null;
  created_at: string;
  created_by_name: string | null;
  note: string;
  line_count: number | null;
}

export interface GoodsReceiptLine {
  id?: number;
  line_no?: number;
  material: number;
  material_code?: string;
  material_name?: string;
  requires_incoming_qc?: boolean;
  quantity: string;
  unit: number;
  unit_code?: string;
  supplier_lot_no: string;
  manufactured_at: string | null;
  expiry_date: string | null;
  unit_price: string | null;
  base_quantity?: string | null;
  base_unit_code?: string;
  created_lot?: number | null;
  created_lot_no?: string | null;
  created_lot_status?: LotStatus | null;
}

export interface GoodsReceipt extends DocumentBase {
  supplier: number;
  supplier_code: string;
  supplier_name: string;
  receipt_date: string;
  delivery_note_no: string;
  quarantine_location: number | null;
  quarantine_location_code: string | null;
  storage_location: number | null;
  storage_location_code: string | null;
}

export interface GoodsReceiptDetail extends GoodsReceipt {
  lines: GoodsReceiptLine[];
}

export interface GoodsReceiptPayload {
  supplier: number | null;
  receipt_date: string;
  delivery_note_no: string;
  quarantine_location: number | null;
  storage_location: number | null;
  note: string;
  lines: GoodsReceiptLine[];
}

export interface AdjustmentLine {
  id?: number;
  line_no?: number;
  lot: number;
  lot_no?: string;
  material_code?: string;
  material_name?: string;
  unit?: string;
  location: number;
  location_code?: string;
  system_quantity?: string;
  counted_quantity: string;
  difference?: string;
  reason: string;
  movement?: number | null;
}

export interface StockAdjustment extends DocumentBase {
  adjustment_date: string;
}

export interface StockAdjustmentDetail extends StockAdjustment {
  lines: AdjustmentLine[];
}

export interface AdjustmentPayload {
  adjustment_date: string;
  note: string;
  lines: AdjustmentLine[];
}

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

async function list<T>(path: string, params: ListParams): Promise<Paginated<T>> {
  const { data } = await api.get<Paginated<T>>(`/inventory/${path}/`, { params: clean(params) });
  return data;
}

// --- lot -----------------------------------------------------------------------------------

export function listLots(params: ListParams = {}): Promise<Paginated<Lot>> {
  return list<Lot>("lots", params);
}

export async function getLot(id: number): Promise<LotDetail> {
  const { data } = await api.get<LotDetail>(`/inventory/lots/${id}/`);
  return data;
}

export async function releaseLot(
  id: number,
  note: string,
  toLocation: number | null,
): Promise<LotDetail> {
  const { data } = await api.post<LotDetail>(`/inventory/lots/${id}/release/`, {
    note,
    to_location: toLocation,
  });
  return data;
}

export async function rejectLot(id: number, note: string): Promise<LotDetail> {
  const { data } = await api.post<LotDetail>(`/inventory/lots/${id}/reject/`, { note });
  return data;
}

export async function blockLot(id: number, note: string): Promise<LotDetail> {
  const { data } = await api.post<LotDetail>(`/inventory/lots/${id}/block/`, { note });
  return data;
}

export async function getLotTrace(id: number, direction: TraceDirection): Promise<TraceNode> {
  const { data } = await api.get<TraceNode>(`/inventory/lots/${id}/trace/`, {
    params: { direction },
  });
  return data;
}

export function lotLabelUrl(id: number): string {
  return `/api/v1/inventory/lots/${id}/label/`;
}

// --- hareket, bakiye, transfer -------------------------------------------------------------

export function listMovements(params: ListParams = {}): Promise<Paginated<StockMovement>> {
  return list<StockMovement>("movements", params);
}

export async function reverseMovement(id: number, reason: string): Promise<StockMovement[]> {
  const { data } = await api.post<StockMovement[]>(`/inventory/movements/${id}/reverse/`, {
    reason,
  });
  return data;
}

export function listBalances(params: ListParams = {}): Promise<Paginated<StockBalance>> {
  return list<StockBalance>("balances", params);
}

export async function transferLot(payload: {
  lot: number;
  from_location: number;
  to_location: number;
  quantity: string;
  note: string;
}): Promise<StockMovement[]> {
  const { data } = await api.post<StockMovement[]>("/inventory/transfers/", payload);
  return data;
}

// --- mal kabul -----------------------------------------------------------------------------

export function listGoodsReceipts(params: ListParams = {}): Promise<Paginated<GoodsReceipt>> {
  return list<GoodsReceipt>("goods-receipts", params);
}

export async function getGoodsReceipt(id: number): Promise<GoodsReceiptDetail> {
  const { data } = await api.get<GoodsReceiptDetail>(`/inventory/goods-receipts/${id}/`);
  return data;
}

export async function saveGoodsReceipt(
  id: number | null,
  payload: GoodsReceiptPayload,
): Promise<GoodsReceiptDetail> {
  const { data } = id
    ? await api.patch<GoodsReceiptDetail>(`/inventory/goods-receipts/${id}/`, payload)
    : await api.post<GoodsReceiptDetail>("/inventory/goods-receipts/", payload);
  return data;
}

export async function postGoodsReceipt(id: number): Promise<GoodsReceiptDetail> {
  const { data } = await api.post<GoodsReceiptDetail>(`/inventory/goods-receipts/${id}/post/`);
  return data;
}

export async function cancelGoodsReceipt(id: number, reason: string): Promise<GoodsReceiptDetail> {
  const { data } = await api.post<GoodsReceiptDetail>(`/inventory/goods-receipts/${id}/cancel/`, {
    reason,
  });
  return data;
}

export function receiptLabelsUrl(id: number): string {
  return `/api/v1/inventory/goods-receipts/${id}/labels/`;
}

// --- sayım düzeltme ------------------------------------------------------------------------

export function listAdjustments(params: ListParams = {}): Promise<Paginated<StockAdjustment>> {
  return list<StockAdjustment>("adjustments", params);
}

export async function getAdjustment(id: number): Promise<StockAdjustmentDetail> {
  const { data } = await api.get<StockAdjustmentDetail>(`/inventory/adjustments/${id}/`);
  return data;
}

export async function saveAdjustment(
  id: number | null,
  payload: AdjustmentPayload,
): Promise<StockAdjustmentDetail> {
  const { data } = id
    ? await api.patch<StockAdjustmentDetail>(`/inventory/adjustments/${id}/`, payload)
    : await api.post<StockAdjustmentDetail>("/inventory/adjustments/", payload);
  return data;
}

export async function postAdjustment(id: number): Promise<StockAdjustmentDetail> {
  const { data } = await api.post<StockAdjustmentDetail>(`/inventory/adjustments/${id}/post/`);
  return data;
}

export async function cancelAdjustment(id: number, reason: string): Promise<StockAdjustmentDetail> {
  const { data } = await api.post<StockAdjustmentDetail>(`/inventory/adjustments/${id}/cancel/`, {
    reason,
  });
  return data;
}

// --- açılış stoku --------------------------------------------------------------------------

export async function uploadOpening(file: File, confirm: boolean): Promise<ImportReport> {
  const body = new FormData();
  body.append("file", file);
  body.append("confirm", confirm ? "true" : "false");
  const { data } = await api.post<ImportReport>("/inventory/opening/import/", body);
  return data;
}

export const OPENING_TEMPLATE_URL = "/api/v1/inventory/opening/template/";
