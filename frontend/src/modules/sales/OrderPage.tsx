import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Modal,
  Paper,
  Radio,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowLeft,
  IconCheck,
  IconLock,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconTruck,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listRecords, type Material } from "../../api/masterdata";
import {
  cancelSalesOrder,
  closeSalesOrder,
  confirmSalesOrder,
  getSalesOrder,
  listCandidates,
  releaseReservation,
  reserveLot,
  reserveShortages,
  saveSalesOrder,
  type Currency,
  type Reservation,
  type SalesOrderDetail,
  type SalesOrderLine,
  type SalesOrderPayload,
} from "../../api/sales";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { CancelModal } from "../inventory/CancelModal";
import { today } from "../inventory/config";
import { idOrNull } from "../inventory/options";
import { Info, Qty } from "../inventory/shared";
import { RowsTable } from "../filling/FillingPage";
import { shipmentColumns } from "./columns";
import {
  customerPath,
  ORDER_WRITE_ROLES,
  RESERVABLE_STATUSES,
  SALES_BASE,
  salesOrderPath,
  SHIPMENT_WRITE_ROLES,
  SHIPPABLE_ORDER_STATUSES,
  shipmentPath,
} from "./config";
import { SalesOrderStatusBadge } from "./shared";
import { PlanShipmentModal } from "./ShipmentForms";
import { st } from "./strings";

const CURRENCIES = (Object.keys(st.currency) as Currency[]).map((value) => ({
  value,
  label: st.currency[value],
}));

interface LineDraft {
  key: string;
  id?: number;
  product: string | null;
  quantity: string;
  unit: string | null;
  unit_price: string;
  currency: string | null;
  note: string;
}

interface HeaderDraft {
  customer: string | null;
  order_date: string;
  requested_delivery_date: string;
  delivery_address: string;
  customer_po_no: string;
  notes: string;
}

let lineSeq = 0;
const newKey = () => `n${++lineSeq}`;

function emptyLine(): LineDraft {
  return {
    key: newKey(),
    product: null,
    quantity: "",
    unit: null,
    unit_price: "",
    currency: "TRY",
    note: "",
  };
}

const str = (value: number | null | undefined) => (value ? String(value) : null);

function toDraft(doc: SalesOrderDetail | null): { header: HeaderDraft; lines: LineDraft[] } {
  if (!doc) {
    return {
      header: {
        customer: null,
        order_date: today(),
        requested_delivery_date: "",
        delivery_address: "",
        customer_po_no: "",
        notes: "",
      },
      lines: [emptyLine()],
    };
  }
  return {
    header: {
      customer: str(doc.customer),
      order_date: doc.order_date,
      requested_delivery_date: doc.requested_delivery_date ?? "",
      delivery_address: doc.delivery_address,
      customer_po_no: doc.customer_po_no,
      notes: doc.notes,
    },
    lines: doc.lines.map((line) => ({
      key: `l${line.id}`,
      id: line.id,
      product: str(line.product),
      quantity: trimDecimal(line.quantity),
      unit: str(line.unit),
      unit_price: line.unit_price ? trimDecimal(line.unit_price) : "",
      currency: line.currency || "TRY",
      note: line.note ?? "",
    })),
  };
}

function toPayload(header: HeaderDraft, lines: LineDraft[]): SalesOrderPayload {
  return {
    customer: idOrNull(header.customer),
    order_date: header.order_date,
    requested_delivery_date: header.requested_delivery_date || null,
    delivery_address: header.delivery_address.trim(),
    customer_po_no: header.customer_po_no.trim(),
    notes: header.notes.trim(),
    lines: lines
      .filter((line) => line.product || line.quantity.trim())
      .map((line): SalesOrderLine => {
        const price = line.unit_price.trim();
        return {
          ...(line.id ? { id: line.id } : {}),
          product: idOrNull(line.product)!,
          quantity: normalizeDecimal(line.quantity),
          unit: idOrNull(line.unit)!,
          unit_price: price ? normalizeDecimal(price) : null,
          currency: price ? ((line.currency ?? "") as Currency | "") : "",
          note: line.note.trim(),
        };
      }),
  };
}

