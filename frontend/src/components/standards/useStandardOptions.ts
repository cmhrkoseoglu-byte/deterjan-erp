import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getStandards, standardsQueryKey } from "../../api/standards";

export interface CodeOption {
  value: string;
  label: string;
}

/**
 * Kod listesinden seçenekler: "Almanya (DE)", "Türkçe (tr)". Ad tarayıcının Türkçe adıdır
 * (Intl.DisplayNames); bilinmeyen kodda yalnız kod yazar. Ada göre Türkçe sıralanır.
 */
export function codeOptions(codes: readonly string[], type: "region" | "language"): CodeOption[] {
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames(["tr"], { type, fallback: "none" });
  } catch {
    names = null;
  }
  const options = codes.map((code) => {
    let name: string | undefined;
    try {
      name = names?.of(code);
    } catch {
      name = undefined;
    }
    return { value: code, label: name && name !== code ? `${name} (${code})` : code };
  });
  return options.sort((a, b) => a.label.localeCompare(b.label, "tr"));
}

/** Seçili değer listede yoksa (eski kayıt) seçeneklere eklenir; böylece alanda görünür. */
export function withValue(options: CodeOption[], value: string | null): CodeOption[] {
  if (!value || options.some((option) => option.value === value)) return options;
  return [{ value, label: value }, ...options];
}

/** Ülke ve dil seçenekleri (sunucudaki ISO listeleri; oturum boyunca bir kez yüklenir). */
export function useStandardOptions() {
  const query = useQuery({
    queryKey: standardsQueryKey,
    queryFn: getStandards,
    staleTime: Infinity,
  });
  const data = query.data;
  return useMemo(
    () => ({
      countries: data ? codeOptions(data.countries, "region") : [],
      languages: data ? codeOptions(data.languages, "language") : [],
      defaultCountry: data?.default_country ?? "TR",
      defaultLanguage: data?.default_language ?? "tr",
    }),
    [data],
  );
}
