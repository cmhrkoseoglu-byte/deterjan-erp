import { api } from "./client";
import type { Paginated } from "./types";

// Canlıya geçiş (Faz 5, Adım 5.6): hazırlık listesi, canlı tarihi, stok karşılaştırması, sorun bildir.

export type CheckStatus = "OK" | "WARNING" | "MISSING";

export interface ReadinessCheck {
  code: string;
  group: string;
  title: string;
  status: CheckStatus;
  detail: string;
  count: number | null;
  link: string;
  items: string[];
  more: number;
}

export interface GoLive {
  go_live_date: string | null;
  opening_open: boolean;
}

export async function getReadiness(): Promise<ReadinessCheck[]> {
  const { data } = await api.get<ReadinessCheck[]>("/golive/readiness/");
  return data;
}

export async function getGoLive(): Promise<GoLive> {
  const { data } = await api.get<GoLive>("/golive/go-live/");
  return data;
}

export async function setGoLive(go_live_date: string | null): Promise<GoLive> {
  const { data } = await api.put<GoLive>("/golive/go-live/", { go_live_date });
  return data;
}

export type ComparisonLevel = "MATERIAL" | "LOCATION" | "LOT" | "LOT_LOCATION";

export interface StockComparison {
  id: number;
  number: string;
  as_of_date: string;
  level: ComparisonLevel;
  level_display: string;
  only_file_materials: boolean;
  file_name: string;
  note: string;
  line_count: number;
  difference_count: number;
  created_at: string;
  created_by_name: string;
}

export interface ComparisonLine {
  id: number;
  material: number;
  material_code: string;
  material_name: string;
  lot_no: string;
  location: number | null;
  location_code: string;
  file_quantity: string;
  system_quantity: string;
  difference: string;
  unit: string;
  in_file: boolean;
}

export async function listComparisons(params: {
  page?: number;
}): Promise<Paginated<StockComparison>> {
  const { data } = await api.get<Paginated<StockComparison>>("/golive/comparisons/", { params });
  return data;
}

export async function getComparison(id: number): Promise<StockComparison> {
  const { data } = await api.get<StockComparison>(`/golive/comparisons/${id}/`);
  return data;
}

export async function listComparisonLines(
  id: number,
  params: { page?: number; only_differences?: boolean; search?: string },
): Promise<Paginated<ComparisonLine>> {
  const { data } = await api.get<Paginated<ComparisonLine>>(`/golive/comparisons/${id}/lines/`, {
    params,
  });
  return data;
}

export interface NewComparison {
  file: File;
  as_of_date: string | null;
  only_file_materials: boolean;
  note: string;
}

/** Hatalı satır varsa 400 `import_has_errors` ve gövdede `report` (ImportModal ile aynı biçim). */
export async function createComparison(input: NewComparison): Promise<StockComparison> {
  const body = new FormData();
  body.append("file", input.file);
  if (input.as_of_date) body.append("as_of_date", input.as_of_date);
  body.append("only_file_materials", input.only_file_materials ? "true" : "false");
  body.append("note", input.note);
  const { data } = await api.post<StockComparison>("/golive/comparisons/", body);
  return data;
}

export const comparisonExportUrl = (id: number) => `/api/v1/golive/comparisons/${id}/export/`;
export const COMPARISON_TEMPLATE_URL = "/api/v1/golive/comparisons/template/";

export interface ProblemReport {
  id: number;
  number: string;
  description: string;
  page_url: string;
  page_title: string;
  user_agent: string;
  screen: string;
  has_screenshot: boolean;
  reporter: string;
  created_at: string;
}

export interface NewProblemReport {
  description: string;
  page_url: string;
  page_title: string;
  user_agent: string;
  screen: string;
  screenshot: Blob | null;
}

export async function reportProblem(input: NewProblemReport): Promise<ProblemReport> {
  const body = new FormData();
  body.append("description", input.description);
  body.append("page_url", input.page_url);
  body.append("page_title", input.page_title);
  body.append("user_agent", input.user_agent);
  body.append("screen", input.screen);
  if (input.screenshot) body.append("screenshot", input.screenshot, "ekran.jpg");
  const { data } = await api.post<ProblemReport>("/golive/problems/", body);
  return data;
}

export async function listProblems(params: { page?: number }): Promise<Paginated<ProblemReport>> {
  const { data } = await api.get<Paginated<ProblemReport>>("/golive/problems/", { params });
  return data;
}

export async function getProblem(id: number): Promise<ProblemReport> {
  const { data } = await api.get<ProblemReport>(`/golive/problems/${id}/`);
  return data;
}

export const problemScreenshotUrl = (id: number) => `/api/v1/golive/problems/${id}/screenshot/`;
