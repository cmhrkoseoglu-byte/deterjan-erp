import { Stack, Tabs, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ComparisonsTab } from "./ComparisonsTab";
import { ProblemsTab } from "./ProblemsTab";
import { ReadinessTab } from "./ReadinessTab";
import { gt } from "./strings";

export const GOLIVE_BASE = "/gecis";

interface TabDef {
  slug: string;
  label: string;
  roles: readonly Role[];
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  {
    slug: "hazirlik",
    label: gt.tabs.readiness,
    roles: ["yonetim", "planlama", "depo"],
    render: () => <ReadinessTab />,
  },
  {
    slug: "karsilastirma",
    label: gt.tabs.comparisons,
    roles: ["yonetim", "planlama", "depo"],
    render: () => <ComparisonsTab />,
  },
  // Sorun bildirimlerinin tamamını admin görür; kişi kendi bildirimini görevinden açar.
  { slug: "sorunlar", label: gt.tabs.problems, roles: ["admin"], render: () => <ProblemsTab /> },
];

/** Canlıya geçiş: hazırlık listesi, paralel çalışma stok karşılaştırması, sorun bildirimleri. */
export function GoLivePage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const current = visible.find((item) => item.slug === (tab ?? visible[0]?.slug));
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
