import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Modal,
  Pagination,
  Paper,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelPurchaseRequest,
  getPurchasingSettings,
  getSupplierPerformance,
  listExpectedDeliveries,
  listPurchaseOrders,
  listPurchaseRequests,
  listSuggestions,
  savePurchaseRequest,
  savePurchasingSettings,
  type PurchaseOrder,
  type PurchaseOrderStatus,
  type PurchaseRequest,
  type PurchaseRequestStatus,
  type Suggestion,
} from "../../api/purchasing";
import { useCan } from "../../auth/access";
import { PERM, type PermKey } from "../../auth/access.gen";
import { hasAnyRole } from "../../auth/roles";
import { ForbiddenPage } from "../../pages/ForbiddenPage";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { optionLabel } from "../common/useOptions";
import { RowsTable } from "../filling/FillingPage";
import { CancelModal } from "../inventory/CancelModal";
import { today } from "../inventory/config";
import { idOrNull } from "../inventory/options";
import { Qty } from "../inventory/shared";
import { PURCHASING_BASE, purchaseOrderPath } from "./config";
import { usePurchasableMaterials } from "./options";
import { PurchaseOrderStatusBadge, RequestStatusBadge } from "./shared";
import { pt } from "./strings";

const PAGE_SIZE = 50;

// --- talepler ---

interface RequestDraft {
  material: string | null;
  quantity: string;
  need_date: string;
  reason: string;
}

