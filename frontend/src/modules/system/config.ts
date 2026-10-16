export const SYSTEM_BASE = "/sistem";
export const TABS = { status: "durum", users: "kullanicilar", device: "bu-cihaz" } as const;
export type TabKey = keyof typeof TABS;
