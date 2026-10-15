// /api/v1/production/* uç noktaları. Miktarlar temel birimde, metin olarak gelir ("600.0000").
import { api } from "./client";
import type { StockBalance } from "./inventory";
import type { ListParams } from "./masterdata";
import type { Paginated } from "./types";

export type OrderStatus =
  | "DRAFT"
  | "APPROVED"
  | "MATERIAL_PREP"
  | "MATERIAL_READY"
  | "IN_PRODUCTION"
  | "QC_PENDING"
  | "COMPLETED"
  | "CANCELLED";
export type BatchStatus = "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export type LineState = "pending" | "under" | "ok" | "over";
export type Priority = 1 | 2 | 3 | 4;

export interface ProductionOrder {
  id: number;
  number: string;
  status: OrderStatus;
  status_display: string;
  product: number;
  product_code: string;
  product_name: string;
  base_unit: string;
  /** Yeniden işleme emrinde boş olabilir (düzeltme listesiyle). */
  recipe_version: number | null;
  recipe_id: number | null;
  recipe_code: string | null;
  version_no: number | null;
  /** Yeniden işlenen bloke bulk lot (yalnızca yeniden işleme emrinde). */
  rework_lot: number | null;
  rework_lot_no: string | null;
  additions: ReworkAddition[];
  planned_quantity: string;
  unit: number;
  unit_code: string;
  planned_base_quantity: string;
  planned_date: string;
  equipment: number;
  equipment_code: string;
  equipment_name: string;
  production_location: number;
  production_location_code: string;
  priority: Priority;
  priority_display: string;
  notes: string;
  created_by_name: string | null;
  created_at: string;
}

export interface ReworkAddition {
  id?: number;
  sequence?: number | null;
  material: number;
  material_code?: string;
  material_name?: string;
  quantity: string;
  unit: number;
  unit_code?: string;
  tolerance_pct: string;
  is_water: boolean;
  instruction: string;
}

export interface RequirementRow {
  id: number;
  sequence: number;
  material: number;
  material_code: string;
  material_name: string;
  unit: string;
  required_quantity: string;
  tolerance_pct: string;
  is_water: boolean;
  /** Depoda hazırlanır mı? (Su ve yeniden işlenen sabit lot hazırlanmaz.) */
  is_picked: boolean;
  lot: number | null;
  lot_no: string | null;
  instruction: string;
  picked_quantity: string;
  consumed_quantity: string;
  to_pick: string;
  is_ready: boolean;
}

export interface MaterialPick {
  id: number;
  requirement: number;
  material_code: string;
  unit: string;
  lot: number;
  lot_no: string;
  quantity: string;
  from_location: number;
  from_location_code: string;
  to_location: number;
  to_location_code: string;
  picked_by_name: string | null;
  picked_at: string;
  returned_at: string | null;
}

export interface ProductionBatch {
  id: number;
  batch_no: string;
  sequence: number;
  order: number;
  order_number: string;
  order_status: OrderStatus;
  product_code: string;
  product_name: string;
  unit: string;
  equipment: number;
  equipment_code: string;
  status: BatchStatus;
  status_display: string;
  planned_quantity: string;
  actual_output_quantity: string | null;
  yield_pct: string | null;
  output_lot: number;
  output_lot_no: string;
  output_lot_status: string;
  output_lot_status_display: string;
  started_at: string;
  started_by_name: string | null;
  finished_at: string | null;
  finished_by_name: string | null;
  finish_note: string;
  cancel_reason: string;
}

export interface ProductionOrderDetail extends ProductionOrder {
  requirements: RequirementRow[];
  picks: MaterialPick[];
  batches: ProductionBatch[];
  allowed_transitions: OrderStatus[];
  remaining_quantity: string;
  suggested_batch_quantity: string;
  approved_by_name: string | null;
  approved_at: string | null;
  completed_at: string | null;
  cancel_reason: string;
}

export interface ConsumableLot {
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  location: number;
  location_code: string;
  quantity: string;
}

export interface BatchLine {
  requirement: number;
  sequence: number;
  material: number;
  material_code: string;
  material_name: string;
  unit: string;
  tolerance_pct: string;
  is_water: boolean;
  is_picked: boolean;
  lot: number | null;
  lot_no: string | null;
  instruction: string;
  planned_quantity: string;
  consumed_quantity: string;
  deviation_pct: string;
  state: LineState;
  available: ConsumableLot[];
}