export function RequestModal({
  request,
  initial,
  onClose,
}: {
  request: PurchaseRequest | null;
  initial?: Partial<RequestDraft>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const materials = usePurchasableMaterials();
  const [draft, setDraft] = useState<RequestDraft>(() => ({
    material: request ? String(request.material) : (initial?.material ?? null),
    quantity: request ? trimDecimal(request.quantity) : (initial?.quantity ?? ""),
    need_date: request?.need_date ?? initial?.need_date ?? today(),
    reason: request?.reason ?? initial?.reason ?? "",
  }));
  const [error, setError] = useState("");
  const material = (materials.data ?? []).find((row) => String(row.id) === draft.material);
  const mutation = useMutation({
    mutationFn: () =>
      savePurchaseRequest(request?.id ?? null, {
        material: idOrNull(draft.material)!,
        quantity: normalizeDecimal(draft.quantity),
        need_date: draft.need_date,
        reason: draft.reason.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: pt.requestCreated });
      void queryClient.invalidateQueries({ queryKey: ["purchasing"] });
      void queryClient.invalidateQueries({ queryKey: ["workflow"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={request ? pt.editRequest : pt.requestTitle}>
      <Stack>
        <Select
          label={pt.material}
          withAsterisk
          searchable
          data={(materials.data ?? []).map((row) => ({
            value: String(row.id),
            label: optionLabel(row),
          }))}
          value={draft.material}
          onChange={(value) => setDraft({ ...draft, material: value })}
          nothingFoundMessage={pt.notFound}
        />
        <TextInput
          label={`${pt.quantity}${material ? ` (${material.base_unit_code})` : ""}`}
          withAsterisk
          inputMode="decimal"
          value={draft.quantity}
          onChange={(event) => setDraft({ ...draft, quantity: event.currentTarget.value })}
        />
        <TextInput
          label={pt.needDate}
          type="date"
          withAsterisk
          value={draft.need_date}
          onChange={(event) => setDraft({ ...draft, need_date: event.currentTarget.value })}
        />
        <Textarea
          label={pt.reason}
          autosize
          minRows={2}
          value={draft.reason}
          onChange={(event) => setDraft({ ...draft, reason: event.currentTarget.value })}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button
            disabled={!draft.material || !draft.quantity.trim() || !draft.need_date}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {pt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

const REQUEST_STATUS_OPTIONS = (Object.keys(pt.requestStatus) as PurchaseRequestStatus[]).map(
  (value) => ({ value, label: pt.requestStatus[value] }),
);

function RequestsTab() {
  const { can, user } = useCan();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<PurchaseRequestStatus | null>("OPEN");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<PurchaseRequest | "new" | null>(null);
  const [cancelling, setCancelling] = useState<PurchaseRequest | null>(null);
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  const query = useQuery({
    queryKey: ["purchasing", "requests", status, params],
    queryFn: () => listPurchaseRequests(params, status ? [status] : []),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const requester = can(PERM.PURCHASING_REQUESTS, "change");
  // Başkasının talebini Satın alma siparişleri: Değiştirir düzenler (backend `_can_edit_request`).
  const buyer = can(PERM.PURCHASING_ORDERS, "change");
  const showOrder = can(PERM.PURCHASING_ORDERS);
  const canEdit = (row: PurchaseRequest) =>
    requester && row.status === "OPEN" && (buyer || row.created_by === user?.id);

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={pt.searchRequests}
            placeholder={pt.searchRequests}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={300}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={pt.status}
            placeholder={pt.allStatuses}
            data={REQUEST_STATUS_OPTIONS}
            value={status}
            clearable
            w={200}
            onChange={(value) => {
              setStatus(value as PurchaseRequestStatus | null);
              setPage(1);
            }}
          />
        </Group>
        {requester && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            {pt.newRequest}
          </Button>
        )}
      </Group>
      {query.error && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={900}>
        <Table striped fz="sm" data-testid="purchase-requests">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{pt.number}</Table.Th>
              <Table.Th>{pt.material}</Table.Th>
              <Table.Th ta="right">{pt.quantity}</Table.Th>
              <Table.Th>{pt.needDate}</Table.Th>
              <Table.Th>{pt.source_}</Table.Th>
              <Table.Th>{pt.requestedBy}</Table.Th>
              <Table.Th>{pt.reason}</Table.Th>
              <Table.Th>{pt.status}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(query.data?.results ?? []).map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td>{row.number}</Table.Td>
                <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
                <Table.Td ta="right">
                  <Qty value={row.quantity} unit={row.unit_code} />
                </Table.Td>
                <Table.Td>{formatDate(row.need_date)}</Table.Td>
                <Table.Td>{pt.source[row.source]}</Table.Td>
                <Table.Td>{row.created_by_name ?? ""}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2}>
                    {row.reason}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <RequestStatusBadge status={row.status} />
                    {row.order_id && showOrder && (
                      <Anchor component={Link} to={purchaseOrderPath(row.order_id)} size="sm">
                        {row.order_number}
                      </Anchor>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  {canEdit(row) && (
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => setEditing(row)}>
                        {pt.editRequest}
                      </Button>
                      <Button
                        size="compact-xs"
                        variant="light"
                        color="red"
                        onClick={() => setCancelling(row)}
                      >
                        {pt.cancelRequest}
                      </Button>
                    </Group>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      {editing && (
        <RequestModal
          request={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {cancelling && (
        <CancelModal
          opened
          cancel={(reason) => cancelPurchaseRequest(cancelling.id, reason)}
          onClose={() => setCancelling(null)}
          onDone={() => {
            setCancelling(null);
            void queryClient.invalidateQueries({ queryKey: ["purchasing"] });
          }}
        />
      )}
    </Stack>
  );
}

// --- öneriler ---

function SuggestionsTab() {
  const { can } = useCan();
  const requester = can(PERM.PURCHASING_REQUESTS, "change");
  const [creating, setCreating] = useState<Suggestion | null>(null);
  const query = useQuery({
    queryKey: ["purchasing", "suggestions"],
    queryFn: listSuggestions,
  });
  const rows = query.data ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {pt.suggestionsIntro}
      </Text>
      {query.error && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {pt.noSuggestions}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={980}>
          <Table striped fz="sm" data-testid="purchase-suggestions">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{pt.material}</Table.Th>
                <Table.Th ta="right">{pt.demand}</Table.Th>
                <Table.Th ta="right">{pt.minStock}</Table.Th>
                <Table.Th ta="right">{pt.freeStock}</Table.Th>
                <Table.Th ta="right">{pt.openOrders}</Table.Th>
                <Table.Th ta="right">{pt.openRequests}</Table.Th>
                <Table.Th ta="right">{pt.suggested}</Table.Th>
                <Table.Th>{pt.needDate}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.material}>
                  <Table.Td>
                    <Text size="sm">{`${row.material_code} - ${row.material_name}`}</Text>
                    {row.sources.length > 0 && (
                      <Text size="xs" c="dimmed">
                        {row.sources.map((source) => source.order_number).join(", ")}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">{formatNumber(row.demand)}</Table.Td>
                  <Table.Td ta="right">{formatNumber(row.min_stock)}</Table.Td>
                  <Table.Td ta="right">{formatNumber(row.free_stock)}</Table.Td>
                  <Table.Td ta="right">{formatNumber(row.open_orders)}</Table.Td>
                  <Table.Td ta="right">{formatNumber(row.open_requests)}</Table.Td>
                  <Table.Td ta="right">
                    <Text span size="sm" fw={700}>
                      <Qty value={row.suggested} unit={row.unit_code} />
                    </Text>
                  </Table.Td>
                  <Table.Td>{formatDate(row.need_date)}</Table.Td>
                  <Table.Td>
                    {requester && (
                      <Button size="compact-xs" variant="light" onClick={() => setCreating(row)}>
                        {pt.createRequest}
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {creating && (
        <RequestModal
          request={null}
          initial={{
            material: String(creating.material),
            quantity: trimDecimal(creating.suggested),
            need_date: creating.need_date,
          }}
          onClose={() => setCreating(null)}
        />
      )}
    </Stack>
  );
}

// --- siparişler ---

const ORDER_STATUS_OPTIONS = (Object.keys(pt.orderStatus) as PurchaseOrderStatus[]).map(
  (value) => ({ value, label: pt.orderStatus[value] }),
);

function OrdersTab() {
  const { can } = useCan();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<PurchaseOrderStatus | null>(null);
  const [page, setPage] = useState(1);
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  const query = useQuery({
    queryKey: ["purchasing", "orders", status, params],
    queryFn: () => listPurchaseOrders(params, status ? [status] : []),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const writer = can(PERM.PURCHASING_ORDERS, "change");
  // Tutarlar Fiyatları görür'e bağlıdır; backend fiyatı yalnız onlara gönderir.
  const showPrices = can(PERM.SENSITIVE_PRICES);
  const columns = [
    { header: pt.orderNumber, render: (r: PurchaseOrder) => r.number },
    { header: pt.supplier, render: (r: PurchaseOrder) => r.supplier_name },
    { header: pt.orderDate, render: (r: PurchaseOrder) => formatDate(r.order_date) },
    { header: pt.expectedDate, render: (r: PurchaseOrder) => formatDate(r.expected_date) },
    ...(showPrices
      ? [
          {
            header: pt.total,
            align: "right" as const,
            render: (r: PurchaseOrder) => (r.total ? formatMoney(r.total, r.currency) : ""),
          },
        ]
      : []),
    {
      header: pt.status,
      render: (r: PurchaseOrder) => <PurchaseOrderStatusBadge status={r.status} />,
    },
  ];
  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={pt.searchOrders}
            placeholder={pt.searchOrders}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={300}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={pt.status}
            placeholder={pt.allStatuses}
            data={ORDER_STATUS_OPTIONS}
            value={status}
            clearable
            w={220}
            onChange={(value) => {
              setStatus(value as PurchaseOrderStatus | null);
              setPage(1);
            }}
          />
        </Group>
        {writer && (
          <Button
            leftSection={<IconPlus size={16} />}
            onClick={() => navigate(purchaseOrderPath("yeni"))}
          >
            {pt.newOrder}
          </Button>
        )}
      </Group>
      <RowsTable
        testId="purchase-orders"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(purchaseOrderPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

// --- beklenen teslimatlar ---

function DeliveriesTab() {
  const navigate = useNavigate();
  const { can } = useCan();
  // Teslimat satırı siparişe gider; sipariş sayfası Satın alma siparişleri: Görür ister.
  const openOrder = can(PERM.PURCHASING_ORDERS);
  const query = useQuery({
    queryKey: ["purchasing", "expected-deliveries"],
    queryFn: () => listExpectedDeliveries(),
  });
  const rows = query.data ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {pt.deliveriesIntro}
      </Text>
      {query.error && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {pt.noDeliveries}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={900}>
          <Table striped highlightOnHover fz="sm" data-testid="expected-deliveries">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{pt.expectedDate}</Table.Th>
                <Table.Th>{pt.orderNumber}</Table.Th>
                <Table.Th>{pt.supplier}</Table.Th>
                <Table.Th>{pt.material}</Table.Th>
                <Table.Th ta="right">{pt.quantity}</Table.Th>
                <Table.Th ta="right">{pt.received}</Table.Th>
                <Table.Th ta="right">{pt.pending}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr
                  key={row.order_line}
                  style={openOrder ? { cursor: "pointer" } : undefined}
                  onClick={openOrder ? () => navigate(purchaseOrderPath(row.order_id)) : undefined}
                >
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      {formatDate(row.expected_date)}
                      {row.is_late && (
                        <Badge color="red" variant="light" size="sm">
                          {pt.late}
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>{row.order_number}</Table.Td>
                  <Table.Td>{row.supplier_name}</Table.Td>
                  <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
                  <Table.Td ta="right">
                    <Qty value={row.base_quantity} unit={row.base_unit_code} />
                  </Table.Td>
                  <Table.Td ta="right">{formatNumber(row.received_quantity)}</Table.Td>
                  <Table.Td ta="right">
                    <Text span size="sm" fw={600}>
                      {formatNumber(row.pending_quantity)}
                    </Text>
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

// --- tedarikçi performansı ---

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function PerformanceTab() {
  const [range, setRange] = useState({ date_from: daysAgo(90), date_to: today() });
  const query = useQuery({
    queryKey: ["purchasing", "performance", range],
    queryFn: () => getSupplierPerformance(range),
    enabled: Boolean(range.date_from && range.date_to),
  });
  const rows = query.data ?? [];
  const rate = (value: string | null) => (value === null ? "—" : `%${formatNumber(value, 1)}`);
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {pt.performanceIntro}
      </Text>
      <Group>
        <TextInput
          label={pt.dateFrom}
          type="date"
          value={range.date_from}
          onChange={(event) => setRange({ ...range, date_from: event.currentTarget.value })}
        />
        <TextInput
          label={pt.dateTo}
          type="date"
          value={range.date_to}
          onChange={(event) => setRange({ ...range, date_to: event.currentTarget.value })}
        />
      </Group>
      {query.error && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {pt.noPerformance}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={760}>
          <Table striped fz="sm" data-testid="supplier-performance">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{pt.supplier}</Table.Th>
                <Table.Th ta="right">{pt.dueLines}</Table.Th>
                <Table.Th ta="right">{pt.onTime}</Table.Th>
                <Table.Th ta="right">{pt.onTimeRate}</Table.Th>
                <Table.Th ta="right">{pt.receivedLots}</Table.Th>
                <Table.Th ta="right">{pt.rejectedLots}</Table.Th>
                <Table.Th ta="right">{pt.rejectRate}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.supplier}>
                  <Table.Td>{`${row.supplier_code} - ${row.supplier_name}`}</Table.Td>
                  <Table.Td ta="right">{row.due_lines}</Table.Td>
                  <Table.Td ta="right">{row.on_time_lines}</Table.Td>
                  <Table.Td ta="right">{rate(row.on_time_rate)}</Table.Td>
                  <Table.Td ta="right">{row.received_lots}</Table.Td>
                  <Table.Td ta="right">{row.rejected_lots}</Table.Td>
                  <Table.Td ta="right">{rate(row.reject_rate)}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

// --- ayarlar (yönetim) ---

function SettingsTab() {
  const { can } = useCan();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["purchasing", "settings"], queryFn: getPurchasingSettings });
  if (query.isLoading) return null;
  if (query.error || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  return (
    <SettingsForm
      key={query.data.updated_at}
      limit={query.data.approval_limit_try}
      tolerance={query.data.over_receipt_tolerance_pct}
      updated={
        query.data.updated_by_name
          ? `${query.data.updated_by_name} · ${formatDateTime(query.data.updated_at)}`
          : ""
      }
      editable={can(PERM.PURCHASING_SETTINGS, "change")}
      onSaved={(saved) => queryClient.setQueryData(["purchasing", "settings"], saved)}
    />
  );
}

function SettingsForm({
  limit,
  tolerance,
  updated,
  editable,
  onSaved,
}: {
  limit: string | null;
  tolerance: string;
  updated: string;
  editable: boolean;
  onSaved: (saved: Awaited<ReturnType<typeof savePurchasingSettings>>) => void;
}) {
  const [values, setValues] = useState({
    limit: limit ? trimDecimal(limit) : "",
    tolerance: trimDecimal(tolerance),
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      savePurchasingSettings({
        approval_limit_try: values.limit.trim() ? normalizeDecimal(values.limit) : null,
        over_receipt_tolerance_pct: normalizeDecimal(values.tolerance),
      }),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: pt.settingsSaved });
      onSaved(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Paper withBorder p="md" radius="md" maw={520}>
      <Stack>
        <TextInput
          label={pt.approvalLimit}
          description={pt.approvalLimitHint}
          inputMode="decimal"
          readOnly={!editable}
          value={values.limit}
          onChange={(event) => setValues({ ...values, limit: event.currentTarget.value })}
        />
        <TextInput
          label={pt.tolerance}
          description={pt.toleranceHint}
          inputMode="decimal"
          readOnly={!editable}
          value={values.tolerance}
          onChange={(event) => setValues({ ...values, tolerance: event.currentTarget.value })}
        />
        {updated && <Text size="xs" c="dimmed">{`${pt.lastUpdated}: ${updated}`}</Text>}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        {editable && (
          <Group justify="flex-end">
            <Button loading={mutation.isPending} onClick={() => mutation.mutate()}>
              {pt.save}
            </Button>
          </Group>
        )}
      </Stack>
    </Paper>
  );
}

interface TabDef {
  slug: string;
  label: string;
  /** Sekmeyi açan bölüm (Görür). */
  section: PermKey;
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  {
    slug: "siparisler",
    label: pt.tabs.orders,
    section: PERM.PURCHASING_ORDERS,
    render: () => <OrdersTab />,
  },
  {
    slug: "teslimatlar",
    label: pt.tabs.deliveries,
    section: PERM.PURCHASING_DELIVERIES,
    render: () => <DeliveriesTab />,
  },
  {
    slug: "talepler",
    label: pt.tabs.requests,
    section: PERM.PURCHASING_REQUESTS,
    render: () => <RequestsTab />,
  },
  {
    slug: "oneriler",
    label: pt.tabs.suggestions,
    section: PERM.PURCHASING_SUGGESTIONS,
    render: () => <SuggestionsTab />,
  },
  {
    slug: "performans",
    label: pt.tabs.performance,
    section: PERM.PURCHASING_PERFORMANCE,
    render: () => <PerformanceTab />,
  },
  {
    slug: "ayarlar",
    label: pt.tabs.settings,
    section: PERM.PURCHASING_SETTINGS,
    render: () => <SettingsTab />,
  },
];

/** Satın alma: sekmeler (`/satin-alma/<sekme>`). Depo siparişleri ve beklenen teslimatları görür
 * (tutarsız); talep açan roller yalnızca talepler sekmesini görür. */
export function PurchasingPage() {
  const { tab } = useParams();
  const { can, user } = useCan();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => can(item.section));
  // Varsayılan sekme sırası rol görünümüdür (plan §5.9); görünmüyorsa ilk görünen sekme.
  const preferred = hasAnyRole(user, ["satin_alma", "yonetim"])
    ? "siparisler"
    : hasAnyRole(user, ["satin_alma", "yonetim", "depo"])
      ? "teslimatlar"
      : "talepler";
  const fallback = visible.find((item) => item.slug === preferred) ?? visible[0];
  if (!fallback) return <ForbiddenPage />;
  const current = tab ? visible.find((item) => item.slug === tab) : fallback;
  if (!current) return <Navigate to={PURCHASING_BASE} replace />;

  return (
    <Stack>
      <Title order={2}>{pt.title}</Title>
      <Tabs
        value={current.slug}
        onChange={(value) => value && navigate(`${PURCHASING_BASE}/${value}`)}
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
