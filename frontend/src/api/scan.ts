// Barkod okutma: /api/v1/inventory/scan/?code=... okutulan kodu lot, lokasyon, malzeme ya da
// palete çözer (LOT:, LOC:, MAT: önekleri, GS1-128, Faz 1'de basılmış düz lot numaraları).
import { api } from "./client";
import type { LotStatus } from "./inventory";
import type { MaterialType } from "./masterdata";

export interface ScanLot {
  id: number;
  lot_no: string;
  material: number;
  material_code: string;
  material_name: string;
  material_type: MaterialType;
  unit: string;
  status: LotStatus;
  status_display: string;
  expiry_date: string | null;
  is_expired: boolean;
}

export interface ScanResult {
  kind: "lot" | "location" | "material" | "pallet";
  code: string;
  lots: ScanLot[];
  material: { id: number; code: string; name: string; material_type: MaterialType } | null;
  location: { id: number; code: string; name: string; warehouse_code: string } | null;
  pallet: { id: number; sscc: string; case_count: number } | null;
  gs1: Record<string, string>;
}

export async function scanCode(code: string): Promise<ScanResult> {
  const { data } = await api.get<ScanResult>("/inventory/scan/", { params: { code } });
  return data;
}
