import type { LotStatus } from "../../api/inventory";

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
