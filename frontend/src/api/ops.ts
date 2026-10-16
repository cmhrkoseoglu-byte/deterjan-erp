// /api/v1/ops/* (Faz 5): sistem durumu (yalnızca admin) ve arayüz hata kaydı.
import { api } from "./client";

export type CheckStatus = "ok" | "error" | "unknown";

export interface StatusCheck {
  check: string;
  label: string;
  status: CheckStatus;
  title: string;
  detail: string;
  since: string | null;
}

export interface DiskUsage {
  path: string;
  total_bytes: number;
  free_bytes: number;
  used_pct: number;
}

export interface RowMismatch {
  table: string;
  expected: number;
  actual: number;
}

export interface BackupRun {
  id: number;
  kind: "backup" | "restore_test";
  kind_display: string;
  run_id: string;
  source_run_id: string;
  started_at: string;
  finished_at: string;
  status: "ok" | "failed";
  status_display: string;
  message: string;
  database_bytes: number;
  media_bytes: number;
  media_files: number;
  tables: number;
  rows: number;
  offsite: "ok" | "failed" | "disabled";
  offsite_display: string;
  offsite_message: string;
  mismatches: RowMismatch[];
}

export interface SystemStatus {
  checks: StatusCheck[];
  disks: DiskUsage[];
  load_15: number | null;
  cpu_count: number | null;
  queue_length: number | null;
  runs: BackupRun[];
}

export async function fetchSystemStatus(): Promise<SystemStatus> {
  const { data } = await api.get<SystemStatus>("/ops/status/");
  return data;
}

export interface ClientErrorReport {
  message: string;
  stack?: string;
  url?: string;
}

export async function postClientError(report: ClientErrorReport): Promise<void> {
  await api.post("/ops/client-errors/", report);
}
