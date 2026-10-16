import {
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconPlus, IconSearch, IconTruck } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { listRecords, type Partner } from "../../api/masterdata";
import {
  listSalesOrders,
  listShipments,
  type SalesOrderStatus,
  type Shipment,
  type ShipmentStatus,
} from "../../api/sales";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ct } from "../common/strings";
import { RowsTable } from "../filling/FillingPage";
import { orderColumns, shipmentColumns } from "./columns";
import { formatDate } from "../../i18n/format";
import {
  customerPath,
  ORDER_WRITE_ROLES,
  PICK_ROLES,
  PICKABLE_STATUSES,
  pickPath,
  SALES_BASE,
  salesOrderPath,
  shipmentPath,
} from "./config";
import { ShipmentStatusBadge } from "./shared";
import { st } from "./strings";

const PAGE_SIZE = 50;
const STATUS_OPTIONS = (Object.keys(st.orderStatus) as SalesOrderStatus[]).map((value) => ({
  value,
  label: st.orderStatus[value],
}));

function OrdersTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<SalesOrderStatus | null>(null);
  const [shortage, setShortage] = useState(false);
  const [page, setPage] = useState(1);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    has_shortage: shortage ? true : undefined,
  };
  const query = useQuery({
    queryKey: ["sales", "orders", status, params],
    queryFn: () => listSalesOrders(params, status ? [status] : []),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={st.search}
            placeholder={st.search}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={340}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={st.status}
            placeholder={st.allStatuses}
            data={STATUS_OPTIONS}
            value={status}
            clearable
            w={200}
            onChange={(value) => {
              setStatus(value as SalesOrderStatus | null);
              setPage(1);
            }}
          />
          <Checkbox
            label={st.onlyShortage}
            checked={shortage}
            onChange={(event) => {
              setShortage(event.currentTarget.checked);
              setPage(1);
            }}
          />
        </Group>
        {hasAnyRole(user, ORDER_WRITE_ROLES) && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate(salesOrderPath("yeni"))}
          >
            {st.newOrder}
          </Button>
        )}
      </Group>
      <RowsTable
        testId="sales-orders"
        columns={orderColumns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(salesOrderPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

const SHIPMENT_STATUS_OPTIONS = (Object.keys(st.shipmentStatus) as ShipmentStatus[]).map(
  (value) => ({ value, label: st.shipmentStatus[value] }),
);

function ShipmentsTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<ShipmentStatus | null>(null);
  const [page, setPage] = useState(1);
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  const query = useQuery({
    queryKey: ["sales", "shipments", status, params],
    queryFn: () => listShipments(params, status ? [status] : []),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group>
        <TextInput
          aria-label={st.shipmentSearch}
          placeholder={st.shipmentSearch}
          leftSection={<IconSearch size={16} />}
          value={search}
          w={340}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Select
          aria-label={st.status}
          placeholder={st.allStatuses}
          data={SHIPMENT_STATUS_OPTIONS}
          value={status}
          clearable
          w={200}
          onChange={(value) => {
            setStatus(value as ShipmentStatus | null);
            setPage(1);
          }}
        />
      </Group>
      <RowsTable
        testId="shipments"
        columns={shipmentColumns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(shipmentPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Depo: toplanacak sevkiyatlar (planlanan tarihe göre), tablete büyük kartlarla. */
function PickingTab() {
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["sales", "shipments", "picking"],
    queryFn: () => listShipments({ page_size: 100, ordering: "planned_date" }, PICKABLE_STATUSES),
  });
  const rows = query.data?.results ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {st.pickingList}
      </Text>
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {st.noPicking}
        </Text>
      )}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm" data-testid="picking-list">
        {rows.map((row: Shipment) => (
          <UnstyledButton key={row.id} onClick={() => navigate(pickPath(row.id))}>
            <Card withBorder padding="md" radius="md">
              <Group justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap">
                  <IconTruck size={20} />
                  <Text fw={700} size="lg">
                    {row.number}
                  </Text>
                </Group>
                <ShipmentStatusBadge status={row.status} />
              </Group>
              <Text size="sm" mt={4}>
                {row.customer_name}
              </Text>
              <Group gap="xs" mt={4}>
                <Badge variant="default">{formatDate(row.planned_date)}</Badge>
                {row.vehicle_plate && <Badge variant="default">{row.vehicle_plate}</Badge>}
                <Badge variant="default">{row.order_number}</Badge>
              </Group>
            </Card>
          </UnstyledButton>
        ))}
      </SimpleGrid>
    </Stack>
  );
}

function CustomersTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const query = useQuery({
    queryKey: ["sales", "customers", debounced],
    queryFn: () =>
      listRecords<Partner>("customers", {
        is_active: true,
        page_size: PAGE_SIZE,
        search: debounced || undefined,
      }),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {st.customersIntro}
      </Text>
      <TextInput
        aria-label={ct.search}
        placeholder={ct.search}
        leftSection={<IconSearch size={16} />}
        value={search}
        w={300}
        onChange={(event) => setSearch(event.currentTarget.value)}
      />
      <RowsTable
        testId="sales-customers"
        columns={[
          { header: st.code, render: (r: Partner) => r.code },
          { header: st.name, render: (r: Partner) => r.name },
          { header: st.contact, render: (r: Partner) => r.contact_person },
          { header: st.phone, render: (r: Partner) => r.phone },
        ]}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(customerPath(row.id))}
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
  { slug: "siparisler", label: st.tabs.orders, roles: [], render: () => <OrdersTab /> },
  { slug: "sevkiyatlar", label: st.tabs.shipments, roles: [], render: () => <ShipmentsTab /> },
  { slug: "toplama", label: st.tabs.picking, roles: PICK_ROLES, render: () => <PickingTab /> },
  { slug: "musteriler", label: st.tabs.customers, roles: [], render: () => <CustomersTab /> },
];

/** Sevkiyat: sekmeler (`/sevkiyat/<sekme>`). Toplama sekmesi depoya (tablet) açılır. */
export function SalesPage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  // Depo tablette doğrudan toplama listesine düşer.
  const fallback =
    hasAnyRole(user, PICK_ROLES) && !hasAnyRole(user, ORDER_WRITE_ROLES) ? "toplama" : "siparisler";
  const current = visible.find((item) => item.slug === (tab ?? fallback));
  if (!current) return <Navigate to={SALES_BASE} replace />;

  return (
    <Stack>
      <Title order={2}>{st.title}</Title>
      <Tabs value={current.slug} onChange={(value) => value && navigate(`${SALES_BASE}/${value}`)}>
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
