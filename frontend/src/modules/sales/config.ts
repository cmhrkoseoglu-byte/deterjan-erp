import type { Role } from "../../api/types";
import type { SalesOrderStatus, ShipmentStatus } from "../../api/sales";

// Yetkiler backend ile aynıdır (apps/sales/api/views.py); arayüz yalnızca düğmeleri gizler.
export const ORDER_WRITE_ROLES: Role[] = ["sevkiyat", "yonetim"];
/** Sevkiyat planlama, iptal ve sevk onayı (backend `SHIPMENT_ROLES`). */
export const SHIPMENT_WRITE_ROLES: Role[] = ["sevkiyat"];
/** Lot okutma ve "Yükleme tamam" (backend `PICK_ROLES`). */
export const PICK_ROLES: Role[] = ["depo"];
/** Müşteri kartındaki sevk edilen lotlar (backend `ShippedLotViewSet`). */
export const SHIPPED_LOT_ROLES: Role[] = ["sevkiyat", "yonetim"];
export const SALES_BASE = "/sevkiyat";

export const salesOrderPath = (id: number | "yeni") => `${SALES_BASE}/siparisler/${id}`;
export const customerPath = (id: number) => `${SALES_BASE}/musteriler/${id}`;
export const shipmentPath = (id: number) => `${SALES_BASE}/sevkiyatlar/${id}`;
export const pickPath = (id: number) => `${SALES_BASE}/sevkiyatlar/${id}/toplama`;

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

export const SHIPMENT_STATUS_COLOR: Record<ShipmentStatus, string> = {
  PLANNED: "blue",
  PICKING: "orange",
  LOADED: "indigo",
  DISPATCHED: "teal",
  CANCELLED: "gray",
};

/** Lot okutulabilen sevkiyat durumları. */
export const PICKABLE_STATUSES: ShipmentStatus[] = ["PLANNED", "PICKING"];
/** Okutmanın geri alınabildiği durumlar (sevkten önce; yüklemeden sonra da). */
export const UNDOABLE_STATUSES: ShipmentStatus[] = ["PICKING", "LOADED"];
/** Sevk edilmemiş, iptal edilebilen ve başlığı düzenlenebilen durumlar. */
export const OPEN_SHIPMENT_STATUSES: ShipmentStatus[] = ["PLANNED", "PICKING", "LOADED"];
/** Sevkiyat planlanabilen sipariş durumları. */
export const SHIPPABLE_ORDER_STATUSES: SalesOrderStatus[] = ["CONFIRMED", "PARTIALLY_SHIPPED"];
