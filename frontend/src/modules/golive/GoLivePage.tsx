import { Stack, Tabs, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { useCan } from "../../auth/access";
import { PERM, type PermKey } from "../../auth/access.gen";
import { ForbiddenPage } from "../../pages/ForbiddenPage";
import { ComparisonsTab } from "./ComparisonsTab";
import { ProblemsTab } from "./ProblemsTab";
import { ReadinessTab } from "./ReadinessTab";
import { gt } from "./strings";

export const GOLIVE_BASE = "/gecis";

interface TabDef {
  slug: string;
  label: string;
  /** Sekmeyi açan bölüm (Görür). */
  section: PermKey;
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  {
    slug: "hazirlik",
    label: gt.tabs.readiness,
    section: PERM.GOLIVE_READINESS,
    render: () => <ReadinessTab />,
  },
  {
    slug: "karsilastirma",
    label: gt.tabs.comparisons,
    section: PERM.GOLIVE_COMPARISONS,
    render: () => <ComparisonsTab />,
  },
  // Sorun bildirimlerinin tamamını admin görür (yalnız admin bölümü); kişi kendi bildirimini
  // görevinden açar.
  {
    slug: "sorunlar",
    label: gt.tabs.problems,
    section: PERM.GOLIVE_PROBLEMS,
    render: () => <ProblemsTab />,
  },
];

/** Canlıya geçiş: hazırlık listesi, paralel çalışma stok karşılaştırması, sorun bildirimleri. */
export function GoLivePage() {
  const { tab } = useParams();
  const { can } = useCan();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => can(item.section));
  // Sekmesiz adres ilk görünen sekmeyi açar; hiçbiri yoksa "Yetkiniz yok".
  if (visible.length === 0) return <ForbiddenPage />;
  const current = visible.find((item) => item.slug === (tab ?? visible[0].slug));
  if (!current) return <Navigate to="/" replace />;

  return (
    <Stack>
      <Title order={2}>{gt.title}</Title>
      <Tabs value={current.slug} onChange={(value) => value && navigate(`${GOLIVE_BASE}/${value}`)}>
        <Tabs.List style={{ overflowX: "auto", flexWrap: "nowrap" }}>
          {visible.map((item) => (
            <Tabs.Tab key={item.slug} value={item.slug}>
              {item.label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <div key={current.slug}>{current.render()}</div>
    </Stack>
  );
}
