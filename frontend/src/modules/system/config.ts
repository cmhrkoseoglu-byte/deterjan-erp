export const SYSTEM_BASE = "/sistem";
export const TABS = {
  status: "durum",
  users: "kullanicilar",
  roles: "rol-yetkileri",
  coding: "kodlama",
  device: "bu-cihaz",
} as const;
export type TabKey = keyof typeof TABS;
