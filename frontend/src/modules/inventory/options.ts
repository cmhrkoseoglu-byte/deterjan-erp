import { useQuery } from "@tanstack/react-query";
import { listRecords, type Location } from "../../api/masterdata";

export interface LocationOption {
  value: string;
  label: string;
  type: Location["location_type"];
}

/** Aktif lokasyonlar (seçim kutusu için). */
export function useLocations() {
  return useQuery({
    queryKey: ["options", "locations-typed"],
    staleTime: 60_000,
    queryFn: async (): Promise<LocationOption[]> => {
      const page = await listRecords<Location>("locations", { is_active: true, page_size: 500 });
      return page.results.map((row) => ({
        value: String(row.id),
        label: `${row.code} - ${row.name}`,
        type: row.location_type,
      }));
    },
  });
}

/** Seçim değeri ("12") → kimlik; boşsa null. */
export function idOrNull(value: string | null | undefined): number | null {
  return value ? Number(value) : null;
}
