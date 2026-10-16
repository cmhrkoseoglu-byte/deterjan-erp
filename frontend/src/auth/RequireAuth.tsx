import { Navigate, Outlet, useLocation } from "react-router-dom";
import { LoadingScreen } from "../components/LoadingScreen";
import { useAuth } from "./AuthContext";
import { SECURITY_PATH } from "./paths";

/**
 * Oturum yoksa giriş ekranına yönlendirir; girişten sonra aynı sayfaya dönülür. Oturum
 * hareketsizlikten kapandıysa giriş ekranı nedenini gösterir (`reason=expired`).
 * Rolü 2FA isteyen ama kurmamış kullanıcı her sayfada Güvenlik sayfasına yönlendirilir.
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
  if (user.otp_setup_required && location.pathname !== SECURITY_PATH) {
    return <Navigate to={SECURITY_PATH} replace />;
  }
  return <Outlet />;
}
