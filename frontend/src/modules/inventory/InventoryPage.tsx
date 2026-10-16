import { Group, Stack, Tabs, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ScanInput } from "../../components/scan/ScanInput";
import { INVENTORY_BASE, lotPath } from "./config";
import { AdjustmentsTab, LotsTab, ReceiptsTab, StockTab } from "./ListTabs";
import { it } from "./strings";

interface TabDef {
  slug: string;
  label: string;
  /** Boşsa herkes görür (okuma herkese açık; yazma backend'de rolle sınırlı). */
  roles: readonly Role[];
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  { slug: "stok", label: it.tabs.stock, roles: [], render: () => <StockTab /> },
  { slug: "lotlar", label: it.tabs.lots, roles: [], render: () => <LotsTab /> },
  {
    slug: "mal-kabul",
    label: it.tabs.receipts,
    roles: ["depo", "planlama", "yonetim", "satin_alma", "laboratuvar"],
    render: () => <ReceiptsTab />,
  },
  {
    slug: "sayim",
    label: it.tabs.adjustments,
    roles: ["depo", "yonetim"],
    render: () => <AdjustmentsTab />,
  },
];

/** Depo ve stok: sekmeler (`/depo/<sekme>`), kullanıcının rolüne göre. */
export function InventoryPage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  // Lot serbest bırakma ve ret kalite modülündedir (numune kararı); burada stok sorgu açılır.
  const current = visible.find((item) => item.slug === (tab ?? visible[0].slug));
  if (!current) return <Navigate to={INVENTORY_BASE} replace />;

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Title order={2}>{it.title}</Title>
        {/* Lot etiketini (ya da koli / palet barkodunu) okutunca lot detayı açılır. */}
        <div style={{ width: 360, maxWidth: "100%" }}>
          <ScanInput
            expect="lot"
            size="md"
            label={it.scanLot}
            onLot={(lot) => navigate(lotPath(lot.id))}
          />
        </div>
      </Group>
      <Tabs
        value={current.slug}
        onChange={(value) => value && navigate(`${INVENTORY_BASE}/${value}`)}
      >
        <Tabs.List style={{ overflowX: "auto", flexWrap: "nowrap" }}>
          {visible.map((item) => (
            <Tabs.Tab key={item.slug} value={item.slug}>
              {item.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      {/* key: sekme değişince liste durumu (sayfa, arama) sıfırlanır */}
      <div key={current.slug}>{current.render()}</div>
    </Stack>
  );
}
