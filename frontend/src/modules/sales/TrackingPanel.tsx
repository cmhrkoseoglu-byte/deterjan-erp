// Müşteri sipariş takibi (docs/plan/musteri-siparis-takibi.md §3.3): Sevkiyat > "Sipariş takibi"
// sekmesi ve müşteri kartındaki "Açık siparişler" paneli. Veri /sales/tracking/* uç noktalarından;
// cari bakiye yalnız Müşteri carileri: Görür + Fiyatları görür olana, Cari hesaplar API'sinden.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Pagination,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getPartnerSummary } from "../../api/ledger";
import {
  listCustomerTracking,
  listTrackedOrders,
  type CustomerTracking,
  type TrackedOrder,
} from "../../api/sales";
import { useCan } from "../../auth/access";
import { PERM } from "../../auth/access.gen";
import { formatDate, formatMoney, formatNumber } from "../../i18n/format";
import { today } from "../inventory/config";
import { balanceText, partnerLedgerPath, PRICES } from "../ledger/config";
import { salesOrderPath, shipmentPath } from "./config";
import { SalesOrderStatusBadge, ShipmentStatusBadge } from "./shared";
import { st } from "./strings";

const PAGE_SIZE = 50;
const DUE_SOON_DAYS = 7;
const tt = st.tracking;

/** `YYYY-MM-DD` tarihine gün ekler. */
function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

function LateBadge({ order }: { order: TrackedOrder }) {
  if (order.is_late && order.days_late)
    return (
      <Badge color="red" variant="filled">
        {tt.daysLate(order.days_late)}
      </Badge>
    );
  if (order.due_date === null)
    return (
      <Text size="sm" c="dimmed">
        {tt.noDueDate}
      </Text>
    );
  return null;
}

function amountText(order: TrackedOrder): string {
  return order.totals.map((total) => formatMoney(total.amount, total.currency)).join(" + ");
}

/** Sevk edilen / sipariş miktarı, sipariş birimiyle (ör. "1 / 2 KOLI"). */
function progressText(order: TrackedOrder): string {
  return order.lines
    .map(
      (line) =>
        `${formatNumber(line.shipped_in_unit)} / ${formatNumber(line.quantity)} ${line.unit_code}`,
    )
    .join(", ");
}

