import type {
  CalibrationState,
  DowntimeReason,
  MaintenanceKind,
  WorkOrder,
  WorkOrderStatus,
} from "../../api/maintenance";
import type { CurrentUser } from "../../api/types";
import { can } from "../../auth/access";
import { PERM } from "../../auth/access.gen";

// Düğme ve sekmeler bölüm yetkisine bakar (`auth/access`); asıl denetim backend'dedir.

export const MAINTENANCE_BASE = "/bakim";
export const workOrderPath = (id: number) => `${MAINTENANCE_BASE}/is-emirleri/${id}`;

/**
 * İş emrini yürütür mü: Bakım iş emirleri: Değiştirir ve sorumlu birim (iş emrinin sorumlu rolü)
 * ya da "Tüm birimlerin iş emirlerini yürütme" (backend `services._can_work`). Sorumlu rol iş
 * verisidir, rol denetimi olarak kalır (plan §4).
 */
export function canWork(user: CurrentUser | null, order: Pick<WorkOrder, "responsible_role">) {
  if (!user || !can(user, PERM.MAINTENANCE_WORK_ORDERS, "change")) return false;
  if (can(user, PERM.MAINTENANCE_ANY_UNIT, "change")) return true;
  return Boolean(order.responsible_role && user.roles.includes(order.responsible_role));
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
