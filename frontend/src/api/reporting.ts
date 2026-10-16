// /api/v1/reporting/* uç noktaları (panolar, raporlar, arka plan rapor dosyaları; Faz 4 Adım 4.3).
// Sayılar metin olarak gelir (Decimal). Tutar alanları yalnızca yönetim ve admin'e döner.
import axios from "axios";
import { api } from "./client";
import type { Paginated } from "./types";

export type DashboardCode = "management" | "warehouse" | "lab" | "production" | "shipping";
export type ColumnKind =
  "text" | "number" | "money" | "percent" | "duration" | "date" | "datetime" | "boolean";
export type FilterKey =
  | "date_from"
  | "date_to"
  | "material"
  | "material_type"
  | "warehouse"
  | "location"
  | "equipment"
  | "customer"
  | "lot_status"
  | "movement_type"
  | "stage"
  | "decision"
  | "role"
  | "lot_no"
  | "expiring_days";
export type ReportParams = Partial<Record<FilterKey, string>>;
export type FileFormat = "xlsx" | "pdf";
export type JobStatus = "QUEUED" | "RUNNING" | "DONE" | "FAILED" | "EXPIRED";

export interface DashboardInfo {
  code: DashboardCode;
  title: string;
}

export interface ReportColumn {
  key: string;
  label: string;
  kind: ColumnKind;
}

export interface SummaryItem {
  key: string;
  label: string;
  kind: ColumnKind;
  value: string | number | null;
}

export interface ReportInfo {
  code: string;
  title: string;
  description: string;
  filters: FilterKey[];
  default_days: number | null;
  columns: ReportColumn[];
}

export type ReportValue = string | number | boolean | null;

export interface ReportPage {
  code: string;
  title: string;
  columns: ReportColumn[];
  summary: SummaryItem[];
  filters: ReportParams;
  count: number;
  sync_limit: number;
  results: Record<string, ReportValue>[];
}

export interface ReportJob {
  id: number;
  report_code: string;
  title: string;
  file_format: FileFormat;
  file_format_display: string;
  params: ReportParams;
  status: JobStatus;
  status_display: string;
  file_name: string;
  row_count: number | null;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
  can_download: boolean;
}

// --- pano veri biçimleri ----------------------------------------------------------------------

export interface StatusCount {
  status: string;
  label: string;
  count: number;
}

export interface ProductionPeriod {
  bulk: { unit: string; quantity: string; batches: number }[];
  units: number;
  runs: number | null;
}

export interface ProductionOutput {
  today: ProductionPeriod;
  week: ProductionPeriod;
}

export interface QcPending {
  sample_count: number;
  lot_count: number;
  avg_wait_hours: string | null;
  max_wait_hours: string | null;
}

export interface ManagementDashboard {
  date: string;
  production: ProductionOutput;
  open_orders: { production: StatusCount[]; filling: StatusCount[]; sales: StatusCount[] };
  qc_pending: QcPending;
  scrap: { days: number; good_units: string; scrap_units: string; rate: string | null };
  critical_stock: {
    count: number;
    items: {
      material_id: number;
      material: string;
      stock: string;
      min_stock: string;
      unit: string;
    }[];
  };
  expiring_lots: {
    days: number;
    count: number;
    expired_count: number;
    items: {
      lot_id: number;
      lot_no: string;
      material: string;
      expiry_date: string;
      days_left: number | null;
      quantity: string;
      unit: string;
      status: string;
    }[];
  };
  tasks: {
    overdue_total: number;
    by_role: {
      role: string;
      label: string;
      open: number;
      overdue: number;
      max_delay_hours: string | null;
    }[];
  };
  maintenance: {
    days: number;
    open_work_orders: number;
    due_plans: number;
    overdue_plans: number;
    open_downtimes: number;
    downtime_minutes: number;
  };
  hse: { days: number; incidents: number; injuries: number; open_incidents: number };
  stock_value: {
    total: string;
    by_type: { material_type: string; value: string }[];
    has_uncosted: boolean;
  } | null;
}

export interface QueueOrder {
  id: number;
  number: string;
  product?: string;
  customer?: string;
  planned_date: string;
  status: string;
  status_display: string;
  priority?: number;
  late: boolean;
}

export interface WarehouseDashboard {
  date: string;
  production_prep: QueueOrder[];
  filling_prep: QueueOrder[];
  shipment_picking: QueueOrder[];
  draft_receipts: number;
  tasks: { open: number; overdue: number };
  expiring_lot_count: number;
  critical_stock_count: number;
}

