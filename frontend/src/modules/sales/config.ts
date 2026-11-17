import type { SalesOrderStatus, ShipmentStatus } from "../../api/sales";

// Düğme ve sekmeler bölüm yetkisine bakar (`auth/access`); asıl denetim backend'dedir.
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
