import { Anchor, type AnchorProps } from "@mantine/core";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canOpenRecord, RECORD_ROUTES } from "./recordLinks";

/**
 * Kayıt bağlantısı (plan §5.9 "Kayıt bağlantıları"): hedef sayfa bu kullanıcıya açılıyorsa
 * bağlantı, açılmıyorsa düz metin. Karar `routes.tsx` ile aynı sayfa kurallarından verilir
 * (`auth/pageAccess.ts`). Adres verilmezse kayıt türünün detay sayfasıdır (`RECORD_ROUTES`).
 */
export function RecordLink({
  model,
  id,
  to,
  children,
  ...anchor
}: {
  /** Kayıt türü, ör. "production.productionorder". */
  model: string;
  id: number | string;
  /** Hedef adres (ör. sekmeli bir sayfa); verilmezse kaydın detay sayfası. */
  to?: string;
  children: ReactNode;
} & AnchorProps) {
  const { user } = useAuth();
  const route = RECORD_ROUTES[model];
  // Adres yardımcıları kimliği metne çevirir; "yeni" gibi metin kimlikler de geçer.
  const path = to ?? (route ? route(id as number) : null);
  if (!path || !canOpenRecord(user, model, id)) return <>{children}</>;
  return (
    <Anchor component={Link} to={path} {...anchor}>
      {children}
    </Anchor>
  );
}
