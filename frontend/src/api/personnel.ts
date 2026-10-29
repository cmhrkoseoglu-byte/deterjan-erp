// /api/v1/personnel/* (admin ve yönetim): personel kartları ve özlük belgeleri. Kişisel veri
// (docs/KVKK.md). Kart silinmez: işten ayrılış `terminate`, yeniden işe başlama `reinstate` ile
// kaydedilir; belge `remove` ile kaldırılır.
import { api } from "./client";
import type { Paginated } from "./types";
import type { AuditEntry } from "./workflow";

export interface LinkedUser {
  id: number;
  username: string;
  full_name: string;
  is_active: boolean;
}

export type EducationLevel =
  "PRIMARY" | "MIDDLE" | "HIGH_SCHOOL" | "ASSOCIATE" | "BACHELOR" | "MASTER" | "DOCTORATE";

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
  /** Kartta açık görünür; denetim günlüğünde maskelidir. */
  national_id: string;
  birth_date: string | null;
  birth_place: string;
  /** En son mezuniyet; boşsa girilmemiş. */
  education_level: EducationLevel | "";
  education_level_display: string;
  school: string;
  field_of_study: string;
  graduation_year: number | null;
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
  | "national_id"
  | "birth_date"
  | "birth_place"
  | "education_level"
  | "school"
  | "field_of_study"
  | "graduation_year"
  | "user"
>;

export type EmployeeDocumentKind = "ID_COPY" | "PAYROLL" | "CONTRACT" | "DIPLOMA";

export interface EmployeeDocument {
  id: number;
  employee: number;
  kind: EmployeeDocumentKind;
  kind_display: string;
  original_name: string;
  size: number;
  mime_type: string;
  /** Bordro dönemi (ayın ilk günü). */
  period: string | null;
  /** Sözleşmenin başlangıcı ve bitişi (belirsiz sürelide bitiş boş). */
  valid_from: string | null;
  valid_until: string | null;
  note: string;
  uploaded_by_name: string | null;
  created_at: string;
  /** Dosya bu adresten açılır; her açılış kartın geçmişine yazılır. */
  download_url: string;
}

export interface EmployeeDocumentInput {
  kind: EmployeeDocumentKind;
  file: File;
  /** Bordro dönemi: "2026-09". */
  period?: string;
  valid_from?: string;
  valid_until?: string;
  note?: string;
}

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
 * invalid_national_id, national_id_taken, invalid_birth_date, invalid_graduation_year,
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

/** Kartın özlük belgeleri (kaldırılanlar hariç); bordrolar döneme göre en yenisi önce. */
export async function listEmployeeDocuments(employeeId: number): Promise<EmployeeDocument[]> {
  const { data } = await api.get<EmployeeDocument[]>("/personnel/documents/", {
    params: { employee: employeeId },
  });
  return data;
}

/** Belge ekler. Hata kodları: period_required, valid_from_required, invalid_contract_dates,
 * file_type_not_allowed, file_empty, file_too_large, validation_error. */
export async function uploadEmployeeDocument(
  employeeId: number,
  input: EmployeeDocumentInput,
): Promise<EmployeeDocument> {
  const form = new FormData();
  form.append("employee", String(employeeId));
  form.append("kind", input.kind);
  form.append("file", input.file, input.file.name);
  if (input.period) form.append("period", input.period);
  if (input.valid_from) form.append("valid_from", input.valid_from);
  if (input.valid_until) form.append("valid_until", input.valid_until);
  if (input.note) form.append("note", input.note);
  const { data } = await api.post<EmployeeDocument>("/personnel/documents/", form);
  return data;
}

/** Belgeyi kaldırır (silinmez; artık açılamaz). Neden zorunludur. */
export async function removeEmployeeDocument(
  id: number,
  reason: string,
): Promise<EmployeeDocument> {
  const { data } = await api.post<EmployeeDocument>(`/personnel/documents/${id}/remove/`, {
    reason,
  });
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