export interface LabDashboard {
  date: string;
  summary: QcPending;
  by_stage: { stage: string; label: string; count: number }[];
  by_status: StatusCount[];
  queue: {
    id: number;
    number: string;
    stage: string;
    status: string;
    status_display: string;
    lot_no: string;
    material: string;
    created_at: string;
    wait_hours: string;
  }[];
  queue_truncated: boolean;
  decided_today: number;
  last_30_days: { decided: number; rejected: number; rejection_rate: string | null };
}

export interface TankStatus {
  id: number;
  code: string;
  name: string;
  type: string;
  capacity: string | null;
  capacity_unit: string;
  fill_pct: string | null;
  state: "IN_BATCH" | "FILLED" | "EMPTY";
  state_display: string;
  batch: {
    id: number;
    batch_no: string;
    order_id: number;
    order_number: string;
    product: string;
    started_at: string;
    running_hours: string;
  } | null;
  contents: {
    lot_no: string;
    material: string;
    quantity: string;
    unit: string;
    lot_status: string;
  }[];
  downtime: { reason: string; reason_display: string; started_at: string } | null;
}

export interface ProductionDashboard {
  date: string;
  tanks: TankStatus[];
  order_counts: StatusCount[];
  orders: {
    id: number;
    number: string;
    product: string;
    equipment: string;
    planned_date: string;
    status: string;
    status_display: string;
    priority: number;
  }[];
  output: ProductionOutput;
}

export interface ShippingDashboard {
  date: string;
  status_counts: StatusCount[];
  dispatched_today: number;
  today: {
    id: number;
    number: string;
    customer: string;
    order_number: string;
    status: string;
    status_display: string;
    vehicle_plate: string;
  }[];
  waiting_orders: number;
  shortage_orders: number;
  late_orders: {
    id: number;
    number: string;
    customer: string;
    requested_delivery_date: string;
    days_late: number | null;
    status_display: string;
  }[];
}

export interface DashboardData {
  management: ManagementDashboard;
  warehouse: WarehouseDashboard;
  lab: LabDashboard;
  production: ProductionDashboard;
  shipping: ShippingDashboard;
}

function clean(params: ReportParams): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
  ) as Record<string, string>;
}

export async function listDashboards(): Promise<DashboardInfo[]> {
  const { data } = await api.get<DashboardInfo[]>("/reporting/dashboards/");
  return data;
}

export async function getDashboard<C extends DashboardCode>(code: C): Promise<DashboardData[C]> {
  const { data } = await api.get<DashboardData[C]>(`/reporting/dashboards/${code}/`);
  return data;
}

export async function listReports(): Promise<ReportInfo[]> {
  const { data } = await api.get<ReportInfo[]>("/reporting/reports/");
  return data;
}

export async function getReport(
  code: string,
  params: ReportParams & { page?: number; page_size?: number },
): Promise<ReportPage> {
  const { data } = await api.get<ReportPage>(`/reporting/reports/${code}/`, {
    params: clean(params as ReportParams),
  });
  return data;
}

export type ExportResult = { kind: "file"; fileName: string } | { kind: "job"; job: ReportJob };

function fileNameFrom(disposition: string | undefined, fallback: string): string {
  const match = disposition?.match(/filename="?([^"]+)"?/);
  return match ? match[1] : fallback;
}

/** Tarayıcıda dosya indirmesini başlatır. */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Excel / PDF: küçük rapor hemen iner; büyüğü arka planda hazırlanır (202, iş kaydı). */
export async function exportReport(
  code: string,
  fileFormat: FileFormat,
  params: ReportParams,
): Promise<ExportResult> {
  let response;
  try {
    response = await api.post<Blob>(
      `/reporting/reports/${code}/export/`,
      { file_format: fileFormat, ...clean(params) },
      { responseType: "blob" },
    );
  } catch (error) {
    // Hata gövdesi de blob gelir; Türkçe mesaj (`detail`) okunabilsin diye JSON'a çevrilir.
    if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
      try {
        error.response.data = JSON.parse(await error.response.data.text());
      } catch {
        // JSON değilse olduğu gibi bırakılır.
      }
    }
    throw error;
  }
  if (response.status === 202) {
    const job = JSON.parse(await response.data.text()) as ReportJob;
    return { kind: "job", job };
  }
  const fileName = fileNameFrom(
    response.headers["content-disposition"] as string | undefined,
    `${code}.${fileFormat}`,
  );
  saveBlob(response.data, fileName);
  return { kind: "file", fileName };
}

export async function listJobs(params: { page?: number } = {}): Promise<Paginated<ReportJob>> {
  const { data } = await api.get<Paginated<ReportJob>>("/reporting/jobs/", { params });
  return data;
}

export function jobDownloadUrl(id: number): string {
  return `/api/v1/reporting/jobs/${id}/download/`;
}
