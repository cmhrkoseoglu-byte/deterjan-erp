// /api/v1/personnel/wages/* (admin ve yönetim): brüt aylık ücretler, geçerlilik tarihli. Ücretler
// kişisel veridir (docs/KVKK.md). 2026-11-01'de Maliyet'ten Personel'e taşındı; personel maliyeti
// ve bordro bu ücretleri okur.
import { api } from "./client";

const BASE = "/personnel/wages";

export interface WageEmployee {
  id: number;
  employee_no: string;
  full_name: string;
  department: string;
  hire_date: string | null;
  /** Ayrılmışsa çıkış tarihi. */
  termination_date: string | null;
  is_active: boolean;
}

export interface EmployeeWage {
  id: number;
  employee: number;
  employee_name: string;
  gross_monthly: string;
  valid_from: string;
  note: string;
  is_active: boolean;
  removal_reason: string;
  created_at: string;
  created_by_name: string | null;
}

export interface WageSummaryRow {
  employee: WageEmployee;
  /** Bugün geçerli ücret; yoksa (hiç girilmedi ya da gelecek tarihli) boş. */
  current_wage: string | null;
  current_valid_from: string | null;
  /** Kaldırılmamış ücretler, en yenisi önce. */
  history: EmployeeWage[];
}

/** Personel sorgularının altında: kart kaydından sonra personel sorguları yenilenince bunlar da. */
export const wageKeys = {
  all: ["personnel", "wages"] as const,
  list: (includeFormer: boolean) => ["personnel", "wages", includeFormer] as const,
};

/** Çalışanlar (çıkış tarihi bugün ya da sonra olanlar dahil); `includeFormer` ile ayrılanlar da. */
export async function getWageSummary(includeFormer = false): Promise<WageSummaryRow[]> {
  const { data } = await api.get<WageSummaryRow[]>(`${BASE}/summary/`, {
    params: includeFormer ? { include_former: true } : undefined,
  });
  return data;
}

/** Hata kodları: employee_required, valid_from_required, invalid_valid_from, invalid_wage,
 * duplicate_wage. */
export async function addWage(payload: {
  employee: number;
  gross_monthly: string;
  valid_from: string;
  note: string;
}): Promise<EmployeeWage> {
  const { data } = await api.post<EmployeeWage>(`${BASE}/`, payload);
  return data;
}

export async function removeWage(id: number, reason: string): Promise<EmployeeWage> {
  const { data } = await api.post<EmployeeWage>(`${BASE}/${id}/remove/`, { reason });
  return data;
}
