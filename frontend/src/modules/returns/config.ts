import type { ReturnDisposition, ReturnStatus } from "../../api/returns";
import type { Role } from "../../api/types";

// Yetkiler backend ile aynıdır (apps/returns/api/views.py); arayüz yalnızca düğmeleri gizler.
export const RETURN_EDIT_ROLES: Role[] = ["sevkiyat"];
export const RETURN_RECEIVE_ROLES: Role[] = ["sevkiyat", "depo"];
export const RETURN_SCRAP_ROLES: Role[] = ["depo", "sevkiyat"];
export const RETURNS_BASE = "/iadeler";

export const returnPath = (id: number | "yeni") => `${RETURNS_BASE}/${id}`;

export const RETURN_STATUS_COLOR: Record<ReturnStatus, string> = {
  DRAFT: "blue",
  RECEIVED: "yellow",
  CLOSED: "green",
  CANCELLED: "gray",
};

export const DISPOSITION_COLOR: Record<ReturnDisposition, string> = {
  PENDING: "yellow",
  RESTOCK: "green",
  REWORK: "orange",
  SCRAP: "red",
};
