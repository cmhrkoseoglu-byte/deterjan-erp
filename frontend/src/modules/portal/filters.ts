import { useDebouncedValue } from "@mantine/hooks";
import { useState } from "react";

export const PAGE_SIZE = 25;

/** Liste süzgeci: arama (gecikmeli), durum ve sayfa. */
export function useListFilters() {
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  return { search, setSearch, debounced, status, setStatus, page, setPage };
}

export type ListFilterState = ReturnType<typeof useListFilters>;
