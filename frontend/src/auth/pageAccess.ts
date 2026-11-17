import type { CurrentUser, RequiredAccess } from "../api/types";
import { can, canRead, isAdminUser, moduleVisible } from "./access";
import { hasAnyRole } from "./roles";

/**
 * Sayfa korumalarının tek tablosu (plan §5.9 "Rota korumaları"). `routes.tsx` her sayfayı
 * `<RequirePage page="...">` ile buradaki kurala bağlar; kayıt bağlantıları (`RecordLink`,
 * "Kayda git") aynı kurala bakarak hedef sayfa açılmayacaksa düz metin olur. Bu dosya sayfa
 * bileşenlerini ve `routes.tsx`'i import etmez (döngü olmasın).
 *
 * - Modül sayfaları ve birden çok bölümün kayıtlarını gösteren alt sayfalar: modülün ekranı olan
 *   bölümlerinin birleşimi (`moduleVisible`).
 * - Tek bölüme ait alt sayfalar: o bölümün Görür'ü.
 * - Depo'nun belge sayfaları: kayıt okuması (`r`).
 * - Yeni üretim ve dolum emri sayfası (`.../emirler/yeni`): emir Değiştirir'i (§8 madde 3).
 * - `/raporlar/indirmeler` herkese açık; Panolar ve raporlar'ın kalanı modülün birleşimi.
 */

/** Rota parametreleri (`useParams`). */
export type PageParams = Readonly<Record<string, string | undefined>>;

export interface PageRule {
  /** Sayfa bu kullanıcıya açılır mı? */
  allow: (user: CurrentUser, params: PageParams) => boolean;
  /** Açılmazsa "Yetkiniz yok" sayfasında gösterilecek gereken yetki. */
  need: (params: PageParams, user?: CurrentUser) => RequiredAccess[];
}

const NO_NEED = (): RequiredAccess[] => [];

/** Modül sayfası: modülün ekranı olan bölümlerinden birinde Görür. */
function modulePage(moduleKey: string): PageRule {
  return {
    allow: (user) => moduleVisible(user, moduleKey),
    need: () => [{ key: moduleKey, level: "view" }],
  };
}

/** Tek bölüme ait sayfa: bölümün Görür'ü. */
function sectionPage(key: string): PageRule {
  return {
    allow: (user) => can(user, key, "view"),
    need: () => [{ key, level: "view" }],
  };
}

/** Kayıt sayfası: bölümün kayıt okuması. */
function readPage(key: string): PageRule {
  return {
    allow: (user) => canRead(user, key),
    need: () => [{ key, level: "read" }],
  };
}

/** Var olan emir modülün birleşimiyle, yeni emir sayfası emir Değiştirir'iyle açılır. */
function orderPage(moduleKey: string, ordersKey: string, param: string): PageRule {
  const module = modulePage(moduleKey);
  return {
    allow: (user, params) =>
      params[param] === "yeni" ? can(user, ordersKey, "change") : module.allow(user, params),
    need: (params) =>
      params[param] === "yeni" ? [{ key: ordersKey, level: "change" }] : module.need(params),
  };
}

const signedIn: PageRule = { allow: () => true, need: NO_NEED };

export const PAGE_RULES = {
  masterdata: modulePage("masterdata"),
  recipes: sectionPage("recipes.recipes"),
  inventory: modulePage("inventory"),
  inventoryLot: readPage("inventory.lots"),
  inventoryReceipt: readPage("inventory.receipts"),
  inventoryAdjustment: readPage("inventory.adjustments"),
  production: modulePage("production"),
  productionOrder: orderPage("production", "production.orders", "orderId"),
  quality: modulePage("quality"),
  qualitySpec: sectionPage("quality.specs"),
  filling: modulePage("filling"),
  fillingOrder: orderPage("filling", "filling.orders", "orderId"),
  fillingSpec: sectionPage("filling.specs"),
  sales: modulePage("sales"),
  returns: modulePage("returns"),
  purchasing: modulePage("purchasing"),
  purchaseOrder: sectionPage("purchasing.orders"),
  traceability: sectionPage("traceability.trace"),
  costing: modulePage("costing"),
  lotCost: sectionPage("costing.lot_costs"),
  maintenance: modulePage("maintenance"),
  hse: modulePage("hse"),
  personnelCards: sectionPage("personnel.cards"),
  personnelAttendance: sectionPage("personnel.attendance"),
  personnelWages: sectionPage("personnel.wages"),
  personnelPayroll: sectionPage("personnel.payroll"),
  reporting: {
    allow: (user, params) => params.tab === "indirmeler" || moduleVisible(user, "reporting"),
    need: (params) => (params.tab === "indirmeler" ? [] : [{ key: "reporting", level: "view" }]),
  },
  golive: modulePage("golive"),
  goliveComparison: sectionPage("golive.comparisons"),
  /** Sorun bildirimi: bildiren ve admin açar (satır kuralı backend'de). */
  goliveProblem: signedIn,
  /** Sistem: yalnız admin. */
  system: { allow: (user) => isAdminUser(user), need: NO_NEED },
  /** Yönetim panosu: yönetim rolü (rol görünümü) ve Yönetim panosu: Görür (plan §3.15, §5.9). */
  dashboard: {
    allow: (user) => hasAnyRole(user, ["yonetim"]) && can(user, "reporting.management", "view"),
    // Yalnız rol eksikse gereken bölüm yetkisi yoktur (Sistem sayfası gibi satır çıkmaz).
    need: (_params, user) =>
      can(user, "reporting.management", "view")
        ? []
        : [{ key: "reporting.management", level: "view" }],
  },
} satisfies Record<string, PageRule>;

export type PageKey = keyof typeof PAGE_RULES;

/** Sayfa bu kullanıcıya açılır mı? Oturum yoksa hayır. */
export function canOpenPage(
  user: CurrentUser | null | undefined,
  page: PageKey,
  params: PageParams = {},
): boolean {
  return Boolean(user) && PAGE_RULES[page].allow(user!, params);
}

/** Personel sayfaları, menü bağlantısının tercih sırasıyla. */
const PERSONNEL_PAGES: readonly [PageKey, string][] = [
  ["personnelCards", "/personel"],
  ["personnelAttendance", "/personel/puantaj"],
  ["personnelWages", "/personel/ucretler"],
  ["personnelPayroll", "/personel/bordro"],
];

/**
 * Personel menü bağlantısı: Personel kartları'nı göremeyen kişi açabildiği ilk personel sayfasına
 * gider (plan §5.9). Varsayılan paketlerde her zaman `/personel`.
 */
export function personnelPath(user: CurrentUser | null | undefined): string {
  return PERSONNEL_PAGES.find(([page]) => canOpenPage(user, page))?.[1] ?? "/personel";
}

/** Personel menüsü yalnız açılabilen bir personel sayfası varsa görünür (ayarların sayfası yok). */
export function canOpenAnyPersonnelPage(user: CurrentUser | null | undefined): boolean {
  return PERSONNEL_PAGES.some(([page]) => canOpenPage(user, page));
}
