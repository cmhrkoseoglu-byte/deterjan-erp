// Kodlama sistematiği: /api/v1/coding/ (biçim ayarları yalnız admin; öneri türün yazma rollerine).
import { api } from "./client";
import type { Paginated } from "./types";

/** Yeni kayıt için sıradaki kod (biçim etkinse). `format` biçimin örneği: "MLZ-0000000". */
export interface CodeSuggestion {
  key: string;
  active: boolean;
  code: string | null;
  format: string;
}

export async function suggestCode(key: string, type?: string): Promise<CodeSuggestion> {
  const { data } = await api.get<CodeSuggestion>(`/coding/suggest/${key}/`, {
    params: type ? { type } : {},
  });
  return data;
}

export type CodeKind = "master" | "document" | "lot" | "standard";
export type YearFormat = "YYYY" | "YY";
export type DateFormat = "YYYYMMDD" | "YYYYDDD" | "YYMMDD";

/** Türe göre önekli kodda (ekipman) her türün satırı. */
export interface CodeTypeOption {
  value: string;
  label: string;
  prefix: string;
  format: string;
  next: string;
  last_number: number;
}

/** Kodlama ekranındaki tür satırı. */
export interface CodeTypeRow {
  key: string;
  kind: CodeKind;
  label: string;
  configurable: boolean;
  locked: boolean;
  free: boolean;
  scanned: boolean;
  prefix: string;
  width: number;
  type_field: string;
  type_prefixes: Record<string, string>;
  year_format: string;
  date_format: string;
  is_active: boolean;
  revision: number;
  updated_at: string | null;
  updated_by: string;
  /** Biçimin örneği: "MLZ-0000000", "UE-2026-00000". */
  format: string;
  next: string;
  longest: string;
  last_number: number;
  types: CodeTypeOption[];
  samples: string[];
}

/** Biçim değerleri (verilmeyen değişmez). */
export interface CodeFormatValues {
  prefix?: string;
  width?: number;
  type_prefixes?: Record<string, string>;
  year_format?: YearFormat;
  date_format?: DateFormat;
}

export interface CodeSchemeUpdate extends CodeFormatValues {
  is_active?: boolean;
  /** Ana veride sıradaki numara: {"MLZ": 25}. */
  counters?: Record<string, number>;
  note: string;
}

export interface CodePreview {
  valid: boolean;
  error: { code: string; detail: string } | null;
  example: CodeTypeRow | null;
}

export interface CodeSchemeRevision {
  id: number;
  key: string;
  label: string;
  revision: number;
  prefix: string;
  type_prefixes: Record<string, string>;
  width: number;
  year_format: string;
  date_format: string;
  is_active: boolean;
  counters: Record<string, number>;
  note: string;
  changed_at: string;
  changed_by_name: string;
}

export async function listCodeTypes(kind?: CodeKind): Promise<CodeTypeRow[]> {
  const { data } = await api.get<Paginated<CodeTypeRow>>("/coding/types/", {
    params: { page_size: 200, ...(kind ? { kind } : {}) },
  });
  return data.results;
}

export async function updateCodeType(key: string, body: CodeSchemeUpdate): Promise<CodeTypeRow> {
  const { data } = await api.put<CodeTypeRow>(`/coding/types/${key}/`, body);
  return data;
}

export async function previewCodeType(key: string, values: CodeFormatValues): Promise<CodePreview> {
  const { data } = await api.post<CodePreview>(`/coding/types/${key}/preview/`, values);
  return data;
}

export async function listCodeRevisions(page = 1): Promise<Paginated<CodeSchemeRevision>> {
  const { data } = await api.get<Paginated<CodeSchemeRevision>>("/coding/revisions/", {
    params: { page },
  });
  return data;
}
