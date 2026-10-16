// /api/v1/maintenance/* uç noktaları (Faz 4, Adım 4.4): bakım planı, iş emri (`BK-`), arıza
// bildirimi, tank temizliği, duruş, kalibrasyon durumu, temizliksiz geçiş kuralları (Karar D-14).
// Miktarlar metin olarak gelir; süreler dakika.
import { api } from "./client";
import type { ListParams } from "./masterdata";
import type { Role } from "./types";
import type { Paginated } from "./types";

export type MaintenanceKind = "PERIODIC" | "CLEANING" | "CALIBRATION" | "REPAIR";
export type PlanKind = Exclude<MaintenanceKind, "REPAIR">;
export type WorkOrderStatus = "OPEN" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export type WorkOrderSource = "PLAN" | "BREAKDOWN" | "CHANGEOVER" | "MANUAL";
export type CalibrationResult = "PASSED" | "FAILED";
export type DowntimeReason =
  | "BREAKDOWN"
  | "PLANNED_MAINTENANCE"
  | "CLEANING"
  | "CALIBRATION"
  | "NO_MATERIAL"
  | "NO_OPERATOR"
  | "OTHER";
export type CalibrationState = "OK" | "DUE_SOON" | "OVERDUE" | "NO_PLAN";

export interface MaintenancePlan {
  id: number;
  equipment: number;
  equipment_code: string;
  equipment_name: string;
  equipment_type: string;
  kind: PlanKind;
  kind_display: string;
  title: string;
  interval_days: number | null;
  interval_runs: number | null;
  checklist: string[];
  responsible_role: Role | "";
  responsible_role_display: string;
  next_due_date: string | null;
  last_done_at: string | null;
  note: string;
  is_active: boolean;
  runs_done: number | null;
  is_due: boolean;
  is_overdue: boolean;
}

export interface PlanPayload {
  equipment: number;
  kind: PlanKind;
  title: string;
  interval_days: number | null;
  interval_runs: number | null;
  checklist: string[];
  responsible_role: Role | "";
  next_due_date: string | null;
  note: string;
}

export interface ChecklistRow {
  item: string;
  done: boolean;
  note: string;
}

export interface WorkOrderPart {
  id: number;
  material: number | null;
  material_code: string | null;
  lot: number | null;
  lot_no: string | null;
  location: number | null;
  location_code: string | null;
  description: string;
  quantity: string;
  unit_text: string;
  movement: number | null;
}

export interface WorkOrder {
  id: number;
  number: string;
  status: WorkOrderStatus;
  status_display: string;
  equipment: number;
  equipment_code: string;
  equipment_name: string;
  plan: number | null;
  plan_title: string | null;
  source: WorkOrderSource;
  source_display: string;
  kind: MaintenanceKind;
  kind_display: string;
  title: string;
  description: string;
  responsible_role: Role | "";
  responsible_role_display: string;
  due_date: string | null;
  checklist_rows: ChecklistRow[];
  previous_product: number | null;
  previous_product_code: string | null;
  started_at: string | null;
  started_by_name: string | null;
  completed_at: string | null;
  completed_by_name: string | null;
  work_done: string;
  duration_minutes: number | null;
  calibration_result: CalibrationResult | "";
  calibration_result_display: string;
  certificate_no: string;
  cancel_reason: string;
  created_at: string;
  created_by_name: string | null;
  parts: WorkOrderPart[];
  downtime_minutes: number | null;
}

export interface WorkOrderPayload {
  equipment: number;
  kind: MaintenanceKind;
  title: string;
  description: string;
  responsible_role: Role | "";
  due_date: string | null;
  checklist: string[];
}

export interface CompletePayload {
  work_done: string;
  duration_minutes: number | null;
  checklist: { done: boolean; note: string }[];
  calibration_result: CalibrationResult | "";
  certificate_no: string;
}

export interface PartPayload {
  material: number | null;
  lot: number | null;
  location: number | null;
  description: string;
  quantity: string;
  unit_text: string;
}

