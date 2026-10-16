import { MultiSelect, Select } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getLot, listLots } from "../../api/inventory";
import { tt } from "./strings";

interface Option {
  value: string;
  label: string;
}

/** Lot arama: lot no ya da malzeme yazılır (barkod okuyucu da yazar). */
function useLotSearch(selected: string[]) {
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const found = useQuery({
    queryKey: ["traceability", "lot-search", debounced],
    queryFn: () => listLots({ search: debounced, page_size: 20 }),
    enabled: debounced.trim().length >= 2,
  });
  // Adresten gelen seçili lotların etiketleri.
  const picked = useQuery({
    queryKey: ["traceability", "lot-labels", selected],
    enabled: selected.length > 0,
    staleTime: 60_000,
    queryFn: () => Promise.all(selected.map((id) => getLot(Number(id)))),
  });
  const label = (lot: { lot_no: string; material_code: string; material_name: string }) =>
    `${lot.lot_no} · ${lot.material_code} - ${lot.material_name}`;
  const options: Option[] = (found.data?.results ?? []).map((lot) => ({
    value: String(lot.id),
    label: label(lot),
  }));
  for (const lot of picked.data ?? []) {
    if (!options.some((option) => option.value === String(lot.id))) {
      options.unshift({ value: String(lot.id), label: label(lot) });
    }
  }
  for (const id of selected) {
    if (!options.some((option) => option.value === id)) options.unshift({ value: id, label: id });
  }
  return {
    options,
    search,
    setSearch,
    nothingFound: debounced.trim().length >= 2 ? tt.notFound : undefined,
  };
}

export function LotPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const { options, search, setSearch, nothingFound } = useLotSearch(value ? [value] : []);
  return (
    <Select
      label={tt.lot}
      placeholder={tt.lotSearch}
      searchable
      clearable
      filter={({ options: all }) => all}
      data={options}
      value={value}
      searchValue={search}
      onSearchChange={setSearch}
      nothingFoundMessage={nothingFound}
      onChange={onChange}
      maw={520}
    />
  );
}

export function LotMultiPicker({
  value,
  onChange,
}: {
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const { options, search, setSearch, nothingFound } = useLotSearch(value);
  return (
    <MultiSelect
      label={tt.lots}
      placeholder={tt.lotSearch}
      searchable
      clearable
      filter={({ options: all }) => all}
      data={options}
      value={value}
      searchValue={search}
      onSearchChange={setSearch}
      nothingFoundMessage={nothingFound}
      onChange={onChange}
      maw={720}
    />
  );
}
