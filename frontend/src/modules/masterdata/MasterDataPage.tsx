import { Stack, Tabs, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useCan } from "../../auth/access";
import { RequireAccess } from "../../auth/RequireAccess";
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

// Sekme adresi (Türkçe) → ekran tanımı (liste ekranı ya da özel bileşen) ve sekmeyi gösteren bölüm
// (Görür). Sıra menüdeki sıradır.
type Screen =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- farklı kayıt türleri
  EntityConfig<any> | { title: string; render: () => ReactNode };
type Tab = [slug: string, screen: Screen, section: string];
const CARDS = "masterdata.cards";
const REFERENCE = "masterdata.reference";
const COMPANY = "masterdata.company";
const TABS: Tab[] = [
  ["malzemeler", materialConfig, CARDS],
  ["tedarikciler", supplierConfig, CARDS],
  ["musteriler", customerConfig, CARDS],
  ["depolar", warehouseConfig, CARDS],
  ["lokasyonlar", locationConfig, CARDS],
  ["ekipmanlar", equipmentConfig, CARDS],
  ["kategoriler", categoryConfig, CARDS],
  ["birim-donusumleri", conversionConfig, CARDS],
  ["birimler", unitConfig, REFERENCE],
  ["yazicilar", printerConfig, REFERENCE],
  ["firma-bilgileri", { title: "Firma bilgileri", render: () => <CompanyProfilePanel /> }, COMPANY],
  [
    "etiket-ayarlari",
    { title: "Etiket ayarları", render: () => <LabelSettingsPanel /> },
    REFERENCE,
  ],
];

export const MASTERDATA_BASE = "/ana-veriler";

/** Ana veriler: her kayıt türü bir sekme (`/ana-veriler/<sekme>`). */
export function MasterDataPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const { can } = useCan();
  const visible = TABS.filter(([, , section]) => can(section, "view"));
  const current = visible.find(([slug]) => slug === tab);
  if (!current) {
    // Görünmeyen ya da bilinmeyen sekme: ilk görünür sekme; hiçbiri yoksa "Yetkiniz yok".
    if (visible.length === 0) {
      return (
        <RequireAccess allow={() => false} need={[{ key: "masterdata", level: "view" }]}>
          {null}
        </RequireAccess>
      );
    }
    return <Navigate to={`${MASTERDATA_BASE}/${visible[0][0]}`} replace />;
  }

  return (
    <Stack>
      <Title order={2}>Ana veriler</Title>
      <Tabs
        value={current[0]}
        onChange={(value) => value && navigate(`${MASTERDATA_BASE}/${value}`)}
      >
        <Tabs.List style={{ overflowX: "auto", flexWrap: "nowrap" }}>
          {visible.map(([slug, config]) => (
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
