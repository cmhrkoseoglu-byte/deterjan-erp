import {
  Alert,
  Button,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  listFillingOrders,
  listRuns,
  listSpecs,
  type FillingOrder,
  type FillingOrderStatus,
  type FillingRun,
  type PackagingSpec,
} from "../../api/filling";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { ct } from "../common/strings";
import {
  FILLING_BASE,
  fillingOrderPath,
  fillingPrepPath,
  LINE_ROLES,
  PLAN_ROLES,
  PREP_ROLES,
  PREP_STATUSES,
  runPath,
  specPath,
  STARTABLE_STATUSES,
} from "./config";
import { FillingOrderStatusBadge, RunStatusBadge, SpecStatusBadge } from "./shared";
import { ft } from "./strings";

const PAGE_SIZE = 50;
const STATUS_OPTIONS = (Object.keys(ft.orderStatus) as FillingOrderStatus[]).map((value) => ({
  value,
  label: ft.orderStatus[value],
}));

interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  align?: "right";
}

export function RowsTable<T extends { id: number }>({
  columns,
  rows,
  loading,
  error,
  onOpen,
  testId,
}: {
  columns: Column<T>[];
  rows: T[];
  loading: boolean;
  error: unknown;
  onOpen: (row: T) => void;
  testId?: string;
}) {
  return (
    <>
      {Boolean(error) && (
        <Alert color="red" variant="light">
          {getErrorMessage(error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={680}>
        <Table striped highlightOnHover data-testid={testId}>
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
              <Table.Tr key={row.id} style={{ cursor: "pointer" }} onClick={() => onOpen(row)}>
                {columns.map((column) => (
                  <Table.Td key={column.header} ta={column.align}>
                    {column.render(row)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
            {!loading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={columns.length}>
                  <Text c="dimmed" ta="center" py="md">
                    {ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

const orderColumns: Column<FillingOrder>[] = [
  { header: ft.number, render: (r) => r.number },
  { header: ft.product, render: (r) => `${r.finished_product_code} - ${r.finished_product_name}` },
  {
    header: ft.plannedUnits,
    align: "right",
    render: (r) => `${formatNumber(r.planned_units)} ${r.unit}`,
  },
  { header: ft.plannedDate, render: (r) => formatDate(r.planned_date) },
  { header: ft.line, render: (r) => r.filling_line_code },
  { header: ft.status, render: (r) => <FillingOrderStatusBadge status={r.status} /> },
];

function useOrders(statuses: FillingOrderStatus[], search: string, page: number) {
  const [debounced] = useDebouncedValue(search, 300);
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  return useQuery({
    queryKey: ["filling", "orders", statuses, params],
    queryFn: () => listFillingOrders(params, statuses),
    placeholderData: keepPreviousData,
  });
}

function OrdersTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<FillingOrderStatus | null>(null);
  const [page, setPage] = useState(1);
  const query = useOrders(status ? [status] : [], search, page);
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={ft.search}
            placeholder={ft.search}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={300}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={ft.status}
            placeholder={ft.allStatuses}
            data={STATUS_OPTIONS}
            value={status}
            clearable
            w={200}
            onChange={(value) => {
              setStatus(value as FillingOrderStatus | null);
              setPage(1);
            }}
          />
        </Group>
        {hasAnyRole(user, PLAN_ROLES) && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate(fillingOrderPath("yeni"))}
          >
            {ft.newOrder}
          </Button>
        )}
      </Group>
      <RowsTable
        columns={orderColumns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(fillingOrderPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Depo: onaylı ve hazırlıktaki emirler; satıra dokununca tablet hazırlama ekranı açılır. */
function PrepTab() {
  const navigate = useNavigate();
  const query = useOrders(PREP_STATUSES, "", 1);
  return (
    <RowsTable
      testId="prep-orders"
      columns={orderColumns}
      rows={query.data?.results ?? []}
      loading={query.isLoading}
      error={query.error}
      onOpen={(row) => navigate(fillingPrepPath(row.id))}
    />
  );
}

/** Dolum hattı: devam eden partiler ve parti bekleyen emirler. */
function LineTab() {
  const navigate = useNavigate();
  const runs = useQuery({
    queryKey: ["filling", "runs", "open"],
    queryFn: () => listRuns({ page_size: PAGE_SIZE }, ["IN_PROGRESS"]),
  });
  const waiting = useOrders(STARTABLE_STATUSES, "", 1);
  const runColumns: Column<FillingRun>[] = [
    { header: ft.outputLot, render: (r) => r.output_lot_no },
    { header: ft.number, render: (r) => r.order_number },
    {
      header: ft.product,
      render: (r) => `${r.finished_product_code} - ${r.finished_product_name}`,
    },
    { header: ft.operator, render: (r) => r.operator_name ?? "" },
    { header: ft.startedAt, render: (r) => formatDateTime(r.started_at) },
    { header: ft.status, render: (r) => <RunStatusBadge status={r.status} /> },
  ];
  return (
    <Stack>
      <Title order={4}>{ft.runStatus.IN_PROGRESS}</Title>
      <RowsTable
        testId="open-runs"
        columns={runColumns}
        rows={runs.data?.results ?? []}
        loading={runs.isLoading}
        error={runs.error}
        onOpen={(row) => navigate(runPath(row.id))}
      />
      <Title order={4}>{ft.startRun}</Title>
      <RowsTable
        testId="startable-orders"
        columns={orderColumns}
        rows={waiting.data?.results ?? []}
        loading={waiting.isLoading}
        error={waiting.error}
        onOpen={(row) => navigate(fillingOrderPath(row.id))}
      />
    </Stack>
  );
}

function SpecsTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const query = useQuery({
    queryKey: ["filling", "specs", debounced],
    queryFn: () => listSpecs({ page_size: PAGE_SIZE, search: debounced || undefined }),
    placeholderData: keepPreviousData,
  });
  const columns: Column<PackagingSpec>[] = [
    {
      header: ft.product,
      render: (r) => `${r.finished_product_code} - ${r.finished_product_name}`,
    },
    { header: ft.version, render: (r) => ft.specVersion(r.version_no) },
    { header: ft.bulk, render: (r) => r.bulk_product_code },
    {
      header: ft.fill,
      align: "right",
      render: (r) => `${formatNumber(r.fill_quantity)} ${r.fill_unit_code}`,
    },
    { header: ft.unitsPerCase, align: "right", render: (r) => r.units_per_case },
    { header: ft.status, render: (r) => <SpecStatusBadge status={r.status} /> },
  ];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {ft.specsIntro}
      </Text>
      <Group justify="space-between">
        <TextInput
          aria-label={ct.search}
          placeholder={ct.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          w={300}
          onChange={(event) => setSearch(event.currentTarget.value)}
        />
        {hasAnyRole(user, PLAN_ROLES) && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => navigate(specPath("yeni"))}>
            {ft.newSpec}
          </Button>
        )}
      </Group>
      <RowsTable
        testId="specs"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(specPath(row.id))}
      />
    </Stack>
  );
}

interface TabDef {
  slug: string;
  label: string;
  roles: readonly Role[];
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  { slug: "emirler", label: ft.tabs.orders, roles: [], render: () => <OrdersTab /> },
  { slug: "hazirlama", label: ft.tabs.prep, roles: PREP_ROLES, render: () => <PrepTab /> },
  { slug: "hat", label: ft.tabs.line, roles: [], render: () => <LineTab /> },
  { slug: "ambalaj-receteleri", label: ft.tabs.specs, roles: [], render: () => <SpecsTab /> },
];

/** Dolum: sekmeler (`/dolum/<sekme>`). Depo hazırlamaya, dolum rolü hatta düşer. */
export function FillingPage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const fallback =
    hasAnyRole(user, PREP_ROLES) && !hasAnyRole(user, PLAN_ROLES)
      ? "hazirlama"
      : user?.roles.some((role) => LINE_ROLES.includes(role))
        ? "hat"
        : "emirler";
  const current = visible.find((item) => item.slug === (tab ?? fallback));
  if (!current) return <Navigate to={FILLING_BASE} replace />;

  return (
    <Stack>
      <Title order={2}>{ft.title}</Title>
      <Tabs
        value={current.slug}
        onChange={(value) => value && navigate(`${FILLING_BASE}/${value}`)}
      >
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
