import {
  IconBuildingFactory2,
  IconChartBar,
  IconChecklist,
  IconCoin,
  IconDatabase,
  IconListDetails,
  IconArrowBackUp,
  IconFlask,
  IconHelp,
  IconLayoutDashboard,
  IconRocket,
  IconRoute,
  IconServer,
  IconPackages,
  IconReportMoney,
  IconBottle,
  IconSettings,
  IconShieldCheck,
  IconShoppingCart,
  IconTool,
  IconTruckDelivery,
  IconUsers,
  type Icon,
} from "@tabler/icons-react";
import type { CurrentUser } from "../api/types";
import { can, isAdminUser, moduleVisible } from "../auth/access";
import { canOpenAnyPersonnelPage, canOpenPage, personnelPath } from "../auth/pageAccess";
import { DASHBOARD_PATH, TASKS_PATH } from "../auth/paths";
import { tr } from "../i18n/tr";

export interface MenuItem {
  key: string;
  label: string;
  path: string;
  icon: Icon;
  /**
   * Öğeyi kim görür (plan §2, §5.9): modül, ekranı olan bölümlerinden birinde Görür'ü olana
   * (`moduleVisible`); Görevlerim ve Yardım herkese; Sistem ve yönetim paneli yalnız admine.
   */
  visible: (user: CurrentUser) => boolean;
  /** Modülün ekleneceği faz; sayfa hazır olana kadar yer tutucu gösterilir. */
  phase?: number;
  /** Uygulama dışı bağlantı (Django yönetim paneli gibi). */
  external?: boolean;
}

// Menünün tek kaynağı. Görünürlük `me.access`'ten (`auth/access.ts`).
const everyone = () => true;

/** Modülün menü öğesi: ekranı olan bölümlerinden birinde Görür. */
function module(key: string) {
  return (user: CurrentUser) => moduleVisible(user, key);
}

