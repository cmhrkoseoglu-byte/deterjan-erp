import {
  IconBuildingFactory2,
  IconChartBar,
  IconChecklist,
  IconDatabase,
  IconFlask,
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
    key: "inventory",
    label: tr.menu.inventory,
    path: "/depo",
    icon: IconPackages,
    roles: ["depo", "planlama", "yonetim"],
    phase: 1,
  },
  {
    key: "production",
    label: tr.menu.production,
    path: "/uretim",
    icon: IconBuildingFactory2,
    roles: ["uretim", "planlama", "yonetim"],
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
    roles: ["dolum", "planlama", "yonetim"],
    phase: 2,
  },
  {
    key: "sales",
    label: tr.menu.sales,
    path: "/sevkiyat",
    icon: IconTruckDelivery,
    roles: ["sevkiyat", "yonetim"],
    phase: 3,
  },
  {
    key: "purchasing",
    label: tr.menu.purchasing,
    path: "/satin-alma",
    icon: IconShoppingCart,
    roles: ["satin_alma", "yonetim"],
    phase: 4,
  },
  {
    key: "reporting",
    label: tr.menu.reporting,
    path: "/raporlar",
    icon: IconChartBar,
    roles: ["yonetim", "planlama"],
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
