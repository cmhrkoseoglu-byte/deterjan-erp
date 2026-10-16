import type { Role } from "../../api/types";
import type { SalesOrderStatus } from "../../api/sales";

// Yetkiler backend ile aynıdır (apps/sales/api/views.py); arayüz yalnızca düğmeleri gizler.
export const ORDER_WRITE_ROLES: Role[] = ["sevkiyat", "yonetim"];
export const SALES_BASE = "/sevkiyat";

export const salesOrderPath = (id: number | "yeni") => `${SALES_BASE}/siparisler/${id}`;
export const customerPath = (id: number) => `${SALES_BASE}/musteriler/${id}`;

export const ORDER_STATUS_COLOR: Record<SalesOrderStatus, string> = {
  DRAFT: "blue",
  CONFIRMED: "indigo",
  PARTIALLY_SHIPPED: "orange",
  SHIPPED: "teal",
  CLOSED: "green",
  CANCELLED: "gray",
};

/** Rezervasyonu değiştirilebilen sipariş durumları. */
export const RESERVABLE_STATUSES: SalesOrderStatus[] = ["CONFIRMED", "PARTIALLY_SHIPPED"];
