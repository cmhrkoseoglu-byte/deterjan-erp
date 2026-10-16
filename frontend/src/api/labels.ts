// Etiketler (PDF / A4 PDF / ZPL), yazıcılar, etiket ayarları ve palet (SSCC) etiketleri.
import { api } from "./client";
import type { Audited } from "./masterdata";
import type { Paginated } from "./types";

export type LabelOutput = "pdf" | "a4" | "zpl";

export interface Printer extends Audited {
  code: string;
  name: string;
  printer_type: "ZPL";
  printer_type_display: string;
  host: string;
  port: number;
  dpi: number;
  location: number | null;
  location_code: string | null;
  note: string;
}

export interface LabelSettings {
  company_name: string;
  gs1_company_prefix: string;
  sscc_extension_digit: number;
  next_sscc_serial: number;
  default_printer: number | null;
  default_printer_code: string | null;
  sscc_enabled: boolean;
  updated_at: string;
}

export interface PrintResult {
  printed: number;
  printer: string;
}

export interface PalletLabel {
  id: number;
  sscc: string;
  lot: number;
  lot_no: string;
  material_code: string;
  material_name: string;
  case_count: number;
  units_per_case: number | null;
  created_by_name: string | null;
  created_at: string;
}

/** Etiket indirme adresi (tarayıcıda yeni sekmede açılır ya da indirilir). */
export function labelUrl(
  path: string,
  params: { output: LabelOutput; copies?: number; units_per_case?: number | null },
): string {
  const query = new URLSearchParams({ output: params.output });
  if (params.copies && params.copies > 1) query.set("copies", String(params.copies));
  if (params.units_per_case) query.set("units_per_case", String(params.units_per_case));
  return `/api/v1${path}?${query.toString()}`;
}

export const labelPaths = {
  lot: (id: number) => `/inventory/lots/${id}/label/`,
  case: (id: number) => `/inventory/lots/${id}/case-label/`,
  receipt: (id: number) => `/inventory/goods-receipts/${id}/labels/`,
  pallet: (id: number) => `/inventory/pallet-labels/${id}/label/`,
  location: (id: number) => `/masterdata/locations/${id}/label/`,
};

export async function listPrinters(): Promise<Printer[]> {
  const { data } = await api.get<Paginated<Printer>>("/masterdata/printers/", {
    params: { is_active: true, page_size: 200 },
  });
  return data.results;
}

export async function testPrinter(id: number): Promise<PrintResult> {
  const { data } = await api.post<PrintResult>(`/masterdata/printers/${id}/test/`);
  return data;
}

export async function getLabelSettings(): Promise<LabelSettings> {
  const { data } = await api.get<LabelSettings>("/masterdata/label-settings/");
  return data;
}

export async function saveLabelSettings(payload: Partial<LabelSettings>): Promise<LabelSettings> {
  const { data } = await api.put<LabelSettings>("/masterdata/label-settings/", payload);
  return data;
}

export interface PrintPayload {
  printer: number;
  copies: number;
  kind?: "lot" | "case";
  units_per_case?: number | null;
}

/** Etiketi ağ yazıcısına gönderir (`print-label` / `print-labels` uçları). */
export async function printLabel(path: string, payload: PrintPayload): Promise<PrintResult> {
  const { data } = await api.post<PrintResult>(path, payload);
  return data;
}

export const printPaths = {
  lot: (id: number) => `/inventory/lots/${id}/print-label/`,
  receipt: (id: number) => `/inventory/goods-receipts/${id}/print-labels/`,
  pallet: (id: number) => `/inventory/pallet-labels/${id}/print-label/`,
  location: (id: number) => `/masterdata/locations/${id}/print-label/`,
};

export async function listPallets(lot: number): Promise<PalletLabel[]> {
  const { data } = await api.get<Paginated<PalletLabel>>("/inventory/pallet-labels/", {
    params: { lot, page_size: 200 },
  });
  return data.results;
}

export async function createPallet(payload: {
  lot: number;
  case_count: number;
  units_per_case?: number | null;
}): Promise<PalletLabel> {
  const { data } = await api.post<PalletLabel>("/inventory/pallet-labels/", payload);
  return data;
}

export const labelQueryKeys = {
  printers: ["labels", "printers"] as const,
  settings: ["labels", "settings"] as const,
};
