import type { CurrentUser } from "../api/types";
import { can } from "./access";

/** Güvenlik sayfası (şifre, iki aşamalı doğrulama). Her giriş yapmış kullanıcıya açık. */
export const SECURITY_PATH = "/guvenlik";
/** Yetkilerim: kişinin kendi rolleri ve yetkileri, salt okunur (plan §6.4). Herkese açık. */
export const MY_ACCESS_PATH = "/yetkilerim";
/** Görevlerim: herkesin görev listesi. */
export const TASKS_PATH = "/gorevlerim";
/** Yönetim panosu: yönetim rolünün açılış ekranı. */
export const DASHBOARD_PATH = "/pano";
/** Lot ve belge numarası araması (üst çubuktaki arama kutusu buraya götürür). */
export const SEARCH_PATH = "/ara";
/** Müşteri ve tedarikçi portalı (docs/plan/musteri-siparis-takibi.md §4.6). */
export const PORTAL_PATH = "/portal";
/** Portal kullanıcısının Güvenlik sayfası (şifre, isteğe bağlı iki aşamalı doğrulama). */
export const PORTAL_SECURITY_PATH = "/portal/guvenlik";
/** KVKK aydınlatma metni: giriş gerektirmez. */
export const PRIVACY_PATH = "/aydinlatma";

/** Portal kullanıcısı mı (müşteri ya da tedarikçi yetkilisi)? */
export function isPortalUser(user: CurrentUser | null | undefined): boolean {
  return Boolean(user && user.account_type && user.account_type !== "staff");
}

/** Sistem > Kullanıcılar > Yetkiler (yalnız admin; plan §6.1); `gecmis` Geçmiş sekmesini açar. */
export function userAccessPath(id: number, tab?: "gecmis"): string {
  return `/sistem/kullanicilar/${id}/yetkiler${tab ? `?sekme=${tab}` : ""}`;
}

export function searchPath(query: string): string {
  return `${SEARCH_PATH}?q=${encodeURIComponent(query.trim())}`;
}

/**
 * Açılış ekranı (`/`, girişten sonra ve logoya basınca): yönetim rolü panoyla, diğer herkes
 * Görevlerim'le açılır. Yalnızca açıkça atanmış yönetim rolü sayılır (rol görünümü); admin
 * Görevlerim'de kalır. Panoyu göremeyen (Yönetim panosu: Görür'ü kaldırılmış) yönetim de
 * Görevlerim'le açılır (plan §3.15, §5.9).
 */
export function landingPath(user: CurrentUser | null): string {
  if (isPortalUser(user)) return PORTAL_PATH;
  return user?.roles.includes("yonetim") && can(user, "reporting.management", "view")
    ? DASHBOARD_PATH
    : TASKS_PATH;
}
