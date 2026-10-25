import { Stack, Tabs, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import type { EntityConfig } from "../common/CrudPage";
import { CrudPage } from "../common/CrudPage";
import {
  categoryConfig,
  conversionConfig,
  customerConfig,
  equipmentConfig,
  locationConfig,
  materialConfig,
  printerConfig,
  supplierConfig,
  unitConfig,
  warehouseConfig,
} from "./entities";
import { CompanyProfilePanel } from "./CompanyProfilePanel";
import { LabelSettingsPanel } from "./LabelTools";

// Sekme adresi (Türkçe) → ekran tanımı (liste ekranı ya da özel bileşen). Sıra menüdeki sıradır.
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- farklı kayıt türleri
type Tab = [string, EntityConfig<any> | { title: string; render: () => ReactNode }];
const TABS: Tab[] = [
  ["malzemeler", materialConfig],
  ["tedarikciler", supplierConfig],
  ["musteriler", customerConfig],
  ["depolar", warehouseConfig],
  ["lokasyonlar", locationConfig],
  ["ekipmanlar", equipmentConfig],
  ["kategoriler", categoryConfig],
  ["birim-donusumleri", conversionConfig],
  ["birimler", unitConfig],
  ["yazicilar", printerConfig],
  ["firma-bilgileri", { title: "Firma bilgileri", render: () => <CompanyProfilePanel /> }],
  ["etiket-ayarlari", { title: "Etiket ayarları", render: () => <LabelSettingsPanel /> }],
];

export const MASTERDATA_BASE = "/ana-veriler";

/** Ana veriler: her kayıt türü bir sekme (`/ana-veriler/<sekme>`). */
export function MasterDataPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const current = TABS.find(([slug]) => slug === tab);
  if (!current) return <Navigate to={`${MASTERDATA_BASE}/${TABS[0][0]}`} replace />;

  return (
    <Stack>
      <Title order={2}>Ana veriler</Title>
      <Tabs
        value={current[0]}
        onChange={(value) => value && navigate(`${MASTERDATA_BASE}/${value}`)}
      >
        <Tabs.List style={{ overflowX: "auto", flexWrap: "nowrap" }}>
          {TABS.map(([slug, config]) => (
            <Tabs.Tab key={slug} value={slug}>
              {config.title}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      {/* key: sekme değişince liste durumu (sayfa, arama) sıfırlanır */}
      {"render" in current[1] ? (
        current[1].render()
      ) : (
        <CrudPage key={current[0]} config={current[1]} />
      )}
    </Stack>
  );
}
