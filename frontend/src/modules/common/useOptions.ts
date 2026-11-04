import { useQuery } from "@tanstack/react-query";
import { listRecords } from "../../api/masterdata";
import type { RelationSource } from "./forms";
import { ct } from "./strings";

interface CodeNamed {
  id: number;
  code: string;
  name: string;
  former_codes?: string[];
}

export interface Option {
  value: string;
  label: string;
}

/** Seçim kutusu seçenekleri: aktif kayıtlar, "KOD - Ad" biçiminde (en çok 500); kodu değişmiş
 * kayıtta eski kodlar da etikette yazar, böylece eski koduyla da aranır. */
export function useOptions(source: RelationSource | undefined) {
  return useQuery({
    queryKey: ["options", source?.endpoint, source?.params],
    enabled: Boolean(source),
    staleTime: 60_000,
    queryFn: async (): Promise<Option[]> => {
      const page = await listRecords<CodeNamed>(source!.endpoint, {
        is_active: true,
        page_size: 500,
        ...source!.params,
      });
      return page.results.map((row) => {
        const label = row.code === row.name ? row.code : `${row.code} - ${row.name}`;
        // Kodu değişmiş kayıt eski koduyla da aranabilsin (kodlama sistematiği).
        const former = row.former_codes?.length
          ? ` ${ct.formerLabel(row.former_codes.join(", "))}`
          : "";
        return { value: String(row.id), label: label + former };
      });
    },
  });
}