/** Siparişe girebilen mamuller, temel birimleriyle. */
function useFinishedProducts() {
  return useQuery({
    queryKey: ["options", "finished-products"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Material>("materials", {
        is_active: true,
        material_type: "FINISHED",
        page_size: 500,
      });
      return page.results;
    },
  });
}

/** Satış siparişi: taslak düzenlenir; onayda FEFO ile rezerve edilir, rezervasyonlar yönetilir. */
export function SalesOrderPage() {
  const param = useParams().orderId;
  const isNew = param === "yeni";
  const orderId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["sales", "order", orderId],
    queryFn: () => getSalesOrder(orderId!),
    enabled: orderId !== null,
  });

  if (!isNew && query.isLoading) return <Loader />;
  if (!isNew && (query.isError || !query.data))
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const doc = query.data ?? null;

  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: doc ? 8 : 12 }}>
        <OrderForm key={doc ? `${doc.id}-${doc.status}` : "new"} doc={doc} />
      </Grid.Col>
      {doc && (
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <RecordPanel contentType="sales.salesorder" objectId={doc.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

function OrderForm({ doc }: { doc: SalesOrderDetail | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const writer = hasAnyRole(user, ORDER_WRITE_ROLES);
  const editable = writer && (!doc || doc.status === "DRAFT");
  const reservable = writer && !!doc && RESERVABLE_STATUSES.includes(doc.status);
  const [{ header, lines }, setDraft] = useState(() => toDraft(doc));
  const [error, setError] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reserveLine, setReserveLine] = useState<SalesOrderLine | null>(null);
  const [releasing, setReleasing] = useState<Reservation | null>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const customers = useOptions({ endpoint: "customers" });
  const units = useOptions({ endpoint: "units" });
  const products = useFinishedProducts();

  useEffect(() => setDraft(toDraft(doc)), [doc]);

  const productById = new Map((products.data ?? []).map((row) => [String(row.id), row]));
  const productOptions = (products.data ?? []).map((row) => ({
    value: String(row.id),
    label: `${row.code} - ${row.name}`,
  }));

  const setHeader = (patch: Partial<HeaderDraft>) =>
    setDraft((current) => ({ ...current, header: { ...current.header, ...patch } }));
  const setLine = (key: string, patch: Partial<LineDraft>) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));

  const refresh = (saved: SalesOrderDetail) => {
    queryClient.setQueryData(["sales", "order", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["sales"] });
    void queryClient.invalidateQueries({ queryKey: ["workflow"] });
  };
  const onError = (err: unknown) => setError(getErrorMessage(err));

  const save = useMutation({
    mutationFn: () => saveSalesOrder(doc?.id ?? null, toPayload(header, lines)),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: st.saved });
      refresh(saved);
      if (!doc) navigate(salesOrderPath(saved.id), { replace: true });
    },
    onError,
  });
  const confirm = useMutation({
    mutationFn: async () => {
      const saved = await saveSalesOrder(doc!.id, toPayload(header, lines));
      return confirmSalesOrder(saved.id);
    },
    onSuccess: (saved) => {
      setError("");
      setConfirmOpen(false);
      notifications.show({ color: "green", message: st.confirmed });
      refresh(saved);
    },
    onError: (err) => {
      setConfirmOpen(false);
      onError(err);
    },
  });
  const close = useMutation({
    mutationFn: () => closeSalesOrder(doc!.id),
    onSuccess: (saved) => {
      setError("");
      setCloseOpen(false);
      notifications.show({ color: "green", message: st.closed });
      refresh(saved);
    },
    onError: (err) => {
      setCloseOpen(false);
      onError(err);
    },
  });
  const fill = useMutation({
    mutationFn: () => reserveShortages(doc!.id),
    onSuccess: (saved) => {
      setError("");
      const short = saved.lines.some((line) => Number(line.shortage_quantity) > 0);
      notifications.show({
        color: short ? "yellow" : "green",
        message: short ? st.stillShort : st.reservedOk,
      });
      refresh(saved);
    },
    onError,
  });
  const release = useMutation({
    mutationFn: (reservation: Reservation) => releaseReservation(doc!.id, reservation.id),
    onSuccess: (saved) => {
      setError("");
      setReleasing(null);
      notifications.show({ color: "green", message: st.reservedOk });
      refresh(saved);
    },
    onError: (err) => {
      setReleasing(null);
      onError(err);
    },
  });

  const title = doc ? st.orderTitle(doc.number) : st.orderNew;
  const hasShortage = !!doc?.lines.some((line) => Number(line.shortage_quantity) > 0);
  const activeReservations = (doc?.reservations ?? []).filter((r) => r.status === "ACTIVE");
  const otherReservations = (doc?.reservations ?? []).filter((r) => r.status !== "ACTIVE");
  const canPlan =
    !!doc &&
    hasAnyRole(user, SHIPMENT_WRITE_ROLES) &&
    SHIPPABLE_ORDER_STATUSES.includes(doc.status) &&
    doc.lines.some((line) => Number(line.plannable_quantity) > 0);

  return (
    <Stack>
      <Anchor component={Link} to={`${SALES_BASE}/siparisler`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {st.tabs.orders}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{title}</Title>
          {doc && <SalesOrderStatusBadge status={doc.status} />}
          {doc && RESERVABLE_STATUSES.includes(doc.status) && hasShortage && (
            <Badge color="red" variant="light">
              {st.shortageBadge}
            </Badge>
          )}
        </Group>
        <Group gap="xs">
          {editable && (
            <Button variant="default" loading={save.isPending} onClick={() => save.mutate()}>
              {st.saveDraft}
            </Button>
          )}
          {editable && doc && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setConfirmOpen(true)}
            >
              {st.confirm}
            </Button>
          )}
          {canPlan && (
            <Button leftSection={<IconTruck size={16} />} onClick={() => setPlanOpen(true)}>
              {st.planShipment}
            </Button>
          )}
          {reservable && hasShortage && (
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              loading={fill.isPending}
              onClick={() => fill.mutate()}
            >
              {st.reserveShortages}
            </Button>
          )}
          {writer && doc && ["PARTIALLY_SHIPPED", "SHIPPED"].includes(doc.status) && (
            <Button
              variant="light"
              leftSection={<IconLock size={16} />}
              onClick={() => setCloseOpen(true)}
            >
              {st.close}
            </Button>
          )}
          {writer && doc && ["DRAFT", "CONFIRMED"].includes(doc.status) && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {st.cancelOrder}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      {editable ? (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
            <Select
              label={st.customer}
              withAsterisk
              searchable
              data={customers.data ?? []}
              value={header.customer}
              onChange={(value) => setHeader({ customer: value })}
              nothingFoundMessage={st.notFound}
            />
            <TextInput
              label={st.orderDate}
              type="date"
              withAsterisk
              value={header.order_date}
              onChange={(event) => setHeader({ order_date: event.currentTarget.value })}
            />
            <TextInput
              label={st.requestedDelivery}
              type="date"
              value={header.requested_delivery_date}
              onChange={(event) =>
                setHeader({ requested_delivery_date: event.currentTarget.value })
              }
            />
            <TextInput
              label={st.customerPo}
              value={header.customer_po_no}
              onChange={(event) => setHeader({ customer_po_no: event.currentTarget.value })}
            />
            <Textarea
              label={st.deliveryAddress}
              description={st.deliveryAddressHint}
              autosize
              minRows={1}
              value={header.delivery_address}
              onChange={(event) => setHeader({ delivery_address: event.currentTarget.value })}
            />
            <Textarea
              label={st.notes}
              autosize
              minRows={1}
              value={header.notes}
              onChange={(event) => setHeader({ notes: event.currentTarget.value })}
            />
          </SimpleGrid>
        </Paper>
      ) : (
        doc && (
          <Paper withBorder p="md" radius="md">
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
              <Info label={st.customer}>
                <Anchor component={Link} to={customerPath(doc.customer)} size="sm">
                  {`${doc.customer_code} - ${doc.customer_name}`}
                </Anchor>
              </Info>
              <Info label={st.orderDate}>
                <Text size="sm">{formatDate(doc.order_date)}</Text>
              </Info>
              <Info label={st.requestedDelivery}>
                <Text size="sm">{formatDate(doc.requested_delivery_date)}</Text>
              </Info>
              <Info label={st.customerPo}>
                <Text size="sm">{doc.customer_po_no}</Text>
              </Info>
              <Info label={st.shelfLife}>
                <Text size="sm">
                  {doc.min_remaining_shelf_life_days != null
                    ? st.shelfLifeDays(doc.min_remaining_shelf_life_days)
                    : st.noShelfLife}
                </Text>
              </Info>
              {doc.confirmed_at && (
                <Info label={st.confirmedBy}>
                  <Text size="sm">{`${doc.confirmed_by_name ?? ""} · ${formatDateTime(doc.confirmed_at)}`}</Text>
                </Info>
              )}
              <Info label={st.deliveryAddress}>
                <Text size="sm">{doc.delivery_address}</Text>
              </Info>
              <Info label={st.notes}>
                <Text size="sm">{doc.notes}</Text>
              </Info>
              {doc.status === "CANCELLED" && (
                <Info label={st.cancelInfo}>
                  <Text size="sm">{doc.cancel_reason}</Text>
                </Info>
              )}
            </SimpleGrid>
          </Paper>
        )
      )}

      <Group justify="space-between">
        <Title order={4}>{st.lines}</Title>
        {editable && (
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() =>
              setDraft((current) => ({ ...current, lines: [...current.lines, emptyLine()] }))
            }
          >
            {st.addLine}
          </Button>
        )}
      </Group>

      {editable ? (
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            {st.priceHint}
          </Text>
          {lines.map((line, index) => (
            <Paper key={line.key} withBorder p="sm" radius="md" data-testid="order-line">
              <Group justify="space-between" mb={4}>
                <Text size="sm" fw={600}>
                  {index + 1}
                </Text>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={st.removeLine}
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      lines: current.lines.filter((row) => row.key !== line.key),
                    }))
                  }
                >
                  <IconTrash size={16} />
                </ActionIcon>
              </Group>
              <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                <Select
                  label={st.product}
                  withAsterisk
                  searchable
                  data={productOptions}
                  value={line.product}
                  nothingFoundMessage={st.notFound}
                  onChange={(value) => {
                    const picked = value ? productById.get(value) : undefined;
                    setLine(line.key, {
                      product: value,
                      unit: line.unit ?? (picked ? String(picked.base_unit) : null),
                    });
                  }}
                />
                <Group gap="xs" grow wrap="nowrap">
                  <TextInput
                    label={st.quantity}
                    withAsterisk
                    inputMode="decimal"
                    value={line.quantity}
                    onChange={(event) => setLine(line.key, { quantity: event.currentTarget.value })}
                  />
                  <Select
                    label={st.unit}
                    withAsterisk
                    searchable
                    data={units.data ?? []}
                    value={line.unit}
                    onChange={(value) => setLine(line.key, { unit: value })}
                  />
                </Group>
                <Group gap="xs" grow wrap="nowrap">
                  <TextInput
                    label={st.unitPrice}
                    inputMode="decimal"
                    value={line.unit_price}
                    onChange={(event) =>
                      setLine(line.key, { unit_price: event.currentTarget.value })
                    }
                  />
                  <Select
                    label={st.currencyLabel}
                    data={CURRENCIES}
                    value={line.currency}
                    onChange={(value) => setLine(line.key, { currency: value })}
                  />
                </Group>
                <TextInput
                  label={st.lineNote}
                  value={line.note}
                  onChange={(event) => setLine(line.key, { note: event.currentTarget.value })}
                />
              </SimpleGrid>
            </Paper>
          ))}
          {lines.length === 0 && (
            <Text size="sm" c="dimmed">
              {ct.empty}
            </Text>
          )}
        </Stack>
      ) : (
        doc && (
          <Table.ScrollContainer minWidth={900}>
            <Table striped fz="sm" data-testid="order-lines">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{st.product}</Table.Th>
                  <Table.Th ta="right">{st.quantity}</Table.Th>
                  <Table.Th ta="right">{st.baseQuantity}</Table.Th>
                  <Table.Th ta="right">{st.reserved}</Table.Th>
                  <Table.Th ta="right">{st.planned}</Table.Th>
                  <Table.Th ta="right">{st.shipped}</Table.Th>
                  <Table.Th ta="right">{st.shortage}</Table.Th>
                  <Table.Th ta="right">{st.lineTotal}</Table.Th>
                  {reservable && <Table.Th />}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {doc.lines.map((line) => {
                  const short = Number(line.shortage_quantity) > 0;
                  return (
                    <Table.Tr key={line.id}>
                      <Table.Td>{line.line_no}</Table.Td>
                      <Table.Td>{`${line.product_code} - ${line.product_name}`}</Table.Td>
                      <Table.Td ta="right">
                        <Qty value={line.quantity} unit={line.unit_code} />
                      </Table.Td>
                      <Table.Td ta="right">
                        <Qty value={line.base_quantity} unit={line.base_unit_code} />
                      </Table.Td>
                      <Table.Td ta="right">{formatNumber(line.reserved_quantity)}</Table.Td>
                      <Table.Td ta="right">{formatNumber(line.planned_quantity)}</Table.Td>
                      <Table.Td ta="right">{formatNumber(line.shipped_quantity)}</Table.Td>
                      <Table.Td ta="right">
                        <Text span size="sm" c={short ? "red" : undefined} fw={short ? 600 : 400}>
                          {formatNumber(line.shortage_quantity)}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">
                        {line.line_total ? formatMoney(line.line_total, line.currency) : ""}
                      </Table.Td>
                      {reservable && (
                        <Table.Td>
                          {short && (
                            <Button
                              size="compact-xs"
                              variant="light"
                              onClick={() => setReserveLine(line)}
                            >
                              {st.reserveLot}
                            </Button>
                          )}
                        </Table.Td>
                      )}
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )
      )}

      {doc && doc.totals.length > 0 && (
        <Group justify="flex-end" gap="lg" data-testid="order-totals">
          {doc.totals.map((total) => (
            <Text key={total.currency} fw={600}>
              {`${st.total}: ${formatMoney(total.amount, total.currency)}`}
            </Text>
          ))}
        </Group>
      )}

      {doc && doc.status !== "DRAFT" && (
        <Stack gap="xs">
          <Title order={4}>{st.reservations}</Title>
          <Text size="sm" c="dimmed">
            {st.reservationsIntro}
          </Text>
          <ReservationTable
            rows={[...activeReservations, ...otherReservations]}
            onRelease={reservable ? setReleasing : undefined}
          />
        </Stack>
      )}

      {doc && doc.status !== "DRAFT" && (
        <Stack gap="xs">
          <Title order={4}>{st.shipments}</Title>
          {doc.shipments.length === 0 ? (
            <Text size="sm" c="dimmed">
              {st.noShipments}
            </Text>
          ) : (
            <RowsTable
              testId="order-shipments"
              columns={shipmentColumns.filter(
                (column) => column.header !== st.customer && column.header !== st.order,
              )}
              rows={doc.shipments}
              loading={false}
              error={null}
              onOpen={(row) => navigate(shipmentPath(row.id))}
            />
          )}
        </Stack>
      )}

      <ConfirmModal
        opened={confirmOpen}
        message={st.confirmQuestion}
        confirmLabel={st.confirm}
        loading={confirm.isPending}
        onConfirm={() => confirm.mutate()}
        onClose={() => setConfirmOpen(false)}
      />
      <ConfirmModal
        opened={closeOpen}
        message={st.closeQuestion}
        confirmLabel={st.close}
        loading={close.isPending}
        onConfirm={() => close.mutate()}
        onClose={() => setCloseOpen(false)}
      />
      <ConfirmModal
        opened={releasing !== null}
        message={releasing ? st.releaseQuestion(releasing.lot_no) : ""}
        confirmLabel={st.release}
        danger
        loading={release.isPending}
        onConfirm={() => releasing && release.mutate(releasing)}
        onClose={() => setReleasing(null)}
      />
      {doc && (
        <CancelModal
          opened={cancelOpen}
          cancel={(reason) => cancelSalesOrder(doc.id, reason)}
          onClose={() => setCancelOpen(false)}
          onDone={(saved) => {
            setCancelOpen(false);
            refresh(saved);
          }}
        />
      )}
      {doc && planOpen && (
        <PlanShipmentModal
          order={doc}
          onClose={() => setPlanOpen(false)}
          onDone={(shipment) => {
            setPlanOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["sales"] });
            void queryClient.invalidateQueries({ queryKey: ["workflow"] });
            navigate(shipmentPath(shipment.id));
          }}
        />
      )}
      {doc && reserveLine && (
        <ReserveModal
          order={doc}
          line={reserveLine}
          onClose={() => setReserveLine(null)}
          onDone={(saved) => {
            setReserveLine(null);
            refresh(saved);
          }}
        />
      )}
    </Stack>
  );
}

