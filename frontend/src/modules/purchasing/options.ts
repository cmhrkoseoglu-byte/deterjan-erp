import { useQuery } from "@tanstack/react-query";
import { listRecords, type Material } from "../../api/masterdata";

/** Satın alınabilen malzemeler (hammadde ve ambalaj), temel birimleriyle. Mal kabul ekranıyla aynı
 * önbellek anahtarını kullanır. */
export function usePurchasableMaterials() {
  return useQuery({
    queryKey: ["options", "receivable-materials"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Material>("materials", {
        is_active: true,
        material_type__in: "RAW,PACKAGING",
        page_size: 500,
      });
      return page.results;
    },
  });
}
