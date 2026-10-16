// /api/v1/filling/* uç noktaları. Miktarlar temel birimde, metin olarak gelir ("780.0000").
import { api } from "./client";
import type { StockBalance } from "./inventory";
import type { ListParams } from "./masterdata";
import type { Paginated } from "./types";

export type FillingOrderStatus =
  | "DRAFT"
  | "APPROVED"
  | "MATERIAL_PREP"
  | "MATERIAL_READY"
  | "IN_PROGRESS"
  | "QC_PENDING"
  | "COMPLETED"
  | "CANCELLED";
export type FillingRunStatus = "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export type PackagingSpecStatus = "DRAFT" | "APPROVED" | "OBSOLETE";
export type ScrapKind = "BULK" | "PACKAGING" | "FINISHED";
export type ScrapReason =
  | "OVERFILL"
  | "UNDERFILL"
  | "LEAK"
  | "LABEL_ERROR"
  | "CAP_ERROR"
  | "DAMAGED_PACKAGING"
  | "SETUP_LOSS"
  | "OTHER";

export interface PackagingSpecLine {
  id?: number;
  spec?: number;
  sequence?: number | null;
  material: number;
  material_code?: string;
  material_name?: string;
  unit?: string;
  quantity_per_unit: string;
  scrap_allowance_pct?: string | null;
}

export interface PackagingSpec {
  id: number;
  finished_product: number;
  finished_product_code: string;
  finished_product_name: string;
  bulk_product: number;
  bulk_product_code: string;
  bulk_product_name: string;
  bulk_unit: string;
  version_no: number;
  status: PackagingSpecStatus;
  status_display: string;
  fill_quantity: string;
  fill_unit: number;
  fill_unit_code: string;
  fill_tolerance_pct: string;
  units_per_case: number;
  cases_per_pallet: number | null;
  change_note: string | null;
  copied_from: number | null;
  copied_from_no: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  obsoleted_at: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface PackagingSpecDetail extends PackagingSpec {
  lines: PackagingSpecLine[];
  is_editable: boolean;
}

export interface PackagingSpecPayload {
  finished_product: number | null;
  bulk_product: number | null;
  fill_quantity: string;
  fill_unit: number | null;
  fill_tolerance_pct: string;
  units_per_case: number;
  cases_per_pallet: number | null;
  change_note: string;
  lines?: PackagingSpecLine[];
}

export interface FillingOrder {
  id: number;
  number: string;
  status: FillingOrderStatus;
  status_display: string;
  finished_product: number;
  finished_product_code: string;
  finished_product_name: string;
  unit: string;
  packaging_spec: number;
  packaging_spec_version: number;
  bulk_product: number;
  bulk_product_code: string;
  fill_quantity: string;
  fill_unit_code: string;
  planned_units: number;
  filling_line: number;
  filling_line_code: string;
  filling_line_name: string;
  line_location_code: string | null;
  output_location: number;
  output_location_code: string;
  planned_date: string;
  notes: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface FillingRequirementRow {
  id: number;
  sequence: number;
  material: number;
  material_code: string;
  material_name: string;
  unit: string;
  quantity_per_unit: string;
  scrap_allowance_pct: string;
  /** Fire payı dahil hazırlanacak miktar. */
  required_quantity: string;
  /** Fire payı hariç ("Ambalaj hazır" için yeterli) miktar. */
  net_quantity: string;
  picked_quantity: string;
  to_pick: string;
  is_ready: boolean;
}

export interface PackagingPick {
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

export interface FillingRun {
  id: number;
  sequence: number;
  order: number;
  order_number: string;
  order_status: FillingOrderStatus;
  finished_product_code: string;
  finished_product_name: string;
  status: FillingRunStatus;
  status_display: string;
  output_lot: number;
  output_lot_no: string;
  output_lot_status: string;
  output_lot_status_display: string;
  operator_name: string | null;
  started_at: string;
  finished_at: string | null;
  finished_by_name: string | null;
  good_units: number | null;
  theoretical_bulk: string | null;
  actual_bulk: string | null;
  bulk_variance_pct: string | null;
  finish_note: string;
  cancel_reason: string;
}

export interface FillingOrderDetail extends FillingOrder {
  units_per_case: number;
  requirements: FillingRequirementRow[];
  picks: PackagingPick[];
  runs: FillingRun[];
  allowed_transitions: FillingOrderStatus[];
  approved_by_name: string | null;
  approved_at: string | null;
  completed_at: string | null;
  cancel_reason: string;
}

export interface FillingOrderPayload {
  finished_product: number | null;
  planned_units: number;
  filling_line: number | null;
  output_location: number | null;
  planned_date: string;
  notes: string;
}

export interface FillingConsumption {
  id: number;
  kind: "BULK" | "PACKAGING";
  kind_display: string;
  material: number;
  material_code: string;
  unit: string;
  lot: number;
  lot_no: string;
  location: number;
  location_code: string;
  quantity: string;
  consumed_by_name: string | null;
  consumed_at: string;
}

export interface ScrapRecord {
  id: number;
  kind: ScrapKind;
  kind_display: string;
  material: number;
  material_code: string;
  unit: string;
  lot: number | null;
  lot_no: string | null;
  quantity: string;
  reason_code: ScrapReason;
  reason_display: string;
  note: string;
  recorded_by_name: string | null;
  recorded_at: string;
}

export interface RunLot {
  id: number;
  material: number;
  material_code: string;
  material_name: string;
  lot: number;
  lot_no: string;
  scanned_by_name: string | null;
  scanned_at: string;
}

export interface StockRow {
  material: number;
  material_code: string;
  unit: string;
  lot: number;
  lot_no: string;
  expiry_date: string | null;
  location: number;
  location_code: string;
  quantity: string;
}

export interface FillingRunDetail extends FillingRun {
  bulk_product: number;
  bulk_product_code: string;
  bulk_unit: string;
  fill_quantity: string;
  fill_unit_code: string;
  planned_units: number;
  line_location_code: string | null;
  consumptions: FillingConsumption[];
  scraps: ScrapRecord[];
  scanned_lots: RunLot[];
  packaging: PackagingSpecLine[];
  /** Tüketilebilir (serbest, SKT'si geçmemiş) bulk lotlar ve tankları. */
  bulk_lots: StockRow[];
  /** Hat başındaki ambalaj stoku. */
  line_stock: StockRow[];
  allowed_transitions: FillingRunStatus[];
}

export interface ConsumptionRow {
  theoretical: string;
  consumed: string;
  scrap: string;
  actual: string;
  variance: string;
  variance_pct: string;
}

export interface PackagingReportRow extends ConsumptionRow {
  material: number;
  material_code: string;
  material_name: string;
  unit: string;
  quantity_per_unit: string;
  scrap_allowance_pct: string;
  over_allowance: boolean;
}

export interface ConsumptionReport {
  good_units: number;
  scrapped_units: number;
  bulk_product_code: string;
  bulk_unit: string;
  threshold_pct: string;
  bulk_over_threshold: boolean;
  bulk: ConsumptionRow;
  packaging: PackagingReportRow[];
  runs: FillingRun[];
}

/** Okutulan lot (numara) ya da listeden seçilen lot (kimlik). */
export interface LotRef {
  lot?: number | null;
  lot_no?: string;
}

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== "" && value !== undefined),
  );
}

