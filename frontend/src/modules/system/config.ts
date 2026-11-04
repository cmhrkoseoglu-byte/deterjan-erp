export const SYSTEM_BASE = "/sistem";
export const TABS = {
  status: "durum",
  users: "kullanicilar",
  coding: "kodlama",
  device: "bu-cihaz",
} as const;
export type TabKey = keyof typeof TABS;
