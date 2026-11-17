import type { CurrentUser } from "../api/types";
import type { RelatedRecord } from "../api/workflow";
import { canOpenPage, type PageKey, type PageParams } from "../auth/pageAccess";

/**
 * Kayıt türü ("app_label.model") → detay sayfası adresi. Görev ve bildirimlerdeki
 * "Kayda git" bağlantısı buradan çözülür. Her modül kendi detay sayfasını ekler, ör.:
 *
 *   "inventory.lot": (id) => `/depo/lotlar/${id}`,
  "golive.problemreport": (id) => `/gecis/sorunlar/${id}`,
 *   "production.productionorder": (id) => `/uretim/emirler/${id}`,
 */
export const RECORD_ROUTES: Record<string, (id: number) => string> = {
  "inventory.lot": (id) => `/depo/lotlar/${id}`,
  "golive.problemreport": (id) => `/gecis/sorunlar/${id}`,
  "inventory.goodsreceipt": (id) => `/depo/mal-kabul/${id}`,
  "inventory.stockadjustment": (id) => `/depo/sayim/${id}`,
  "production.productionorder": (id) => `/uretim/emirler/${id}`,
  "production.productionbatch": (id) => `/uretim/sarjlar/${id}`,
  "filling.fillingorder": (id) => `/dolum/emirler/${id}`,
  "filling.fillingrun": (id) => `/dolum/partiler/${id}`,
  "filling.packagingspec": (id) => `/dolum/ambalaj-receteleri/${id}`,
  "quality.sample": (id) => `/kalite/numuneler/${id}`,
  "returns.customerreturn": (id) => `/iadeler/${id}`,
  "quality.specification": (id) => `/kalite/spesifikasyonlar/${id}`,
  "sales.salesorder": (id) => `/sevkiyat/siparisler/${id}`,
  "purchasing.purchaseorder": (id) => `/satin-alma/siparisler/${id}`,
  "purchasing.purchaserequest": () => "/satin-alma/talepler",
  "sales.shipment": (id) => `/sevkiyat/sevkiyatlar/${id}`,
  "maintenance.maintenanceworkorder": (id) => `/bakim/is-emirleri/${id}`,
  "hse.incident": (id) => `/isg/olaylar/${id}`,
  "hse.wasterecord": () => "/isg/atik",
  "hse.safetydatasheet": () => "/isg/gbf",
  "reporting.reportjob": () => "/raporlar/indirmeler",
};

/** Kaydın detay sayfası; sayfası henüz yoksa null. */
export function recordPath(related: RelatedRecord | null | undefined): string | null {
  if (!related) return null;
  const route = RECORD_ROUTES[related.model];
  return route ? route(related.id) : null;
}

/**
 * Kayıt türü → detay sayfasının koruması (`auth/pageAccess.ts`; `routes.tsx` aynı kuralları
 * kullanır). Kayıt bağlantısı ve "Kayda git" yalnız açılabilecek sayfaya gider (plan §5.9, §8
 * madde 2). Sekmeye giden bağlantılarda (ör. `/isg/gbf`) yalnız modül sayfası sayılır: görünmeyen
 * sekme modülün ilk sekmesine döner.
 */
export const RECORD_PAGES: Readonly<Record<string, readonly [PageKey, PageParams?]>> = {
  "inventory.lot": ["inventoryLot"],
  "golive.problemreport": ["goliveProblem"],
  "inventory.goodsreceipt": ["inventoryReceipt"],
  "inventory.stockadjustment": ["inventoryAdjustment"],
  "production.productionorder": ["productionOrder"],
  "production.productionbatch": ["production"],
  "filling.fillingorder": ["fillingOrder"],
  "filling.fillingrun": ["filling"],
  "filling.packagingspec": ["fillingSpec"],
  "quality.sample": ["quality"],
  "returns.customerreturn": ["returns"],
  "quality.specification": ["qualitySpec"],
  "sales.salesorder": ["sales"],
  "purchasing.purchaseorder": ["purchaseOrder"],
  "purchasing.purchaserequest": ["purchasing"],
  "sales.shipment": ["sales"],
  "maintenance.maintenanceworkorder": ["maintenance"],
  "hse.incident": ["hse"],
  "hse.wasterecord": ["hse"],
  "hse.safetydatasheet": ["hse"],
  "reporting.reportjob": ["reporting", { tab: "indirmeler" }],
};

/**
 * Kaydın detay sayfası bu kullanıcıya açılır mı? Koruması tanımlı olmayan kayıt türünde sayfa
 * kendi korumasına bırakılır (`true`).
 */
export function canOpenRecord(
  user: CurrentUser | null | undefined,
  model: string,
  id?: number | string,
): boolean {
  if (!user) return false;
  const target = RECORD_PAGES[model];
  if (!target) return true;
  const [page, params] = target;
  return canOpenPage(user, page, { ...params, ...(id === "yeni" ? { orderId: "yeni" } : {}) });
}

/** Görev ya da bildirimin kaydı: sayfası varsa ve kullanıcı açabiliyorsa adresi, yoksa null. */
export function openableRecordPath(
  user: CurrentUser | null | undefined,
  related: RelatedRecord | null | undefined,
): string | null {
  const path = recordPath(related);
  return path && related && canOpenRecord(user, related.model, related.id) ? path : null;
}