export interface BreakdownPayload {
  equipment: number;
  description: string;
  stop_equipment: boolean;
}

export interface CleaningPayload {
  equipment: number;
  work_done: string;
  checklist: string[];
  duration_minutes: number | null;
}

export interface CleaningCheck {
  required: boolean;
  previous_product_code: string | null;
  previous_product_name: string | null;
  is_down: boolean;
  downtime_reason: string | null;
}

export interface Downtime {
  id: number;
  equipment: number;
  equipment_code: string;
  equipment_name: string;
  reason: DowntimeReason;
  reason_display: string;
  started_at: string;
  ended_at: string | null;
  note: string;
  end_note: string;
  work_order: number | null;
  work_order_number: string | null;
  created_by_name: string | null;
  ended_by_name: string | null;
  minutes: number | null;
}

export interface DowntimePayload {
  equipment: number;
  reason: DowntimeReason;
  started_at?: string;
  note: string;
}

export interface DowntimeSummaryRow {
  equipment_id: number;
  equipment_code: string;
  equipment_name: string;
  reason: DowntimeReason;
  reason_display: string;
  count: number;
  minutes: number;
}

export interface CalibrationStatus {
  equipment: number;
  equipment_code: string;
  equipment_name: string;
  status: CalibrationState;
  label: string;
  next_due_date: string | null;
  days_left: number | null;
  is_down: boolean;
}

export interface ChangeoverRule {
  id: number;
  from_product: number;
  from_product_code: string;
  from_product_name: string;
  to_product: number;
  to_product_code: string;
  to_product_name: string;
  note: string;
  is_active: boolean;
}

export interface ChangeoverRulePayload {
  from_product: number;
  to_product: number;
  note: string;
}

export interface MaintenanceSettings {
  calibration_warning_days: number;
  plan_lead_days: number;
}

const BASE = "/maintenance";
const PLANS = `${BASE}/plans`;
const ORDERS = `${BASE}/work-orders`;
const DOWNTIMES = `${BASE}/downtimes`;
const RULES = `${BASE}/changeover-rules`;

function clean(params: ListParams): ListParams {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  );
}

// --- plan ---

export async function listPlans(params: ListParams = {}): Promise<Paginated<MaintenancePlan>> {
  const { data } = await api.get<Paginated<MaintenancePlan>>(`${PLANS}/`, {
    params: clean(params),
  });
  return data;
}

export async function getPlan(id: number): Promise<MaintenancePlan> {
  const { data } = await api.get<MaintenancePlan>(`${PLANS}/${id}/`);
  return data;
}

export async function savePlan(id: number | null, payload: PlanPayload): Promise<MaintenancePlan> {
  const { data } = id
    ? await api.patch<MaintenancePlan>(`${PLANS}/${id}/`, payload)
    : await api.post<MaintenancePlan>(`${PLANS}/`, payload);
  return data;
}