export interface BatchConsumption {
  id: number;
  requirement: number;
  material_code: string;
  unit: string;
  lot: number;
  lot_no: string;
  location: number;
  location_code: string;
  planned_quantity: string;
  actual_quantity: string;
  deviation_pct: string;
  deviation_note: string;
  weighed_by_name: string | null;
  weighed_at: string;
}

export interface ProductionBatchDetail extends ProductionBatch {
  lines: BatchLine[];
  consumptions: BatchConsumption[];
  allowed_transitions: BatchStatus[];
}

export interface OrderPayload {
  recipe_version: number | null;
  rework_lot?: number | null;
  additions?: ReworkAddition[];
  planned_quantity: string;
  unit: number | null;
  planned_date: string;
  equipment: number | null;
  production_location?: number | null;
  priority: Priority;
  notes: string;
}

/** Okutulan lot (numara) ya da listeden seçilen lot (kimlik). */
export interface LotInput {
  requirement: number;
  lot?: number | null;
  lot_no?: string;
  quantity: string;
  note?: string;
  /** Hazırlamada lotun alınacağı lokasyon (öneriden seçilince). */
  from_location?: number | null;
}

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== "" && value !== undefined),
  );
}

/** Liste; `statuses` birden çok durumla süzer (`?status=A&status=B`). */
async function list<T>(path: string, params: ListParams, statuses: string[]) {
  const { data } = await api.get<Paginated<T>>(`/production/${path}/`, {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  });
  return data;
}

export function listOrders(
  params: ListParams = {},
  statuses: OrderStatus[] = [],
): Promise<Paginated<ProductionOrder>> {
  return list<ProductionOrder>("orders", params, statuses);
}

export async function getOrder(id: number): Promise<ProductionOrderDetail> {
  const { data } = await api.get<ProductionOrderDetail>(`/production/orders/${id}/`);
  return data;
}

export async function saveOrder(
  id: number | null,
  payload: OrderPayload,
): Promise<ProductionOrderDetail> {
  const { data } = id
    ? await api.patch<ProductionOrderDetail>(`/production/orders/${id}/`, payload)
    : await api.post<ProductionOrderDetail>("/production/orders/", payload);
  return data;
}

type OrderAction = "approve" | "start-prep" | "mark-ready" | "complete";

export async function orderAction(id: number, action: OrderAction): Promise<ProductionOrderDetail> {
  const { data } = await api.post<ProductionOrderDetail>(`/production/orders/${id}/${action}/`, {});
  return data;
}

export async function cancelOrder(id: number, reason: string): Promise<ProductionOrderDetail> {
  const { data } = await api.post<ProductionOrderDetail>(`/production/orders/${id}/cancel/`, {
    reason,
  });
  return data;
}

export async function pickMaterial(orderId: number, input: LotInput): Promise<MaterialPick> {
  const { data } = await api.post<MaterialPick>(`/production/orders/${orderId}/picks/`, input);
  return data;
}

export async function pickSuggestions(
  orderId: number,
  requirement: number,
): Promise<StockBalance[]> {
  const { data } = await api.get<StockBalance[]>(
    `/production/orders/${orderId}/pick-suggestions/`,
    { params: { requirement } },
  );
  return data;
}

export function listBatches(
  params: ListParams = {},
  statuses: BatchStatus[] = [],
): Promise<Paginated<ProductionBatch>> {
  return list<ProductionBatch>("batches", params, statuses);
}

export async function getBatch(id: number): Promise<ProductionBatchDetail> {
  const { data } = await api.get<ProductionBatchDetail>(`/production/batches/${id}/`);
  return data;
}

export async function startBatch(payload: {
  order: number;
  equipment?: number | null;
  planned_quantity?: string | null;
}): Promise<ProductionBatchDetail> {
  const { data } = await api.post<ProductionBatchDetail>("/production/batches/", payload);
  return data;
}

export async function consume(batchId: number, input: LotInput): Promise<ProductionBatchDetail> {
  const { data } = await api.post<ProductionBatchDetail>(
    `/production/batches/${batchId}/consume/`,
    input,
  );
  return data;
}

export async function finishBatch(
  batchId: number,
  payload: { output_quantity: string; note: string },
): Promise<ProductionBatchDetail> {
  const { data } = await api.post<ProductionBatchDetail>(
    `/production/batches/${batchId}/finish/`,
    payload,
  );
  return data;
}

export async function cancelBatch(batchId: number, reason: string): Promise<ProductionBatchDetail> {
  const { data } = await api.post<ProductionBatchDetail>(`/production/batches/${batchId}/cancel/`, {
    reason,
  });
  return data;
}