async function list<T>(path: string, params: ListParams, statuses: string[]) {
  const { data } = await api.get<Paginated<T>>(`/filling/${path}/`, {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  });
  return data;
}

// --- ambalaj reçetesi ---------------------------------------------------------------------------

export function listSpecs(
  params: ListParams = {},
  statuses: PackagingSpecStatus[] = [],
): Promise<Paginated<PackagingSpec>> {
  return list<PackagingSpec>("packaging-specs", params, statuses);
}

export async function getSpec(id: number): Promise<PackagingSpecDetail> {
  const { data } = await api.get<PackagingSpecDetail>(`/filling/packaging-specs/${id}/`);
  return data;
}

export async function saveSpec(
  id: number | null,
  payload: PackagingSpecPayload,
): Promise<PackagingSpecDetail> {
  const { data } = id
    ? await api.patch<PackagingSpecDetail>(`/filling/packaging-specs/${id}/`, payload)
    : await api.post<PackagingSpecDetail>("/filling/packaging-specs/", payload);
  return data;
}

export async function specAction(
  id: number,
  action: "copy" | "approve",
  note = "",
): Promise<PackagingSpecDetail> {
  const { data } = await api.post<PackagingSpecDetail>(
    `/filling/packaging-specs/${id}/${action}/`,
    { note },
  );
  return data;
}

export async function addSpecLine(
  specId: number,
  line: PackagingSpecLine,
): Promise<PackagingSpecLine> {
  const { data } = await api.post<PackagingSpecLine>(
    `/filling/packaging-specs/${specId}/lines/`,
    line,
  );
  return data;
}

