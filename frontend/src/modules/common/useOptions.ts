import { useQuery } from "@tanstack/react-query";
import { listRecords } from "../../api/masterdata";
import type { RelationSource } from "./forms";
import { ct } from "./strings";

/** Kodlu kayıt; kodu değişmiş kayıtta liste uçları eski kodları da döner (`former_codes`). */
export interface CodeNamed {
  code: string;
  name: string;
  former_codes?: string[];
}

export interface Option {
  value: string;
  label: string;
}

/**
 * Seçim kutusu etiketi: "KOD - Ad" (kod adla aynıysa yalnız kod), ardından `detail` (ör. " (v2)").
 * Kodu değişmiş kayıtta eski kodlar da yazar, böylece eski koduyla da aranır (kodlama
 * sistematiği). Kodlu ana veriden elle kurulan bütün seçenek listeleri bunu kullanır.
 */
export function optionLabel(row: CodeNamed, detail = ""): string {
  const label = row.code === row.name ? row.code : `${row.code} - ${row.name}`;
  const former = row.former_codes?.length ? ` ${ct.formerLabel(row.former_codes.join(", "))}` : "";
  return `${label}${detail}${former}`;
}

/** Seçim kutusu seçenekleri: aktif kayıtlar, `optionLabel` biçiminde (en çok 500). */
export function useOptions(source: RelationSource | undefined) {
  return useQuery({
    queryKey: ["options", source?.endpoint, source?.params],
    enabled: Boolean(source),
    staleTime: 60_000,
    queryFn: async (): Promise<Option[]> => {
      const page = await listRecords<CodeNamed & { id: number }>(source!.endpoint, {
        is_active: true,
        page_size: 500,
        ...source!.params,
      });
      return page.results.map((row) => ({ value: String(row.id), label: optionLabel(row) }));
    },
  });
}
