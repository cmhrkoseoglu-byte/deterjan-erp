import type { BatchStatus, LineState, OrderStatus } from "../../api/production";
import type { Role } from "../../api/types";

// Yetkiler backend ile aynıdır (apps/production/api/views.py); arayüz yalnızca düğmeleri gizler.
export const ORDER_ROLES: Role[] = ["planlama"];
export const PREP_ROLES: Role[] = ["depo"];
export const BATCH_ROLES: Role[] = ["uretim"];
export const PRODUCTION_BASE = "/uretim";

export const orderPath = (id: number | "yeni") => `${PRODUCTION_BASE}/emirler/${id}`;
export const prepPath = (id: number) => `${PRODUCTION_BASE}/emirler/${id}/hazirlama`;
export const batchPath = (id: number) => `${PRODUCTION_BASE}/sarjlar/${id}`;

export const ORDER_STATUS_COLOR: Record<OrderStatus, string> = {
  DRAFT: "blue",
  APPROVED: "indigo",
  MATERIAL_PREP: "orange",
  MATERIAL_READY: "teal",
  IN_PRODUCTION: "violet",
  QC_PENDING: "yellow",
  COMPLETED: "green",
  CANCELLED: "gray",
};

export const BATCH_STATUS_COLOR: Record<BatchStatus, string> = {
  IN_PROGRESS: "violet",
  COMPLETED: "green",
  CANCELLED: "gray",
};

/** Tolerans göstergesi: yeşil = tolerans içinde, sarı = eksik, kırmızı = fazla. */
export const LINE_STATE_COLOR: Record<LineState, string> = {
  pending: "gray",
  under: "yellow",
  ok: "green",
  over: "red",
};

/** Depo hazırlama ekranına düşen emirler. */
export const PREP_STATUSES: OrderStatus[] = ["APPROVED", "MATERIAL_PREP"];
/** Şarj başlatılabilen emirler. */
export const BATCHABLE_STATUSES: OrderStatus[] = ["MATERIAL_READY", "IN_PRODUCTION"];
