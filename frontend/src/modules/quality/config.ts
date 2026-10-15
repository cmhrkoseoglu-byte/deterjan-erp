import type {
  ApprovalStatus,
  DecisionType,
  SampleStage,
  SampleStatus,
  SpecStatus,
} from "../../api/quality";
import type { Role } from "../../api/types";

// Yetkiler backend ile aynıdır (apps/quality/api/views.py); arayüz yalnızca düğmeleri gizler.
export const LAB_ROLES: Role[] = ["laboratuvar"];
export const APPROVAL_ROLES: Role[] = ["yonetim"];
export const QUALITY_BASE = "/kalite";

export const samplePath = (id: number) => `${QUALITY_BASE}/numuneler/${id}`;
export const specPath = (id: number) => `${QUALITY_BASE}/spesifikasyonlar/${id}`;

export const SAMPLE_STATUS_COLOR: Record<SampleStatus, string> = {
  PENDING: "blue",
  IN_TEST: "violet",
  AWAITING_APPROVAL: "orange",
  DECIDED: "green",
  CANCELLED: "gray",
};

export const SPEC_STATUS_COLOR: Record<SpecStatus, string> = {
  DRAFT: "blue",
  APPROVED: "green",
  OBSOLETE: "gray",
};

export const DECISION_COLOR: Record<DecisionType, string> = {
  RELEASE: "green",
  CONDITIONAL_RELEASE: "teal",
  REWORK: "orange",
  REJECT: "red",
};

export const APPROVAL_COLOR: Record<ApprovalStatus, string> = {
  NOT_REQUIRED: "gray",
  PENDING: "orange",
  APPROVED: "green",
  REFUSED: "red",
};

export const STAGES: SampleStage[] = ["INCOMING", "IN_PROCESS", "FINAL"];
/** Kararla lotu serbest bırakan / reddeden / yeniden işlemeye ayıran kararlar. */
export const DECISIONS: DecisionType[] = ["RELEASE", "CONDITIONAL_RELEASE", "REWORK", "REJECT"];
/** Şarj sırası (ara) kontrolde yalnızca uygun / uygun değil kaydedilir; lot değişmez. */
export const IN_PROCESS_DECISIONS: DecisionType[] = ["RELEASE", "REJECT"];
export const OPEN_SAMPLE_STATUSES: SampleStatus[] = ["PENDING", "IN_TEST", "AWAITING_APPROVAL"];
