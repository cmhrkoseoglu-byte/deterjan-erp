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
  listBatches,
  listOrders,
  type OrderStatus,
  type ProductionBatch,
  type ProductionOrder,
} from "../../api/production";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime } from "../../i18n/format";
import { ct } from "../common/strings";
import { Qty } from "../inventory/shared";
import {
  BATCHABLE_STATUSES,
  batchPath,
  ORDER_ROLES,
  orderPath,
  PREP_ROLES,
  PREP_STATUSES,
  prepPath,
  PRODUCTION_BASE,
} from "./config";
import { BatchStatusBadge, OrderStatusBadge } from "./shared";
import { pt } from "./strings";

const PAGE_SIZE = 50;
const ORDER_STATUS_OPTIONS = (Object.keys(pt.orderStatus) as OrderStatus[]).map((value) => ({
  value,
  label: pt.orderStatus[value],
}));

interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  align?: "right";
}

function RowsTable<T extends { id: number }>({
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

const orderColumns: Column<ProductionOrder>[] = [
  { header: pt.number, render: (r) => r.number },
  { header: pt.product, render: (r) => `${r.product_code} - ${r.product_name}` },
  {
    header: pt.plannedQuantity,
    align: "right",
    render: (r) => <Qty value={r.planned_quantity} unit={r.unit_code} />,
  },
  { header: pt.plannedDate, render: (r) => formatDate(r.planned_date) },
  { header: pt.tank, render: (r) => r.equipment_code },
  { header: pt.priorityLabel, render: (r) => pt.priority[r.priority] },
  { header: pt.status, render: (r) => <OrderStatusBadge status={r.status} /> },
];

function useOrders(statuses: OrderStatus[], search: string, page: number) {
  const [debounced] = useDebouncedValue(search, 300);
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  return useQuery({
    queryKey: ["production", "orders", statuses, params],
    queryFn: () => listOrders(params, statuses),
    placeholderData: keepPreviousData,
  });
}

function SearchBox(props: { value: string; placeholder: string; onChange: (v: string) => void }) {
  return (
    <TextInput
      aria-label={props.placeholder}
      placeholder={props.placeholder}
      leftSection={<IconSearch size={16} />}
      value={props.value}
      w={300}
      onChange={(event) => props.onChange(event.currentTarget.value)}
    />
  );
}

function OrdersTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<OrderStatus | null>(null);
  const [page, setPage] = useState(1);
  const query = useOrders(status ? [status] : [], search, page);
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <SearchBox
            value={search}
            placeholder={pt.search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
          />
          <Select
            aria-label={pt.status}
            placeholder={pt.allStatuses}
            data={ORDER_STATUS_OPTIONS}
            value={status}
            clearable
            w={200}
            onChange={(value) => {
              setStatus(value as OrderStatus | null);
              setPage(1);
            }}
          />
        </Group>
        {hasAnyRole(user, ORDER_ROLES) && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => navigate(orderPath("yeni"))}>
            {pt.newOrder}
          </Button>
        )}
      </Group>
      <RowsTable
        columns={orderColumns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(orderPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Depo: onaylı ve hazırlıktaki emirler; satıra dokununca tablet hazırlama ekranı açılır. */
function PrepTab() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const query = useOrders(PREP_STATUSES, "", page);
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  return (
    <Stack>
      <RowsTable
        testId="prep-orders"
        columns={orderColumns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(prepPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Devam eden şarjlar ve şarj bekleyen emirler. */
function BatchesTab() {
  const navigate = useNavigate();
  const batches = useQuery({
    queryKey: ["production", "batches", "open"],
    queryFn: () => listBatches({ page_size: PAGE_SIZE }, ["IN_PROGRESS"]),
  });
  const waiting = useOrders(BATCHABLE_STATUSES, "", 1);
  const batchColumns: Column<ProductionBatch>[] = [
    { header: pt.batchNo, render: (r) => r.batch_no },
    { header: pt.order, render: (r) => r.order_number },
    { header: pt.product, render: (r) => `${r.product_code} - ${r.product_name}` },
    { header: pt.tank, render: (r) => r.equipment_code },
    {
      header: pt.batchQuantity,
      align: "right",
      render: (r) => <Qty value={r.planned_quantity} unit={r.unit} />,
    },
    { header: pt.when, render: (r) => formatDateTime(r.started_at) },
    { header: pt.status, render: (r) => <BatchStatusBadge status={r.status} /> },
  ];
  return (
    <Stack>
      <Title order={4}>{pt.batchStatus.IN_PROGRESS}</Title>
      <RowsTable
        testId="open-batches"
        columns={batchColumns}
        rows={batches.data?.results ?? []}
        loading={batches.isLoading}
        error={batches.error}
        onOpen={(row) => navigate(batchPath(row.id))}
      />
      <Title order={4}>{pt.startBatch}</Title>
      <RowsTable
        testId="batchable-orders"
        columns={orderColumns}
        rows={waiting.data?.results ?? []}
        loading={waiting.isLoading}
        error={waiting.error}
        onOpen={(row) => navigate(orderPath(row.id))}
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
  { slug: "emirler", label: pt.tabs.orders, roles: [], render: () => <OrdersTab /> },
  { slug: "hazirlama", label: pt.tabs.prep, roles: PREP_ROLES, render: () => <PrepTab /> },
  { slug: "sarjlar", label: pt.tabs.batches, roles: [], render: () => <BatchesTab /> },
];

/** Üretim: sekmeler (`/uretim/<sekme>`). Depo hazırlamaya, üretim şarjlara düşer. */
export function ProductionPage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const fallback =
    hasAnyRole(user, PREP_ROLES) && !hasAnyRole(user, ORDER_ROLES)
      ? "hazirlama"
      : user?.roles.includes("uretim")
        ? "sarjlar"
        : "emirler";
  const current = visible.find((item) => item.slug === (tab ?? fallback));
  if (!current) return <Navigate to={PRODUCTION_BASE} replace />;

  return (
    <Stack>
      <Title order={2}>{pt.title}</Title>
      <Tabs
        value={current.slug}
        onChange={(value) => value && navigate(`${PRODUCTION_BASE}/${value}`)}
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
