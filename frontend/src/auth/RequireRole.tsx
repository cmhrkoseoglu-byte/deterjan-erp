import type { ReactNode } from "react";
import type { Role } from "../api/types";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import { useAuth } from "./AuthContext";
import { hasAnyRole } from "./roles";

/** Kullanıcı rollerden hiçbirine sahip değilse "Yetkiniz yok" sayfasını gösterir. */
export function RequireRole({ roles, children }: { roles: readonly Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!hasAnyRole(user, roles)) return <ForbiddenPage />;
  return <>{children}</>;
}
