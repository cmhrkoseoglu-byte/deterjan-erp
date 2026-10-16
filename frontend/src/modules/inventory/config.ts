import type { Role } from "../../api/types";
import type { LotStatus } from "../../api/inventory";

// Yetkiler backend ile aynıdır (apps/inventory/api/views.py); arayüz yalnızca düğmeleri gizler.
export const STOCK_WRITE_ROLES: Role[] = ["depo"];
/** Lotu bloke etme laboratuvarındır; serbest bırakma ve ret yalnızca kalite kararıyla olur. */
export const LOT_BLOCK_ROLES: Role[] = ["laboratuvar"];
/** Kalite kararı dışında elle serbest bırakma (Karar D-5): yalnızca admin, gerekçeyle. */
export const MANUAL_RELEASE_ROLES: Role[] = ["admin"];
export const INVENTORY_BASE = "/depo";

export const lotPath = (id: number) => `${INVENTORY_BASE}/lotlar/${id}`;
export const receiptPath = (id: number | "yeni") => `${INVENTORY_BASE}/mal-kabul/${id}`;
export const adjustmentPath = (id: number | "yeni") => `${INVENTORY_BASE}/sayim/${id}`;

export const LOT_STATUS_COLOR: Record<LotStatus, string> = {
  QUARANTINE: "yellow",
  RELEASED: "green",
  REJECTED: "red",
  BLOCKED: "gray",
};

/** Bugünün tarihi, `YYYY-MM-DD` (Türkiye saatiyle). */
export function today(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul" }).format(new Date());
}

/** Palet (SSCC) etiketi açabilen roller; backend `PALLET_ROLES`. */
export const PALLET_ROLES: Role[] = ["depo", "dolum", "sevkiyat", "uretim"];
