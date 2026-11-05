// /api/v1/standards/: uluslararası kod listeleri. Ülke ISO 3166-1 alpha-2 (cari), dil ISO 639-1
// (GBF). Listeler sunucudadır; ekran adları tarayıcının Türkçe adlarıdır (Intl.DisplayNames).
import { api } from "./client";

export interface Standards {
  countries: string[];
  languages: string[];
  default_country: string;
  default_language: string;
}

export const standardsQueryKey = ["standards"] as const;

export async function getStandards(): Promise<Standards> {
  const { data } = await api.get<Standards>("/standards/");
  return data;
}
