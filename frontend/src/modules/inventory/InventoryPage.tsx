import { Group, Stack, Tabs, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useCan } from "../../auth/access";
import { RequireAccess } from "../../auth/RequireAccess";
import { ScanInput } from "../../components/scan/ScanInput";
import { INVENTORY_BASE, lotPath } from "./config";
import { AdjustmentsTab, LotsTab, ReceiptsTab, StockTab } from "./ListTabs";
import { it } from "./strings";

interface TabDef {
  slug: string;
  label: string;
  /** Sekmeyi gösteren bölüm (Görür). Stok, lotlar ve paletler herkese açıktır (kilitli). */
  section: string;
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  { slug: "stok", label: it.tabs.stock, section: "inventory.stock", render: () => <StockTab /> },
  { slug: "lotlar", label: it.tabs.lots, section: "inventory.lots", render: () => <LotsTab /> },
  {
    slug: "mal-kabul",
    label: it.tabs.receipts,
    section: "inventory.receipts",
    render: () => <ReceiptsTab />,
  },
  {
    slug: "sayim",
    label: it.tabs.adjustments,
    section: "inventory.adjustments",
    render: () => <AdjustmentsTab />,
  },
];

/** Depo ve stok: sekmeler (`/depo/<sekme>`), kullanıcının yetkisine göre. */
export function InventoryPage() {
  const { tab } = useParams();
  const { can } = useCan();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => can(item.section, "view"));
  if (visible.length === 0) {
    return (
      <RequireAccess allow={() => false} need={[{ key: "inventory", level: "view" }]}>
        {null}
      </RequireAccess>
    );
  }
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
