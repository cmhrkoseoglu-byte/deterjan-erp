import type { FillingOrderStatus, FillingRunStatus, PackagingSpecStatus } from "../../api/filling";
import type { Role } from "../../api/types";

// Yetkiler backend ile aynıdır (apps/filling/api/views.py); arayüz yalnızca düğmeleri gizler.
export const PLAN_ROLES: Role[] = ["planlama"];
export const PREP_ROLES: Role[] = ["depo"];
export const LINE_ROLES: Role[] = ["dolum"];
export const FILLING_BASE = "/dolum";

export const fillingOrderPath = (id: number | "yeni") => `${FILLING_BASE}/emirler/${id}`;
export const fillingPrepPath = (id: number) => `${FILLING_BASE}/emirler/${id}/hazirlama`;
export const runPath = (id: number) => `${FILLING_BASE}/partiler/${id}`;
export const specPath = (id: number | "yeni") => `${FILLING_BASE}/ambalaj-receteleri/${id}`;

export const ORDER_STATUS_COLOR: Record<FillingOrderStatus, string> = {
  DRAFT: "blue",
  APPROVED: "indigo",
  MATERIAL_PREP: "orange",
  MATERIAL_READY: "teal",
  IN_PROGRESS: "violet",
  QC_PENDING: "yellow",
  COMPLETED: "green",
  CANCELLED: "gray",
};

export const RUN_STATUS_COLOR: Record<FillingRunStatus, string> = {
  IN_PROGRESS: "violet",
  COMPLETED: "green",
  CANCELLED: "gray",
};

export const SPEC_STATUS_COLOR: Record<PackagingSpecStatus, string> = {
  DRAFT: "blue",
  APPROVED: "green",
  OBSOLETE: "gray",
};

/** Depo ambalaj hazırlama ekranına düşen emirler. */
export const PREP_STATUSES: FillingOrderStatus[] = ["APPROVED", "MATERIAL_PREP"];
/** Dolum partisi başlatılabilen emirler. */
export const STARTABLE_STATUSES: FillingOrderStatus[] = ["MATERIAL_READY", "IN_PROGRESS"];