function ReservationTable({
  rows,
  onRelease,
}: {
  rows: Reservation[];
  onRelease?: (row: Reservation) => void;
}) {
  if (rows.length === 0)
    return (
      <Text size="sm" c="dimmed">
        {st.noReservations}
      </Text>
    );
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table striped fz="sm" data-testid="reservations">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>{st.lot}</Table.Th>
            <Table.Th>{st.expiry}</Table.Th>
            <Table.Th>{st.location}</Table.Th>
            <Table.Th ta="right">{st.quantity}</Table.Th>
            <Table.Th>{st.status}</Table.Th>
            {onRelease && <Table.Th />}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.id} c={row.status === "ACTIVE" ? undefined : "dimmed"}>
              <Table.Td>{row.line_no}</Table.Td>
              <Table.Td>
                <Anchor component={Link} to={`/depo/lotlar/${row.lot}`} size="sm">
                  {row.lot_no}
                </Anchor>
              </Table.Td>
              <Table.Td>{formatDate(row.expiry_date)}</Table.Td>
              <Table.Td>{row.location_code}</Table.Td>
              <Table.Td ta="right">
                <Qty value={row.quantity} unit={row.unit} />
              </Table.Td>
              <Table.Td>{st.reservationStatus[row.status]}</Table.Td>
              {onRelease && (
                <Table.Td>
                  {row.status === "ACTIVE" && (
                    <Button
                      size="compact-xs"
                      color="red"
                      variant="subtle"
                      onClick={() => onRelease(row)}
                    >
                      {st.release}
                    </Button>
                  )}
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function ReserveModal({
  order,
  line,
  onClose,
  onDone,
}: {
  order: SalesOrderDetail;
  line: SalesOrderLine;
  onClose: () => void;
  onDone: (saved: SalesOrderDetail) => void;
}) {
  const candidates = useQuery({
    queryKey: ["sales", "candidates", order.id, line.id],
    queryFn: () => listCandidates(order.id, line.id!),
  });
  const [picked, setPicked] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState("");
  const rows = candidates.data ?? [];
  const keyOf = (row: { lot: number; location: number }) => `${row.lot}-${row.location}`;
  const selected = rows.find((row) => keyOf(row) === picked);
  const mutation = useMutation({
    mutationFn: () =>
      reserveLot(order.id, {
        line: line.id!,
        lot: selected!.lot,
        location: selected!.location,
        quantity: normalizeDecimal(quantity),
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: st.reservedOk });
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened onClose={onClose} title={st.reserveTitle(line.line_no ?? 0)} size="lg">
      <Stack>
        {candidates.isLoading && <Loader size="sm" />}
        {!candidates.isLoading && rows.length === 0 && (
          <Text size="sm" c="dimmed">
            {st.noCandidates}
          </Text>
        )}
        <Radio.Group
          value={picked}
          onChange={(value) => {
            setPicked(value);
            const row = rows.find((candidate) => keyOf(candidate) === value);
            if (row) {
              const max = Math.min(
                Number(row.available_quantity),
                Number(line.shortage_quantity ?? 0),
              );
              setQuantity(trimDecimal(String(max)));
            }
          }}
        >
          <Stack gap="xs">
            {rows.map((row) => (
              <Radio
                key={keyOf(row)}
                value={keyOf(row)}
                disabled={!row.meets_shelf_life}
                label={
                  <Group gap="xs">
                    <Text size="sm" fw={600}>
                      {row.lot_no}
                    </Text>
                    <Text size="sm">{`${st.expiry} ${formatDate(row.expiry_date)}`}</Text>
                    <Text size="sm">{row.location_code}</Text>
                    <Text size="sm">{`${st.available}: ${formatNumber(row.available_quantity)} ${row.unit}`}</Text>
                    {!row.meets_shelf_life && (
                      <Badge color="red" variant="light" size="sm">
                        {st.shelfLifeShort}
                      </Badge>
                    )}
                  </Group>
                }
              />
            ))}
          </Stack>
        </Radio.Group>
        <TextInput
          label={st.reserveQuantity}
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.currentTarget.value)}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button
            disabled={!selected || !quantity.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {st.reserve}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
