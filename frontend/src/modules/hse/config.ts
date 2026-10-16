import type {
  HazardClass,
  Incident,
  IncidentStatus,
  IncidentType,
  Severity,
  SdsState,
} from "../../api/hse";
import type { Role } from "../../api/types";

// Yetkiler backend ile aynıdır (apps/hse/services.py); arayüz yalnızca düğmeleri ve sekmeleri gizler.
/** GBF, atık, depolama limiti yazar; olayları inceler ve kapatır. */
export const HSE_ROLES: Role[] = ["yonetim"];
/** Malzeme tehlike bilgisini ve H/P ifadelerini girer (herkes okur). */
export const HAZARD_ROLES: Role[] = ["yonetim", "laboratuvar"];
/** GBF arşivini ve eksik GBF raporunu görür. */
export const SDS_READ_ROLES: Role[] = ["yonetim", "depo", "laboratuvar"];
/** Depolama limitlerini ve doluluğu görür. */
export const STORAGE_READ_ROLES: Role[] = ["yonetim", "depo"];
/** Olayı herkes bildirir; yönetim dışındakiler yalnızca kendi bildirdiklerini görür. */
export const INCIDENT_ROLES: Role[] = [];

export const HSE_BASE = "/isg";
export const incidentPath = (id: number) => `${HSE_BASE}/olaylar/${id}`;

export const HAZARD_CLASSES: HazardClass[] = [
  "GHS01",
  "GHS02",
  "GHS03",
  "GHS04",
  "GHS05",
  "GHS06",
  "GHS07",
  "GHS08",
  "GHS09",
];

export const INCIDENT_TYPES: IncidentType[] = [
  "WORK_ACCIDENT",
  "NEAR_MISS",
  "ENVIRONMENTAL",
  "FIRE",
  "OTHER",
];

export const SEVERITIES: Severity[] = ["LOW", "MEDIUM", "HIGH"];

export const OPEN_INCIDENT_STATUSES: IncidentStatus[] = ["OPEN", "INVESTIGATING"];

export const INCIDENT_STATUS_COLOR: Record<IncidentStatus, string> = {
  OPEN: "blue",
  INVESTIGATING: "orange",
  CLOSED: "green",
  CANCELLED: "gray",
};

export const SEVERITY_COLOR: Record<Severity, string> = {
  LOW: "gray",
  MEDIUM: "yellow",
  HIGH: "red",
};

export const SDS_STATE_COLOR: Record<SdsState, string> = {
  OK: "green",
  MISSING: "red",
  NO_FILE: "orange",
  EXPIRED: "red",
  OUTDATED: "yellow",
};

/** Olay inceleme / kapatma işlemleri yalnızca açık kayıtlarda. */
export function isIncidentOpen(incident: Pick<Incident, "status">): boolean {
  return OPEN_INCIDENT_STATUSES.includes(incident.status);
}
