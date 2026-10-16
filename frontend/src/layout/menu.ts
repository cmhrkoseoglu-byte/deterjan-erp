import {
  IconBuildingFactory2,
  IconChartBar,
  IconChecklist,
  IconCoin,
  IconDatabase,
  IconListDetails,
  IconArrowBackUp,
  IconFlask,
  IconRoute,
  IconPackages,
  IconBottle,
  IconSettings,
  IconShoppingCart,
  IconTruckDelivery,
  type Icon,
} from "@tabler/icons-react";
import type { CurrentUser, Role } from "../api/types";
import { hasAnyRole } from "../auth/roles";
import { tr } from "../i18n/tr";

export interface MenuItem {
  key: string;
  label: string;
  path: string;
  icon: Icon;
  /** Boşsa her giriş yapmış kullanıcı görür. `admin` her öğeyi görür. */
  roles: readonly Role[];
  /** Modülün ekleneceği faz; sayfa hazır olana kadar yer tutucu gösterilir. */
  phase?: number;
  /** Uygulama dışı bağlantı (Django yönetim paneli gibi). */
  external?: boolean;
}

// Menünün tek kaynağı. Rol listesi CLAUDE.md §5'teki rollerdir.
export const MENU: readonly MenuItem[] = [
  { key: "home", label: tr.menu.home, path: "/", icon: IconChecklist, roles: [] },
  {
    key: "masterdata",
    label: tr.menu.masterdata,
    path: "/ana-veriler",
    icon: IconDatabase,
    roles: ["planlama", "yonetim"],
    phase: 1,
  },
  {
    key: "recipes",
    label: tr.menu.recipes,
    path: "/receteler",
    icon: IconListDetails,
    roles: ["planlama", "laboratuvar"],
    phase: 1,
  },
  {
    key: "inventory",
    label: tr.menu.inventory,
    path: "/depo",
    icon: IconPackages,
    // Stok sorgu ve lot detayı herkese açık; sekmeler rolle daralır (InventoryPage).
    roles: [],
    phase: 1,
  },
  {
    key: "production",
    label: tr.menu.production,
    path: "/uretim",
    icon: IconBuildingFactory2,
    roles: ["uretim", "planlama", "depo", "yonetim"],
    phase: 1,
  },
  {
    key: "quality",
    label: tr.menu.quality,
    path: "/kalite",
    icon: IconFlask,
    roles: ["laboratuvar", "yonetim"],
    phase: 2,
  },
  {
    key: "filling",
    label: tr.menu.filling,
    path: "/dolum",
    icon: IconBottle,
    roles: ["dolum", "planlama", "depo", "yonetim"],
    phase: 2,
  },
  {
    key: "sales",
    label: tr.menu.sales,
    path: "/sevkiyat",
    icon: IconTruckDelivery,
    // Planlama ve depo siparişleri ve rezervasyonları görür (yazma sevkiyat ve yönetimde).
    roles: ["sevkiyat", "yonetim", "planlama", "depo"],
    phase: 3,
  },
  {
    key: "returns",
    label: tr.menu.returns,
    path: "/iadeler",
    icon: IconArrowBackUp,
    // Depo da görür: teslim alır ve imha eder.
    roles: ["sevkiyat", "laboratuvar", "depo", "yonetim"],
    phase: 3,
  },
  {
    key: "traceability",
    label: tr.menu.traceability,
    path: "/izlenebilirlik",
    icon: IconRoute,
    roles: ["laboratuvar", "yonetim"],
    phase: 3,
  },
  {
    key: "purchasing",
    label: tr.menu.purchasing,
    path: "/satin-alma",
    icon: IconShoppingCart,
    // Depo siparişleri (tutarsız) ve beklenen teslimatları görür; planlama ve üretim talep açar.
    roles: ["satin_alma", "yonetim", "depo", "planlama", "uretim"],
    phase: 4,
  },
  {
    key: "costing",
    label: tr.menu.costing,
    path: "/maliyet",
    icon: IconCoin,
    // Maliyet tutarlarını yalnızca yönetim (ve admin) görür (Karar D-15).
    roles: ["yonetim"],
    phase: 4,
  },
  {
    key: "reporting",
    label: tr.menu.reporting,
    path: "/raporlar",
    icon: IconChartBar,
    // Her rolün en az bir panosu ya da raporu var; sekme içerikleri rolle daralır.
    roles: [],
    phase: 4,
  },
  {
    key: "admin",
    label: tr.menu.adminPanel,
    path: "/admin/",
    icon: IconSettings,
    roles: ["admin"],
    external: true,
  },
];

export function visibleMenu(user: CurrentUser | null): MenuItem[] {
  return MENU.filter((item) => hasAnyRole(user, item.roles));
}
