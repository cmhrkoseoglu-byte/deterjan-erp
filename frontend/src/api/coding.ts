// Kodlama sistematiği: /api/v1/coding/ (biçim ayarları yalnız admin; öneri türün yazma rollerine).
import { api } from "./client";

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
