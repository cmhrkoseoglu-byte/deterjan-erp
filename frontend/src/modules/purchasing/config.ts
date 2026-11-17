import type { PurchaseOrderStatus, PurchaseRequestStatus } from "../../api/purchasing";

// Sekme ve düğmeler bölüm yetkisine bakar (`auth/access`); asıl denetim backend'dedir.

export const PURCHASING_BASE = "/satin-alma";
export const purchaseOrderPath = (id: number | "yeni") => `${PURCHASING_BASE}/siparisler/${id}`;

export const ORDER_STATUS_COLOR: Record<PurchaseOrderStatus, string> = {
  DRAFT: "blue",
  PENDING_APPROVAL: "yellow",
  APPROVED: "indigo",
  SENT: "cyan",
  PARTIALLY_RECEIVED: "orange",
  RECEIVED: "green",
  CANCELLED: "gray",
};

export const REQUEST_STATUS_COLOR: Record<PurchaseRequestStatus, string> = {
  OPEN: "blue",
  ORDERED: "green",
  CANCELLED: "gray",
};

/** Mal kabul yapılabilen sipariş durumları. */
export const RECEIVABLE_STATUSES: PurchaseOrderStatus[] = [
  "APPROVED",
  "SENT",
  "PARTIALLY_RECEIVED",
];
/** İptal edilebilen durumlar (mal kabul gelmeden). */
export const CANCELLABLE_STATUSES: PurchaseOrderStatus[] = [
  "DRAFT",
  "PENDING_APPROVAL",
  "APPROVED",
  "SENT",
];
