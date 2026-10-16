import { useQuery } from "@tanstack/react-query";
import { listRecords, type Equipment } from "../../api/masterdata";

/** Aktif ekipman (seçim kutusu için). */
export function useEquipmentOptions() {
  return useQuery({
    queryKey: ["options", "equipment"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Equipment>("equipment", { is_active: true, page_size: 500 });
      return page.results;
    },
  });
}

export function equipmentLabel(row: { code: string; name: string }): string {
  return `${row.code} - ${row.name}`;
}

/** Boş maddeler atılır. */
export function cleanItems(items: string[]): string[] {
  return items.map((item) => item.trim()).filter(Boolean);
}