export async function setPlanActive(id: number, active: boolean): Promise<MaintenancePlan> {
  const { data } = await api.post<MaintenancePlan>(
    `${PLANS}/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

// --- iş emri ---

export async function listWorkOrders(
  params: ListParams = {},
  statuses: WorkOrderStatus[] = [],
): Promise<Paginated<WorkOrder>> {
  const { data } = await api.get<Paginated<WorkOrder>>(`${ORDERS}/`, {
    params: { ...clean(params), ...(statuses.length ? { status: statuses } : {}) },
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function getWorkOrder(id: number): Promise<WorkOrder> {
  const { data } = await api.get<WorkOrder>(`${ORDERS}/${id}/`);
  return data;
}

export async function createWorkOrder(payload: WorkOrderPayload): Promise<WorkOrder> {
  const { data } = await api.post<WorkOrder>(`${ORDERS}/`, payload);
  return data;
}

async function orderAction(id: number, name: string, body: object = {}): Promise<WorkOrder> {
  const { data } = await api.post<WorkOrder>(`${ORDERS}/${id}/${name}/`, body);
  return data;
}

export const startWorkOrder = (id: number) => orderAction(id, "start");
export const completeWorkOrder = (id: number, payload: CompletePayload) =>
  orderAction(id, "complete", payload);
export const cancelWorkOrder = (id: number, reason: string) =>
  orderAction(id, "cancel", { reason });
export const addWorkOrderPart = (id: number, payload: PartPayload) =>
  orderAction(id, "parts", payload);

// --- arıza, temizlik ---

export async function reportBreakdown(payload: BreakdownPayload): Promise<WorkOrder> {
  const { data } = await api.post<WorkOrder>(`${BASE}/breakdowns/`, payload);
  return data;
}

export async function recordCleaning(payload: CleaningPayload): Promise<WorkOrder> {
  const { data } = await api.post<WorkOrder>(`${BASE}/cleanings/`, payload);
  return data;
}

export async function getCleaningCheck(equipment: number, product: number): Promise<CleaningCheck> {
  const { data } = await api.get<CleaningCheck>(`${BASE}/cleaning-check/`, {
    params: { equipment, product },
  });
  return data;
}

// --- duruş ---

export async function listDowntimes(
  params: {
    is_open?: boolean;
    equipment?: number;
    reason?: DowntimeReason;
    date_from?: string;
    date_to?: string;
    page?: number;
    page_size?: number;
    search?: string;
  } = {},
): Promise<Paginated<Downtime>> {
  const { data } = await api.get<Paginated<Downtime>>(`${DOWNTIMES}/`, {
    params: clean(params as ListParams),
  });
  return data;
}

export async function startDowntime(payload: DowntimePayload): Promise<Downtime> {
  const { data } = await api.post<Downtime>(`${DOWNTIMES}/`, payload);
  return data;
}

export async function endDowntime(
  id: number,
  payload: { note: string; ended_at?: string | null },
): Promise<Downtime> {
  const { data } = await api.post<Downtime>(`${DOWNTIMES}/${id}/end/`, payload);
  return data;
}

export async function getDowntimeSummary(
  params: { date_from?: string; date_to?: string; equipment?: number } = {},
): Promise<DowntimeSummaryRow[]> {
  const { data } = await api.get<DowntimeSummaryRow[]>(`${BASE}/downtime-summary/`, {
    params: clean(params as ListParams),
  });
  return data;
}

// --- kalibrasyon ---

export async function getCalibrationStatus(): Promise<CalibrationStatus[]> {
  const { data } = await api.get<CalibrationStatus[]>(`${BASE}/calibration/`);
  return data;
}

// --- temizliksiz geçişler ---

export async function listChangeoverRules(
  params: ListParams = {},
): Promise<Paginated<ChangeoverRule>> {
  const { data } = await api.get<Paginated<ChangeoverRule>>(`${RULES}/`, {
    params: clean(params),
  });
  return data;
}

export async function createChangeoverRule(
  payload: ChangeoverRulePayload,
): Promise<ChangeoverRule> {
  const { data } = await api.post<ChangeoverRule>(`${RULES}/`, payload);
  return data;
}

export async function setChangeoverRuleActive(
  id: number,
  active: boolean,
): Promise<ChangeoverRule> {
  const { data } = await api.post<ChangeoverRule>(
    `${RULES}/${id}/${active ? "activate" : "deactivate"}/`,
  );
  return data;
}

// --- ayarlar ---

export async function getMaintenanceSettings(): Promise<MaintenanceSettings> {
  const { data } = await api.get<MaintenanceSettings>(`${BASE}/settings/`);
  return data;
}

export async function saveMaintenanceSettings(
  payload: Partial<MaintenanceSettings>,
): Promise<MaintenanceSettings> {
  const { data } = await api.patch<MaintenanceSettings>(`${BASE}/settings/`, payload);
  return data;
}
