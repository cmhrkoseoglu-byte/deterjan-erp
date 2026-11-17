import type { CurrentUser } from "../api/types";
import { can } from "./access";

/** Güvenlik sayfası (şifre, iki aşamalı doğrulama). Her giriş yapmış kullanıcıya açık. */
export const SECURITY_PATH = "/guvenlik";
/** Görevlerim: herkesin görev listesi. */
export const TASKS_PATH = "/gorevlerim";
/** Yönetim panosu: yönetim rolünün açılış ekranı. */
export const DASHBOARD_PATH = "/pano";
/** Lot ve belge numarası araması (üst çubuktaki arama kutusu buraya götürür). */
export const SEARCH_PATH = "/ara";

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
  return user?.roles.includes("yonetim") && can(user, "reporting.management", "view")
    ? DASHBOARD_PATH
    : TASKS_PATH;
}
