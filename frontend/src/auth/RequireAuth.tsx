import { Navigate, Outlet, useLocation } from "react-router-dom";
import { LoadingScreen } from "../components/LoadingScreen";
import { useAuth } from "./AuthContext";
import { isPortalUser, PORTAL_PATH, PORTAL_SECURITY_PATH, SECURITY_PATH } from "./paths";

/**
 * Oturum yoksa giriş ekranına yönlendirir; girişten sonra aynı sayfaya dönülür. Oturum
 * hareketsizlikten kapandıysa giriş ekranı nedenini gösterir (`reason=expired`).
 * Geçici şifreyle giren (önce kendi şifresini belirlemeli) ya da rolü 2FA isteyen ama kurmamış
 * kullanıcı her sayfada Güvenlik sayfasına yönlendirilir.
 *
 * Portal kullanıcısı (müşteri, tedarikçi) yalnız `/portal` altını açar; başka her adres portala
 * döner. Çalışan `/portal` adresini açamaz (açılış ekranına döner). Asıl ret sunucudadır.
 */
export function RequireAuth() {
  const { user, isLoading, sessionExpired } = useAuth();
  const location = useLocation();
  if (isLoading) return <LoadingScreen />;
  if (!user) {
    const params = new URLSearchParams({ next: location.pathname + location.search });
    if (sessionExpired) params.set("reason", "expired");
    return <Navigate to={`/login?${params.toString()}`} replace />;
  }
  const portal = isPortalUser(user);
  const path = location.pathname;
  const inPortal = path === PORTAL_PATH || path.startsWith(`${PORTAL_PATH}/`);
  if (portal && !inPortal) return <Navigate to={PORTAL_PATH} replace />;
  if (!portal && inPortal) return <Navigate to="/" replace />;
  const security = portal ? PORTAL_SECURITY_PATH : SECURITY_PATH;
  const mustVisitSecurity = user.password_change_required || user.otp_setup_required;
  if (mustVisitSecurity && path !== security) {
    return <Navigate to={security} replace />;
  }
  return <Outlet />;
}