export const MENU: readonly MenuItem[] = [
  {
    key: "dashboard",
    label: tr.menu.dashboard,
    path: DASHBOARD_PATH,
    icon: IconLayoutDashboard,
    // Yönetimin açılış ekranı. Aynı pano planlamaya Panolar ve raporlar'da açıktır.
    visible: (user) => canOpenPage(user, "dashboard"),
  },
  { key: "home", label: tr.menu.home, path: TASKS_PATH, icon: IconChecklist, visible: everyone },
  {
    key: "masterdata",
    label: tr.menu.masterdata,
    path: "/ana-veriler",
    icon: IconDatabase,
    visible: module("masterdata"),
    phase: 1,
  },
  {
    key: "recipes",
    label: tr.menu.recipes,
    path: "/receteler",
    icon: IconListDetails,
    visible: (user) => can(user, "recipes.recipes"),
    phase: 1,
  },
  {
    key: "inventory",
    label: tr.menu.inventory,
    path: "/depo",
    icon: IconPackages,
    // Stok sorgu, lot ve palet herkese açık; sekmeler yetkiyle daralır (InventoryPage).
    visible: module("inventory"),
    phase: 1,
  },
  {
    key: "production",
    label: tr.menu.production,
    path: "/uretim",
    icon: IconBuildingFactory2,
    visible: module("production"),
    phase: 1,
  },
  {
    key: "quality",
    label: tr.menu.quality,
    path: "/kalite",
    icon: IconFlask,
    visible: module("quality"),
    phase: 2,
  },
  {
    key: "filling",
    label: tr.menu.filling,
    path: "/dolum",
    icon: IconBottle,
    visible: module("filling"),
    phase: 2,
  },
  {
    key: "sales",
    label: tr.menu.sales,
    path: "/sevkiyat",
    icon: IconTruckDelivery,
    // Planlama ve depo siparişleri ve rezervasyonları görür (yazma sevkiyat ve yönetimde).
    visible: module("sales"),
    phase: 3,
  },
  {
    key: "returns",
    label: tr.menu.returns,
    path: "/iadeler",
    icon: IconArrowBackUp,
    // Depo da görür: teslim alır ve imha eder.
    visible: module("returns"),
    phase: 3,
  },
  {
    key: "traceability",
    label: tr.menu.traceability,
    path: "/izlenebilirlik",
    icon: IconRoute,
    visible: (user) => can(user, "traceability.trace"),
    phase: 3,
  },
  {
    key: "purchasing",
    label: tr.menu.purchasing,
    path: "/satin-alma",
    icon: IconShoppingCart,
    // Depo siparişleri (tutarsız) ve beklenen teslimatları görür; planlama ve üretim talep açar.
    visible: module("purchasing"),
    phase: 4,
  },
  {
    key: "ledger",
    label: tr.menu.ledger,
    path: "/cari-hesaplar",
    icon: IconReportMoney,
    // Müşteri carileri yönetim ve sevkiyatta, tedarikçi carileri yönetim ve satın almada.
    visible: module("ledger"),
    phase: 4,
  },
  {
    key: "costing",
    label: tr.menu.costing,
    path: "/maliyet",
    icon: IconCoin,
    // Maliyet tutarlarını yalnızca yönetim (ve admin) görür (Karar D-15).
    visible: module("costing"),
    phase: 4,
  },
  {
    key: "maintenance",
    label: tr.menu.maintenance,
    path: "/bakim",
    icon: IconTool,
    // Arıza bildirimi her rolde açıktır (ana sayfadaki düğme); bakım ekranları bu birimlere.
    visible: module("maintenance"),
    phase: 4,
  },
  {
    key: "hse",
    label: tr.menu.hse,
    path: "/isg",
    icon: IconShieldCheck,
    // Olay / ramak kala bildirimi ve tehlike bilgileri rolü olan herkese açık (rolsüzde yok).
    visible: module("hse"),
    phase: 4,
  },
  {
    key: "personnel",
    label: tr.menu.personnel,
    path: "/personel",
    icon: IconUsers,
    // Personel bilgileri kişisel veri: yalnızca yönetim rolündekilere verilebilir (docs/KVKK.md).
    // Personel ayarları'nın kendi sayfası yok: menü açılabilen bir personel sayfası ister.
    visible: canOpenAnyPersonnelPage,
  },
  {
    key: "reporting",
    label: tr.menu.reporting,
    path: "/raporlar",
    icon: IconChartBar,
    // Her rolün en az bir panosu ya da raporu var (rolsüzde yok; İndirmeler herkese açık).
    visible: module("reporting"),
    phase: 4,
  },
  {
    key: "golive",
    label: tr.menu.golive,
    path: "/gecis",
    icon: IconRocket,
    // Hazırlık listesi ve paralel çalışma stok karşılaştırması (Faz 5, Adım 5.6).
    visible: module("golive"),
    phase: 5,
  },
  {
    key: "help",
    label: tr.menu.help,
    path: "/yardim",
    icon: IconHelp,
    // Rol bazında kullanım kılavuzları; herkes kendi rolünün kılavuzunu görür.
    visible: everyone,
    phase: 5,
  },
  {
    key: "system",
    label: tr.menu.system,
    path: "/sistem",
    icon: IconServer,
    // Sistem durumu, yedekler, kullanıcı kilidi ve 2FA sıfırlama, saha tableti işareti.
    visible: isAdminUser,
    phase: 5,
  },
  {
    key: "admin",
    label: tr.menu.adminPanel,
    path: "/admin/",
    icon: IconSettings,
    visible: isAdminUser,
    external: true,
  },
];

export function visibleMenu(user: CurrentUser | null): MenuItem[] {
  if (!user) return [];
  return MENU.filter((item) => item.visible(user)).map((item) =>
    // Personel kartları'nı göremeyen kişi açabildiği ilk personel sayfasına gider (plan §5.9).
    item.key === "personnel" ? { ...item, path: personnelPath(user) } : item,
  );
}
