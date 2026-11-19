import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconDownload, IconSearch } from "@tabler/icons-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { PAGE_SIZE, type ListFilterState } from "./filters";
import { pt } from "./strings";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  align?: "right";
}

/** Sade tablo; satıra tıklanınca `onOpen` (varsa). Dar ekranda yatay kaydırılır. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onOpen,
  testId,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onOpen?: (row: T) => void;
  testId?: string;
}) {
  if (rows.length === 0)
    return (
      <Text size="sm" c="dimmed">
        {pt.empty}
      </Text>
    );
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table striped highlightOnHover={Boolean(onOpen)} data-testid={testId}>
        <Table.Thead>
          <Table.Tr>
            {columns.map((column) => (
              <Table.Th key={column.header} ta={column.align}>
                {column.header}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr
              key={rowKey(row)}
              style={onOpen ? { cursor: "pointer" } : undefined}
              onClick={onOpen ? () => onOpen(row) : undefined}
            >
              {columns.map((column) => (
                <Table.Td key={column.header} ta={column.align}>
                  {column.render(row)}
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

const STATUS_COLOR: Record<string, string> = {
  CONFIRMED: "blue",
  PARTIALLY_SHIPPED: "yellow",
  SHIPPED: "green",
  CLOSED: "gray",
  CANCELLED: "red",
  PLANNED: "blue",
  PICKING: "yellow",
  LOADED: "orange",
  DISPATCHED: "green",
  SENT: "blue",
  PARTIALLY_RECEIVED: "yellow",
  RECEIVED: "green",
};

export function StatusBadge({ status, label }: { status: string; label: string }) {
  return (
    <Badge variant="light" color={STATUS_COLOR[status] ?? "gray"}>
      {label}
    </Badge>
  );
}

/** Sayfa başlığı, açıklama ve (detay sayfasında) geri bağlantısı. */
export function PageHeader({
  title,
  intro,
  back,
  actions,
}: {
  title: string;
  intro?: string;
  back?: string;
  actions?: ReactNode;
}) {
  return (
    <Stack gap="xs">
      {back && (
        <Anchor component={Link} to={back} size="sm">
          <Group gap={4}>
            <IconArrowLeft size={14} />
            {pt.back}
          </Group>
        </Anchor>
      )}
      <Group justify="space-between" align="flex-start">
        <Title order={2}>{title}</Title>
        {actions}
      </Group>
      {intro && (
        <Text size="sm" c="dimmed">
          {intro}
        </Text>
      )}
    </Stack>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm">{children || "—"}</Text>
    </Stack>
  );
}

export function Fields({ children }: { children: ReactNode }) {
  return <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>{children}</SimpleGrid>;
}

export function QueryState({ isLoading, error }: { isLoading: boolean; error: unknown }) {
  if (isLoading) return <Loader size="sm" />;
  if (error)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(error)}
      </Alert>
    );
  return null;
}

/** PDF indirme düğmesi: indirirken bekler, hata olursa bildirir. */
export function DownloadButton({
  label,
  onDownload,
  disabled,
}: {
  label: string;
  onDownload: () => Promise<void>;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      await onDownload();
    } catch (error) {
      notifications.show({ color: "red", message: getErrorMessage(error) || pt.downloadFailed });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Button
      variant="light"
      size="xs"
      leftSection={<IconDownload size={16} />}
      loading={busy}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        void run();
      }}
    >
      {label}
    </Button>
  );
}

export function ListFilters({
  filters,
  statuses,
}: {
  filters: ListFilterState;
  statuses?: { value: string; label: string }[];
}) {
  return (
    <Group>
      <TextInput
        aria-label={pt.search}
        placeholder={pt.search}
        leftSection={<IconSearch size={16} />}
        value={filters.search}
        w={260}
        onChange={(event) => {
          filters.setSearch(event.currentTarget.value);
          filters.setPage(1);
        }}
      />
      {statuses && (
        <Select
          aria-label={pt.status}
          placeholder={pt.allStatuses}
          data={statuses}
          value={filters.status}
          clearable
          w={220}
          onChange={(value) => {
            filters.setStatus(value);
            filters.setPage(1);
          }}
        />
      )}
    </Group>
  );
}

export function Pages({ count, filters }: { count: number; filters: ListFilterState }) {
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  if (pages <= 1) return null;
  return <Pagination value={filters.page} onChange={filters.setPage} total={pages} />;
}
