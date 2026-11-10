// Barkod okutma: /api/v1/inventory/scan/?code=... okutulan kodu lot, lokasyon, malzeme ya da
// palete çözer (LOT:, LOC:, MAT: önekleri, GS1-128, Faz 1'de basılmış düz lot numaraları).
// Koli GTIN'i okutulunca sonuç koli birimiyle gelir (`unit`, `units_per_case`).
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
  is_hazardous?: boolean;
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
  material: {
    id: number;
    code: string;
    name: string;
    material_type: MaterialType;
    /** Temel birim kodu: lotsuz koli okutmasında "1 koli = N <birim>" bununla yazılır. */
    base_unit_code?: string;
  } | null;
  location: { id: number; code: string; name: string; warehouse_code: string } | null;
  pallet: { id: number; sscc: string; case_count: number } | null;
  gs1: Record<string, string>;
  /** Kayıt eski koduyla bulunduysa okutulan eski kod (etiket yenilenmeli). */
  former_code?: string;
  /** "KOLI": koli GTIN'i okutuldu (koli birimiyle çözüldü); diğer kodlarda "". */
  unit?: string;
  /** Koli GTIN'inde 1 koli = kaç temel birim (ondalık metin, ör. "12.0000"). */
  units_per_case?: string | null;
  /** Türkçe uyarılar (ör. barkoddaki SKT lot kaydından farklı). */
  warnings?: string[];
  /** Çözülen GS1 tarihleri, AI → ISO "YYYY-MM-DD" (ör. {"17": "2028-10-31"}). */
  gs1_dates?: Record<string, string>;
}

export async function scanCode(code: string): Promise<ScanResult> {
  const { data } = await api.get<ScanResult>("/inventory/scan/", { params: { code } });
  return data;
}
