import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconRefresh } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { getErrorMessage } from "../../api/client";
import { fetchSystemStatus, type CheckStatus, type SystemStatus } from "../../api/ops";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { formatBytes } from "./format";
import { sy } from "./strings";

const CHECK_COLORS: Record<CheckStatus, string> = { ok: "green", error: "red", unknown: "gray" };
const OFFSITE_COLORS: Record<string, string> = { ok: "green", failed: "red", disabled: "gray" };

function diskColor(pct: number): string {
  if (pct >= 90) return "red";
  if (pct >= 80) return "orange";
  return "blue";
}

/** Sistem durumu: kontroller, disk, yük, kuyruk ve son yedek / geri yükleme testi kayıtları. */
export function StatusPanel() {
  const query = useQuery({
    queryKey: ["ops", "status"],
    queryFn: fetchSystemStatus,
    refetchInterval: 60_000,
  });
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {sy.statusHelp}
      </Text>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          {query.dataUpdatedAt ? sy.asOf(formatDateTime(new Date(query.dataUpdatedAt))) : ""}
        </Text>
        <Button
          variant="subtle"
          size="xs"
          leftSection={<IconRefresh size={14} />}
          loading={query.isFetching}
          onClick={() => query.refetch()}
        >
          {sy.refresh}
        </Button>
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading && <Loader />}
      {query.data && <StatusBody data={query.data} />}
    </Stack>
  );
}

function StatusBody({ data }: { data: SystemStatus }) {
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {data.checks.map((check) => (
          <Card key={check.check} withBorder>
            <Stack gap={4}>
              <Group justify="space-between" wrap="nowrap">
                <Text fw={600}>{check.label}</Text>
                <Badge color={CHECK_COLORS[check.status] ?? "gray"}>
                  {sy.checkStatus[check.status] ?? check.status}
                </Badge>
              </Group>
              <Text size="sm">{check.title}</Text>
              {check.detail && (
                <Text size="xs" c="dimmed" style={{ whiteSpace: "pre-line" }}>
                  {check.detail}
                </Text>
              )}
              {check.since && (
                <Text size="xs" c="dimmed">
                  {sy.since(formatDateTime(check.since))}
                </Text>
              )}
            </Stack>
          </Card>
        ))}
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        <Card withBorder>
          <Stack gap="xs">
            <Text fw={600}>{sy.disks}</Text>
            {data.disks.length === 0 && <Text c="dimmed">{sy.unknown}</Text>}
            {data.disks.map((disk) => (
              <div key={disk.path}>
                <Group justify="space-between" gap="xs">
                  <Text size="sm" ff="monospace">
                    {disk.path}
                  </Text>
                  <Text size="sm">%{formatNumber(Math.round(disk.used_pct))}</Text>
                </Group>
                <Progress
                  value={disk.used_pct}
                  color={diskColor(disk.used_pct)}
                  aria-label={disk.path}
                />
                <Text size="xs" c="dimmed">
                  {sy.diskDetail(formatBytes(disk.free_bytes), formatBytes(disk.total_bytes))}
                </Text>
              </div>
            ))}
          </Stack>
        </Card>
        <Card withBorder>
          <Text fw={600}>{sy.load}</Text>
          <Text fz="xl">{data.load_15 === null ? sy.unknown : formatNumber(data.load_15, 2)}</Text>
          {data.cpu_count !== null && (
            <Text size="sm" c="dimmed">
              {sy.loadDetail(data.cpu_count)}
            </Text>
          )}
        </Card>
        <Card withBorder>
          <Text fw={600}>{sy.queue}</Text>
          <Text fz="xl">
            {data.queue_length === null ? sy.unknown : formatNumber(data.queue_length)}
          </Text>
        </Card>
      </SimpleGrid>

      <Title order={4}>{sy.runs}</Title>
      {data.runs.length === 0 ? (
        <Text c="dimmed">{sy.noRuns}</Text>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{sy.runDate}</Table.Th>
                <Table.Th>{sy.runKind}</Table.Th>
                <Table.Th>{sy.runStatus}</Table.Th>
                <Table.Th ta="right">{sy.runRows}</Table.Th>
                <Table.Th>{sy.runSize}</Table.Th>
                <Table.Th>{sy.runOffsite}</Table.Th>
                <Table.Th>{sy.runMessage}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.runs.map((run) => (
                <Table.Tr key={run.id}>
                  <Table.Td>{formatDateTime(run.started_at)}</Table.Td>
                  <Table.Td>{run.kind_display}</Table.Td>
                  <Table.Td>
                    <Badge color={run.status === "ok" ? "green" : "red"}>
                      {run.status_display}
                    </Badge>
                  </Table.Td>
                  <Table.Td ta="right">{formatNumber(run.rows)}</Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {sy.runSizeDetail(
                        formatBytes(run.database_bytes),
                        formatBytes(run.media_bytes),
                        formatNumber(run.media_files),
                      )}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={OFFSITE_COLORS[run.offsite] ?? "gray"} variant="light">
                      {run.offsite_display}
                    </Badge>
                    {run.offsite_message && (
                      <Text size="xs" c="dimmed">
                        {run.offsite_message}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{run.message}</Text>
                    {run.mismatches.length > 0 && (
                      <Stack gap={0}>
                        <Text size="xs" c="red">
                          {sy.mismatches(run.mismatches.length)}
                        </Text>
                        {run.mismatches.slice(0, 5).map((m) => (
                          <Text key={m.table} size="xs" c="red">
                            {sy.mismatch(m.table, formatNumber(m.expected), formatNumber(m.actual))}
                          </Text>
                        ))}
                      </Stack>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}
