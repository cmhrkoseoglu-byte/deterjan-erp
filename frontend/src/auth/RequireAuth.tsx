import { Navigate, Outlet, useLocation } from "react-router-dom";
import { LoadingScreen } from "../components/LoadingScreen";
import { useAuth } from "./AuthContext";

/** Oturum yoksa giriş ekranına yönlendirir; girişten sonra aynı sayfaya dönülür. */
export function RequireAuth() {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <LoadingScreen />;
  if (!user) {
    const next = location.pathname + location.search;
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />;
  }
  return <Outlet />;
}
