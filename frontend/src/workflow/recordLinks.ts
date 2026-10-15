import type { RelatedRecord } from "../api/workflow";

/**
 * Kayıt türü ("app_label.model") → detay sayfası adresi. Görev ve bildirimlerdeki
 * "Kayda git" bağlantısı buradan çözülür. Her modül kendi detay sayfasını ekler, ör.:
 *
 *   "inventory.lot": (id) => `/depo/lotlar/${id}`,
 *   "production.productionorder": (id) => `/uretim/emirler/${id}`,
 */
export const RECORD_ROUTES: Record<string, (id: number) => string> = {
  "inventory.lot": (id) => `/depo/lotlar/${id}`,
  "inventory.goodsreceipt": (id) => `/depo/mal-kabul/${id}`,
  "inventory.stockadjustment": (id) => `/depo/sayim/${id}`,
  "production.productionorder": (id) => `/uretim/emirler/${id}`,
  "production.productionbatch": (id) => `/uretim/sarjlar/${id}`,
};

/** Kaydın detay sayfası; sayfası henüz yoksa null. */
export function recordPath(related: RelatedRecord | null | undefined): string | null {
  if (!related) return null;
  const route = RECORD_ROUTES[related.model];
  return route ? route(related.id) : null;
}
