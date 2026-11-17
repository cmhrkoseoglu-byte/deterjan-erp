import type { ReturnDisposition, ReturnStatus } from "../../api/returns";

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
