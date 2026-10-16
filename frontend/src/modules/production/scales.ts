import { useQuery } from "@tanstack/react-query";
import { getScaleStatuses, type ScaleStatus } from "../../api/production";

const STORAGE_KEY = "uretim.terazi";

/** Bu tablette son seçilen terazi (cihaz başına hatırlanır). */
export function rememberedScale(): number | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value ? Number(value) : null;
  } catch {
    return null;
  }
}

export function remember(id: number | null) {
  try {
    if (id === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    // Tarayıcı depolaması kapalıysa seçim yalnızca bu sayfada kalır.
  }
}

export function scaleBlocked(row: ScaleStatus): boolean {
  return row.status === "OVERDUE" || row.is_down;
}

export function useScales() {
  return useQuery({
    queryKey: ["production", "scales"],
    queryFn: getScaleStatuses,
    staleTime: 60_000,
  });
}
