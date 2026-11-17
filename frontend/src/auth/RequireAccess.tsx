import type { ReactNode } from "react";
import { useParams } from "react-router-dom";
import type { CurrentUser, RequiredAccess } from "../api/types";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import { useAuth } from "./AuthContext";
import { PAGE_RULES, type PageKey } from "./pageAccess";

/**
 * Kullanıcı `allow` koşulunu sağlamıyorsa "Yetkiniz yok" sayfasını (gereken yetki `need` ile)
 * gösterir. Koşul her çizimde `me`'den yeniden hesaplanır: yetki değişince (`access.changed`,
 * pencereye dönüş, 403) açık sayfa da kapanır (plan §6.5).
 */
export function RequireAccess({
  allow,
  need,
  children,
}: {
  allow: (user: CurrentUser) => boolean;
  need?: readonly RequiredAccess[];
  children: ReactNode;
}) {
  const { user } = useAuth();
  if (!user || !allow(user)) return <ForbiddenPage need={need} />;
  return <>{children}</>;
}

/**
 * Rota koruması: sayfanın kuralı (`auth/pageAccess.ts`), rota parametreleriyle (ör. yeni emir
 * sayfası). Kayıt bağlantıları aynı kurala bakar.
 */
export function RequirePage({ page, children }: { page: PageKey; children: ReactNode }) {
  const { user } = useAuth();
  const params = useParams();
  const rule = PAGE_RULES[page];
  if (!user || !rule.allow(user, params))
    return <ForbiddenPage need={rule.need(params, user ?? undefined)} />;
  return <>{children}</>;
}
