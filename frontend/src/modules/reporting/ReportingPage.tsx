import { Alert, Button, Group, Loader, Stack, Tabs, Text, Title } from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getDashboard, listDashboards, type DashboardCode } from "../../api/reporting";
import { formatDateTime } from "../../i18n/format";
import { REPORTING_BASE, TABS, type TabKey } from "./config";
import { LabView, ManagementView, ProductionView, ShippingView, WarehouseView } from "./Dashboards";
import { JobsPanel } from "./JobsPanel";
import { ReportsPanel } from "./ReportsPanel";
import { rt } from "./strings";

function tabFromPath(value: string | undefined): TabKey {
  return (Object.keys(TABS) as TabKey[]).find((key) => TABS[key] === value) ?? "dashboards";
}

/** Panolar ve raporlar: menü herkese açık; panolar ve raporlar rolle daralır (backend listesi). */
export function ReportingPage() {
  const tab = tabFromPath(useParams().tab);
  const navigate = useNavigate();
  return (
    <Stack>
      <Title order={2}>{rt.title}</Title>
      <Tabs
        value={tab}
        onChange={(value) => value && navigate(`${REPORTING_BASE}/${TABS[value as TabKey]}`)}
      >
        <Tabs.List>
          {(Object.keys(TABS) as TabKey[]).map((key) => (
            <Tabs.Tab key={key} value={key}>
              {rt.tabs[key]}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      {tab === "dashboards" && <DashboardsPanel />}
      {tab === "reports" && <ReportsPanel />}
      {tab === "jobs" && <JobsPanel />}
    </Stack>
  );
}

function DashboardsPanel() {
  const list = useQuery({ queryKey: ["reporting", "dashboards"], queryFn: listDashboards });
  const [selected, setSelected] = useState<DashboardCode | null>(null);
  if (list.isLoading) return <Loader />;
  if (list.isError)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(list.error)}
      </Alert>
    );
  const dashboards = list.data ?? [];
  if (dashboards.length === 0) return <Text c="dimmed">{rt.noDashboard}</Text>;
  const code = selected ?? dashboards[0].code;
  return (
    <Stack>
      {dashboards.length > 1 && (
        <Tabs
          variant="pills"
          value={code}
          onChange={(value) => value && setSelected(value as DashboardCode)}
        >
          <Tabs.List>
            {dashboards.map((d) => (
              <Tabs.Tab key={d.code} value={d.code}>
                {d.title}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </Tabs>
      )}
      <Dashboard code={code} />
    </Stack>
  );
}

/** Pano: veri dakikada bir yenilenir; üstte güncellik zamanı ve Yenile düğmesi. */
export function Dashboard({ code }: { code: DashboardCode }) {
  const query = useQuery({
    queryKey: ["reporting", "dashboard", code],
    queryFn: () => getDashboard(code),
    refetchInterval: 60_000,
  });
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {query.dataUpdatedAt ? rt.asOf(formatDateTime(new Date(query.dataUpdatedAt))) : ""}
        </Text>
        <Button
          variant="subtle"
          size="xs"
          leftSection={<IconRefresh size={14} />}
          loading={query.isFetching}
          onClick={() => query.refetch()}
        >
          {rt.refresh}
        </Button>
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading && <Loader />}
      {query.data && <DashboardBody code={code} data={query.data} />}
    </Stack>
  );
}

function DashboardBody({ code, data }: { code: DashboardCode; data: unknown }) {
  switch (code) {
    case "management":
      return <ManagementView data={data as Parameters<typeof ManagementView>[0]["data"]} />;
    case "warehouse":
      return <WarehouseView data={data as Parameters<typeof WarehouseView>[0]["data"]} />;
    case "lab":
      return <LabView data={data as Parameters<typeof LabView>[0]["data"]} />;
    case "production":
      return <ProductionView data={data as Parameters<typeof ProductionView>[0]["data"]} />;
    case "shipping":
      return <ShippingView data={data as Parameters<typeof ShippingView>[0]["data"]} />;
  }
}
