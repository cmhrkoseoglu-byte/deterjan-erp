import type {
  CalibrationState,
  DowntimeReason,
  MaintenanceKind,
  WorkOrder,
  WorkOrderStatus,
} from "../../api/maintenance";
import type { CurrentUser, Role } from "../../api/types";
import { hasAnyRole } from "../../auth/roles";

// Yetkiler backend ile aynıdır (apps/maintenance/services.py); arayüz yalnızca düğmeleri gizler.
/** Bakım planı ve elle iş emri açar. */
export const PLAN_ROLES: Role[] = ["uretim", "dolum", "laboratuvar", "yonetim"];
/** Duruş başlatır / bitirir. */
export const DOWNTIME_ROLES: Role[] = ["uretim", "dolum", "laboratuvar", "planlama", "yonetim"];
/** Bakım ekranlarını görür. */
export const READ_ROLES: Role[] = ["uretim", "dolum", "laboratuvar", "planlama", "yonetim"];
/** Temizliksiz geçişleri tanımlar (Karar D-14). */
export const CHANGEOVER_ROLES: Role[] = ["laboratuvar"];
export const SETTINGS_ROLES: Role[] = ["yonetim"];

export const MAINTENANCE_BASE = "/bakim";
export const workOrderPath = (id: number) => `${MAINTENANCE_BASE}/is-emirleri/${id}`;

/** İş emrini sorumlu birim ya da yönetim yürütür. */
export function canWork(user: CurrentUser | null, order: Pick<WorkOrder, "responsible_role">) {
  const roles: Role[] = order.responsible_role ? [order.responsible_role, "yonetim"] : ["yonetim"];
  return hasAnyRole(user, roles);
}

export const WORK_ORDER_STATUS_COLOR: Record<WorkOrderStatus, string> = {
  OPEN: "blue",
  IN_PROGRESS: "orange",
  COMPLETED: "green",
  CANCELLED: "gray",
};

export const OPEN_STATUSES: WorkOrderStatus[] = ["OPEN", "IN_PROGRESS"];

export const CALIBRATION_COLOR: Record<CalibrationState, string> = {
  OK: "green",
  DUE_SOON: "yellow",
  OVERDUE: "red",
  NO_PLAN: "gray",
};

export const KIND_COLOR: Record<MaintenanceKind, string> = {
  PERIODIC: "indigo",
  CLEANING: "cyan",
  CALIBRATION: "grape",
  REPAIR: "red",
};

export const DOWNTIME_REASONS: DowntimeReason[] = [
  "BREAKDOWN",
  "PLANNED_MAINTENANCE",
  "CLEANING",
  "CALIBRATION",
  "NO_MATERIAL",
  "NO_OPERATOR",
  "OTHER",
];
