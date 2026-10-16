import {
  Button,
  Checkbox,
  Group,
  Pagination,
  Select,
  Stack,
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
import { listRecords, type Partner } from "../../api/masterdata";
import { listSalesOrders, type SalesOrderStatus } from "../../api/sales";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ct } from "../common/strings";
import { RowsTable } from "../filling/FillingPage";
import { orderColumns } from "./columns";
import { customerPath, ORDER_WRITE_ROLES, SALES_BASE, salesOrderPath } from "./config";
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
  { slug: "musteriler", label: st.tabs.customers, roles: [], render: () => <CustomersTab /> },
];

/** Sevkiyat: sekmeler (`/sevkiyat/<sekme>`). Sevkiyat planlama ve toplama Adım 3.2'de eklenir. */
export function SalesPage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const current = visible.find((item) => item.slug === (tab ?? "siparisler"));
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