function OrderLines({ order }: { order: TrackedOrder }) {
  return (
    <Stack gap="xs" p="xs">
      <Table.ScrollContainer minWidth={640}>
        <Table data-testid={`tracking-lines-${order.id}`}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{st.product}</Table.Th>
              <Table.Th ta="right">{tt.ordered}</Table.Th>
              <Table.Th ta="right">{tt.shipped}</Table.Th>
              <Table.Th ta="right">{tt.planned}</Table.Th>
              <Table.Th ta="right">{tt.remaining}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {order.lines.map((line) => {
              const base = line.base_unit_code;
              return (
                <Table.Tr key={line.id}>
                  <Table.Td>
                    {line.product_code} · {line.product_name}
                  </Table.Td>
                  <Table.Td ta="right">
                    {formatNumber(line.quantity)} {line.unit_code}
                  </Table.Td>
                  <Table.Td ta="right">
                    {formatNumber(line.shipped_quantity ?? 0)} {base}
                  </Table.Td>
                  <Table.Td ta="right">
                    {formatNumber(line.planned_quantity ?? 0)} {base}
                  </Table.Td>
                  <Table.Td ta="right" fw={Number(line.remaining_quantity) > 0 ? 600 : undefined}>
                    {formatNumber(line.remaining_quantity)} {base}
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group gap="xs">
        <Text size="sm" fw={500}>
          {tt.shipments}:
        </Text>
        {order.shipments.length === 0 && (
          <Text size="sm" c="dimmed">
            {tt.noShipments}
          </Text>
        )}
        {order.shipments.map((shipment) => (
          <Group key={shipment.id} gap={4}>
            <Anchor component={Link} to={shipmentPath(shipment.id)} size="sm">
              {shipment.number}
            </Anchor>
            <ShipmentStatusBadge status={shipment.status} />
            <Text size="xs" c="dimmed">
              {formatDate(shipment.dispatched_at ?? shipment.planned_date)}
            </Text>
          </Group>
        ))}
      </Group>
    </Stack>
  );
}

/** Müşterinin cari bakiyesi; yalnız Müşteri carileri: Görür + Fiyatları görür olana. */
function CustomerBalance({ customerId }: { customerId: number }) {
  const { can } = useCan();
  const allowed = can(PERM.LEDGER_CUSTOMERS) && can(PRICES);
  const query = useQuery({
    queryKey: ["ledger", "customers", "summary", customerId],
    queryFn: () => getPartnerSummary("customers", customerId),
    enabled: allowed,
  });
  if (!allowed) return null;
  const balances = query.data?.balances ?? [];
  return (
    <Paper withBorder p="sm" radius="md" data-testid="tracking-balance">
      <Group justify="space-between" wrap="wrap">
        <Group gap="lg">
          <Text size="sm" fw={500}>
            {tt.balance}
          </Text>
          {query.isLoading && <Loader size="xs" />}
          {query.isError && (
            <Text size="sm" c="red">
              {getErrorMessage(query.error)}
            </Text>
          )}
          {query.isSuccess && balances.length === 0 && (
            <Text size="sm" c="dimmed">
              {tt.noBalance}
            </Text>
          )}
          {balances.map((balance) => (
            <Group key={balance.currency} gap="xs">
              <Text size="sm">{balanceText(balance.balance, balance.currency)}</Text>
              {Number(balance.overdue ?? 0) > 0 && (
                <Badge color="red" variant="light">
                  {tt.overdue}: {formatMoney(balance.overdue, balance.currency)}
                </Badge>
              )}
            </Group>
          ))}
        </Group>
        <Anchor component={Link} to={partnerLedgerPath("musteriler", customerId)} size="sm">
          {tt.statement}
        </Anchor>
      </Group>
    </Paper>
  );
}

/** Bir müşterinin takipteki siparişleri: süzgeçler, sipariş satırları ve (yetkiye göre) cari bakiye. */
export function CustomerOrderTracking({ customerId }: { customerId: number }) {
  const [onlyLate, setOnlyLate] = useState(false);
  const [dueThisWeek, setDueThisWeek] = useState(false);
  const [includeFinished, setIncludeFinished] = useState(false);
  const [open, setOpen] = useState<number[]>([]);
  const params = {
    customer: customerId,
    page_size: 100,
    late: onlyLate || undefined,
    due_before: dueThisWeek ? addDays(today(), DUE_SOON_DAYS) : undefined,
    include_finished: includeFinished || undefined,
  };
  const query = useQuery({
    queryKey: ["sales", "tracking", "orders", params],
    queryFn: () => listTrackedOrders(params),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.results ?? [];
  const toggle = (id: number) =>
    setOpen((ids) => (ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]));

  return (
    <Stack gap="sm">
      <CustomerBalance customerId={customerId} />
      <Group>
        <Checkbox
          label={tt.onlyLate}
          checked={onlyLate}
          onChange={(event) => setOnlyLate(event.currentTarget.checked)}
        />
        <Checkbox
          label={tt.dueThisWeek}
          checked={dueThisWeek}
          onChange={(event) => setDueThisWeek(event.currentTarget.checked)}
        />
        <Checkbox
          label={tt.includeFinished}
          checked={includeFinished}
          onChange={(event) => setIncludeFinished(event.currentTarget.checked)}
        />
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading && <Loader size="sm" />}
      {query.isSuccess && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {tt.noOrders}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table data-testid="tracking-orders">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{st.number}</Table.Th>
                <Table.Th>{tt.dueDate}</Table.Th>
                <Table.Th>{st.status}</Table.Th>
                <Table.Th />
                <Table.Th>{tt.progress}</Table.Th>
                <Table.Th ta="right">{tt.amount}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((order) => {
                const expanded = open.includes(order.id);
                return (
                  <Fragment key={order.id}>
                    <Table.Tr
                      data-testid={`tracking-order-${order.id}`}
                      bg={order.is_late ? "var(--mantine-color-red-light)" : undefined}
                    >
                      <Table.Td>
                        <Anchor component={Link} to={salesOrderPath(order.id)} size="sm">
                          {order.number}
                        </Anchor>
                      </Table.Td>
                      <Table.Td>{formatDate(order.due_date)}</Table.Td>
                      <Table.Td>
                        <SalesOrderStatusBadge status={order.status} />
                      </Table.Td>
                      <Table.Td>
                        <LateBadge order={order} />
                      </Table.Td>
                      <Table.Td>{progressText(order)}</Table.Td>
                      <Table.Td ta="right">{amountText(order)}</Table.Td>
                      <Table.Td ta="right">
                        <Button size="compact-xs" variant="subtle" onClick={() => toggle(order.id)}>
                          {expanded ? tt.hideLines : tt.showLines}
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                    {expanded && (
                      <Table.Tr>
                        <Table.Td colSpan={7}>
                          <OrderLines order={order} />
                        </Table.Td>
                      </Table.Tr>
                    )}
                  </Fragment>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

/** Sevkiyat > Sipariş takibi: açık siparişi olan müşteriler; seçilen müşterinin siparişleri altta. */
export function TrackingTab() {
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [onlyLate, setOnlyLate] = useState(false);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<CustomerTracking | null>(null);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    late: onlyLate || undefined,
  };
  const query = useQuery({
    queryKey: ["sales", "tracking", "customers", params],
    queryFn: () => listCustomerTracking(params),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {tt.intro}
      </Text>
      <Group>
        <TextInput
          aria-label={st.search}
          placeholder={st.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          w={300}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Checkbox
          label={tt.onlyLate}
          checked={onlyLate}
          onChange={(event) => {
            setOnlyLate(event.currentTarget.checked);
            setPage(1);
          }}
        />
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isSuccess && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {tt.noCustomers}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={680}>
          <Table striped highlightOnHover data-testid="tracking-customers">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{st.code}</Table.Th>
                <Table.Th>{st.name}</Table.Th>
                <Table.Th ta="right">{tt.openOrders}</Table.Th>
                <Table.Th ta="right">{tt.lateOrders}</Table.Th>
                <Table.Th ta="right">{tt.dueSoon}</Table.Th>
                <Table.Th ta="right">{tt.maxDaysLate}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr
                  key={row.id}
                  style={{ cursor: "pointer" }}
                  aria-selected={selected?.id === row.id}
                  bg={selected?.id === row.id ? "var(--mantine-primary-color-light)" : undefined}
                  onClick={() => setSelected(row)}
                >
                  <Table.Td>{row.code}</Table.Td>
                  <Table.Td>{row.name}</Table.Td>
                  <Table.Td ta="right">{row.open_orders}</Table.Td>
                  <Table.Td ta="right">
                    {row.late_orders > 0 ? (
                      <Badge color="red" variant="light">
                        {row.late_orders}
                      </Badge>
                    ) : (
                      0
                    )}
                  </Table.Td>
                  <Table.Td ta="right">{row.due_soon}</Table.Td>
                  <Table.Td ta="right">
                    {row.max_days_late && row.max_days_late > 0 ? tt.days(row.max_days_late) : ""}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      {selected && (
        <Stack gap="sm" data-testid="tracking-selected">
          <Title order={4}>{tt.ordersOf(selected.name)}</Title>
          <CustomerOrderTracking key={selected.id} customerId={selected.id} />
        </Stack>
      )}
    </Stack>
  );
}
