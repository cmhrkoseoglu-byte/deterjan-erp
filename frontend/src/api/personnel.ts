// /api/v1/personnel/* (admin ve yönetim): personel kartları. Kişisel veri (docs/KVKK.md).
// Kart silinmez: işten ayrılış `terminate`, yeniden işe başlama `reinstate` ile kaydedilir.
import { api } from "./client";
import type { Paginated } from "./types";
import type { AuditEntry } from "./workflow";

export interface LinkedUser {
  id: number;
  username: string;
  full_name: string;
  is_active: boolean;
}

export interface Employee {
  id: number;
  employee_no: string;
  full_name: string;
  department: string;
  title: string;
  hire_date: string | null;
  /** Yalnızca ayrılışla yazılır; çalışan personelde boş. */
  termination_date: string | null;
  phone: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  /** Bağlı sistem kullanıcısı (yoksa sistemi kullanmıyor). */
  user: number | null;
  user_info: LinkedUser | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type EmployeeInput = Pick<
  Employee,
  | "employee_no"
  | "full_name"
  | "department"
  | "title"
  | "hire_date"
  | "phone"
  | "emergency_contact_name"
  | "emergency_contact_phone"
  | "user"
>;

export interface EmployeeFilters {
  search?: string;
  department?: string;
  /** true: çalışanlar, false: ayrılanlar, boş: tümü. */
  is_active?: boolean;
  page?: number;
}

export const EMPLOYEES_PAGE_SIZE = 50;

export async function listEmployees(filters: EmployeeFilters = {}): Promise<Paginated<Employee>> {
  const { data } = await api.get<Paginated<Employee>>("/personnel/employees/", {
    params: {
      page_size: EMPLOYEES_PAGE_SIZE,
      page: filters.page,
      search: filters.search || undefined,
      department: filters.department || undefined,
      is_active: filters.is_active,
    },
  });
  return data;
}

export async function getEmployee(id: number): Promise<Employee> {
  const { data } = await api.get<Employee>(`/personnel/employees/${id}/`);
  return data;
}

/** Hata kodları: full_name_required, department_required, employee_no_taken,
 * user_already_linked, inactive_user, validation_error. */
export async function createEmployee(input: EmployeeInput): Promise<Employee> {
  const { data } = await api.post<Employee>("/personnel/employees/", input);
  return data;
}

/** Yalnızca gönderilen alanlar değişir; hata kodları `createEmployee` ile aynı. */
export async function updateEmployee(
  id: number,
  changes: Partial<EmployeeInput>,
): Promise<Employee> {
  const { data } = await api.patch<Employee>(`/personnel/employees/${id}/`, changes);
  return data;
}

/** İşten ayrılış. Hata kodları: already_terminated, termination_before_hire. */
export async function terminateEmployee(
  id: number,
  terminationDate: string,
  note = "",
): Promise<Employee> {
  const { data } = await api.post<Employee>(`/personnel/employees/${id}/terminate/`, {
    termination_date: terminationDate,
    note,
  });
  return data;
}

/** Yeniden işe başlama. Hata kodu: already_active. */
export async function reinstateEmployee(id: number): Promise<Employee> {
  const { data } = await api.post<Employee>(`/personnel/employees/${id}/reinstate/`);
  return data;
}

/** Kartın değişiklik geçmişi (en yenisi önce). */
export async function fetchEmployeeHistory(id: number): Promise<AuditEntry[]> {
  const { data } = await api.get<AuditEntry[]>(`/personnel/employees/${id}/history/`);
  return data;
}

/** Kayıtlı birimler (süzgeç ve yeni kartta öneri). */
export async function listDepartments(): Promise<string[]> {
  const { data } = await api.get<string[]>("/personnel/departments/");
  return data;
}

/** Karta bağlanabilecek kullanıcılar; `employeeId` verilirse o kartın kullanıcısı da listede. */
export async function listLinkableUsers(employeeId?: number): Promise<LinkedUser[]> {
  const { data } = await api.get<LinkedUser[]>("/personnel/linkable-users/", {
    params: { employee: employeeId },
  });
  return data;
}
