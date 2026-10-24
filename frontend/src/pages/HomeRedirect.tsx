import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { landingPath } from "../auth/paths";

/** `/`: kullanıcıyı açılış ekranına yönlendirir (yönetim panosu ya da Görevlerim). */
export function HomeRedirect() {
  const { user } = useAuth();
  return <Navigate to={landingPath(user)} replace />;
}
