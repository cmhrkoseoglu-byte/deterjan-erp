import type { ComponentProps } from "react";
import { RouterProvider } from "react-router-dom";

/**
 * Uygulamanın yönlendirici sağlayıcısı; uygulama ve testler aynısını kullanır. Sayfa geçişleri hemen
 * çizilir: React transition'ı kapalı, react-router 6'daki gibi. Uygulamada Suspense yok, transition bir
 * şey kazandırmaz; açık olsaydı kaydedip yeni sayfaya geçen formlar geçiş çizilene kadar bir an daha
 * tıklanabilir kalırdı (docs/DECISIONS.md, "react-router 7'ye geçiş").
 */
export function AppRouterProvider({
  router,
}: Pick<ComponentProps<typeof RouterProvider>, "router">) {
  return <RouterProvider router={router} useTransitions={false} />;
}