export async function updateSpecLine(
  id: number,
  line: Partial<PackagingSpecLine>,
): Promise<PackagingSpecLine> {
  const { data } = await api.patch<PackagingSpecLine>(`/filling/packaging-spec-lines/${id}/`, line);
  return data;
}

export async function removeSpecLine(id: number): Promise<void> {
  await api.delete(`/filling/packaging-spec-lines/${id}/`);
}

// --- dolum emri ---------------------------------------------------------------------------------

export function listFillingOrders(
  params: ListParams = {},
  statuses: FillingOrderStatus[] = [],
): Promise<Paginated<FillingOrder>> {
  return list<FillingOrder>("orders", params, statuses);
}

export async function getFillingOrder(id: number): Promise<FillingOrderDetail> {
  const { data } = await api.get<FillingOrderDetail>(`/filling/orders/${id}/`);
  return data;
}

export async function saveFillingOrder(
  id: number | null,
  payload: FillingOrderPayload,
): Promise<FillingOrderDetail> {
  const { data } = id
    ? await api.patch<FillingOrderDetail>(`/filling/orders/${id}/`, payload)
    : await api.post<FillingOrderDetail>("/filling/orders/", payload);
  return data;
}

type FillingOrderAction = "approve" | "start-prep" | "mark-ready" | "finish";

export async function fillingOrderAction(
  id: number,
  action: FillingOrderAction,
): Promise<FillingOrderDetail> {
  const { data } = await api.post<FillingOrderDetail>(`/filling/orders/${id}/${action}/`, {});
  return data;
}

export async function cancelFillingOrder(id: number, reason: string): Promise<FillingOrderDetail> {
  const { data } = await api.post<FillingOrderDetail>(`/filling/orders/${id}/cancel/`, {
    reason,
  });
  return data;
}

export async function pickPackaging(
  orderId: number,
  input: LotRef & { requirement: number; quantity: string; from_location?: number | null },
): Promise<PackagingPick> {
  const { data } = await api.post<PackagingPick>(`/filling/orders/${orderId}/picks/`, input);
  return data;
}

export async function packagingSuggestions(
  orderId: number,
  requirement: number,
): Promise<StockBalance[]> {
  const { data } = await api.get<StockBalance[]>(`/filling/orders/${orderId}/pick-suggestions/`, {
    params: { requirement },
  });
  return data;
}

export async function orderReport(orderId: number): Promise<ConsumptionReport> {
  const { data } = await api.get<ConsumptionReport>(`/filling/orders/${orderId}/report/`);
  return data;
}

// --- dolum partisi ------------------------------------------------------------------------------

export function listRuns(
  params: ListParams = {},
  statuses: FillingRunStatus[] = [],
): Promise<Paginated<FillingRun>> {
  return list<FillingRun>("runs", params, statuses);
}

export async function getRun(id: number): Promise<FillingRunDetail> {
  const { data } = await api.get<FillingRunDetail>(`/filling/runs/${id}/`);
  return data;
}

export async function startRun(order: number): Promise<FillingRunDetail> {
  const { data } = await api.post<FillingRunDetail>("/filling/runs/", { order });
  return data;
}

export async function consumeBulk(
  runId: number,
  input: LotRef & { quantity: string },
): Promise<FillingRunDetail> {
  const { data } = await api.post<FillingRunDetail>(`/filling/runs/${runId}/consume-bulk/`, input);
  return data;
}

export async function scanPackaging(runId: number, input: LotRef): Promise<FillingRunDetail> {
  const { data } = await api.post<FillingRunDetail>(`/filling/runs/${runId}/scan/`, input);
  return data;
}

export async function recordScrap(
  runId: number,
  input: LotRef & { kind: ScrapKind; reason_code: ScrapReason; quantity: string; note?: string },
): Promise<FillingRunDetail> {
  const { data } = await api.post<FillingRunDetail>(`/filling/runs/${runId}/scrap/`, input);
  return data;
}

export async function finishRun(
  runId: number,
  payload: { good_units: number; note: string },
): Promise<FillingRunDetail> {
  const { data } = await api.post<FillingRunDetail>(`/filling/runs/${runId}/finish/`, payload);
  return data;
}

export async function cancelRun(runId: number, reason: string): Promise<FillingRunDetail> {
  const { data } = await api.post<FillingRunDetail>(`/filling/runs/${runId}/cancel/`, { reason });
  return data;
}

export async function runReport(runId: number): Promise<ConsumptionReport> {
  const { data } = await api.get<ConsumptionReport>(`/filling/runs/${runId}/report/`);
  return data;
}
