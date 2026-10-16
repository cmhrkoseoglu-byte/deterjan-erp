import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Checkbox,
  Grid,
  Group,
  Loader,
  Modal,
  MultiSelect,
  Paper,
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
  IconFileTypePdf,
  IconLock,
  IconPackageImport,
  IconPlus,
  IconSend,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  approvePurchaseOrder,
  cancelPurchaseOrder,
  closePurchaseOrder,
  getPurchaseOrder,
  listPurchaseRequests,
  purchaseOrderPdfUrl,
  receivePurchaseOrder,
  returnPurchaseOrder,
  savePurchaseOrder,
  sendPurchaseOrder,
  submitPurchaseOrder,
  type PurchaseOrderDetail,
  type PurchaseOrderLine,
  type PurchaseOrderPayload,
} from "../../api/purchasing";
import type { Currency } from "../../api/sales";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { CancelModal } from "../inventory/CancelModal";
import { receiptPath, today } from "../inventory/config";
import { idOrNull, useLocations } from "../inventory/options";
import { Info, Qty } from "../inventory/shared";
import {
  CANCELLABLE_STATUSES,
  ORDER_WRITE_ROLES,
  PURCHASING_BASE,
  purchaseOrderPath,
  RECEIVABLE_STATUSES,
  RECEIVE_ROLES,
} from "./config";
import { usePurchasableMaterials } from "./options";
import { PurchaseOrderStatusBadge } from "./shared";
import { pt } from "./strings";

const CURRENCIES = (Object.keys(pt.currency) as Currency[]).map((value) => ({
  value,
  label: pt.currency[value],
}));

interface LineDraft {
  key: string;
  id?: number;
  material: string | null;
  quantity: string;
  unit: string | null;
  unit_price: string;
  expected_date: string;
  note: string;
  requests: string[];
}

interface HeaderDraft {
  supplier: string | null;
  order_date: string;
  currency: Currency;
  exchange_rate: string;
  notes: string;
}

let lineSeq = 0;
const newKey = () => `n${++lineSeq}`;
const str = (value: number | null | undefined) => (value ? String(value) : null);

function emptyLine(): LineDraft {
  return {
    key: newKey(),
    material: null,
    quantity: "",
    unit: null,
    unit_price: "",
    expected_date: today(),
    note: "",
    requests: [],
  };
}

function toDraft(doc: PurchaseOrderDetail | null): { header: HeaderDraft; lines: LineDraft[] } {
  if (!doc) {
    return {
      header: {
        supplier: null,
        order_date: today(),
        currency: "TRY",
        exchange_rate: "1",
        notes: "",
      },
      lines: [emptyLine()],
    };
  }
  return {
    header: {
      supplier: str(doc.supplier),
      order_date: doc.order_date,
      currency: doc.currency,
      exchange_rate: doc.exchange_rate ? trimDecimal(doc.exchange_rate) : "1",
      notes: doc.notes,
    },
    lines: doc.lines.map((line) => ({
      key: `l${line.id}`,
      id: line.id,
      material: str(line.material),
      quantity: trimDecimal(line.quantity),
      unit: str(line.unit),
      unit_price: line.unit_price ? trimDecimal(line.unit_price) : "",
      expected_date: line.expected_date,
      note: line.note ?? "",
      requests: (line.requests ?? []).map(String),
    })),
  };
}

function toPayload(header: HeaderDraft, lines: LineDraft[]): PurchaseOrderPayload {
  return {
    supplier: idOrNull(header.supplier),
    order_date: header.order_date,
    currency: header.currency,
    exchange_rate: header.currency === "TRY" ? "1" : normalizeDecimal(header.exchange_rate),
    notes: header.notes.trim(),
    lines: lines
      .filter((line) => line.material || line.quantity.trim())
      .map((line): PurchaseOrderLine => ({
        ...(line.id ? { id: line.id } : {}),
        material: idOrNull(line.material)!,
        quantity: normalizeDecimal(line.quantity),
        unit: idOrNull(line.unit)!,
        unit_price: normalizeDecimal(line.unit_price),
        expected_date: line.expected_date,
        note: line.note.trim(),
        requests: line.requests.map(Number),
      })),
  };
}

/** Satın alma siparişi: taslak düzenlenir, D-13'e göre onaylanır, gönderilir, mal kabul açılır. */
export function PurchaseOrderPage() {
  const param = useParams().orderId;
  const isNew = param === "yeni";
  const orderId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["purchasing", "order", orderId],
    queryFn: () => getPurchaseOrder(orderId!),
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
          <RecordPanel contentType="purchasing.purchaseorder" objectId={doc.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

/** Seçili malzemenin açık talepleri (satıra bağlanabilir). */
function useOpenRequests() {
  return useQuery({
    queryKey: ["purchasing", "requests", "open-options"],
    staleTime: 30_000,
    queryFn: async () => (await listPurchaseRequests({ page_size: 500 }, ["OPEN"])).results,
  });
}

function OrderForm({ doc }: { doc: PurchaseOrderDetail | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const writer = hasAnyRole(user, ORDER_WRITE_ROLES);
  const editable = writer && (!doc || doc.status === "DRAFT");
  const [{ header, lines }, setDraft] = useState(() => toDraft(doc));
  const [error, setError] = useState("");
  const [approveOpen, setApproveOpen] = useState(false);
  const [returnOpen, setReturnOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [sendOpen, setSendOpen] = useState(false);
  const [receiveOpen, setReceiveOpen] = useState(false);
  const suppliers = useOptions({ endpoint: "suppliers" });
  const units = useOptions({ endpoint: "units" });
  const materials = usePurchasableMaterials();
  const openRequests = useOpenRequests();

  useEffect(() => setDraft(toDraft(doc)), [doc]);

  const materialById = new Map((materials.data ?? []).map((row) => [String(row.id), row]));
  const materialOptions = (materials.data ?? []).map((row) => ({
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
  const requestOptions = (line: LineDraft) => {
    const current = doc?.lines.find((row) => row.id === line.id);
    const linked = (current?.requests ?? []).map((id, index) => ({
      value: String(id),
      label: current?.request_numbers?.[index] ?? String(id),
    }));
    const open = (openRequests.data ?? [])
      .filter((row) => String(row.material) === line.material)
      .map((row) => ({
        value: String(row.id),
        label: `${row.number} · ${formatNumber(row.quantity)} ${row.unit_code} · ${formatDate(row.need_date)}`,
      }));
    return [...linked, ...open.filter((o) => !linked.some((l) => l.value === o.value))];
  };

  const refresh = (saved: PurchaseOrderDetail) => {
    queryClient.setQueryData(["purchasing", "order", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["purchasing"] });
    void queryClient.invalidateQueries({ queryKey: ["workflow"] });
  };
  const onError = (err: unknown) => setError(getErrorMessage(err));
  const saveDraft = () => savePurchaseOrder(doc?.id ?? null, toPayload(header, lines));

  const save = useMutation({
    mutationFn: saveDraft,
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: pt.saved });
      refresh(saved);
      if (!doc) navigate(purchaseOrderPath(saved.id), { replace: true });
    },
    onError,
  });
  const submit = useMutation({
    mutationFn: async () => submitPurchaseOrder((await saveDraft()).id),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: pt.submitted });
      refresh(saved);
    },
    onError,
  });
  const approve = useMutation({
    mutationFn: async () => {
      const saved = doc!.status === "DRAFT" ? await saveDraft() : doc!;
      return approvePurchaseOrder(saved.id);
    },
    onSuccess: (saved) => {
      setError("");
      setApproveOpen(false);
      notifications.show({ color: "green", message: pt.approved });
      refresh(saved);
    },
    onError: (err) => {
      setApproveOpen(false);
      onError(err);
    },
  });

  const title = doc ? pt.orderTitle(doc.number) : pt.orderNew;
  const pending = doc?.status === "PENDING_APPROVAL";
  const canApprove = !!doc && doc.can_approve && (doc.status === "DRAFT" || pending);
  const needsManagement = !!doc && writer && doc.status === "DRAFT" && !doc.can_approve;
  const receivable =
    !!doc && hasAnyRole(user, RECEIVE_ROLES) && RECEIVABLE_STATUSES.includes(doc.status);
  const showPrices = writer;

  return (
    <Stack>
      <Anchor component={Link} to={`${PURCHASING_BASE}/siparisler`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {pt.tabs.orders}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{title}</Title>
          {doc && <PurchaseOrderStatusBadge status={doc.status} />}
        </Group>
        <Group gap="xs">
          {editable && (
            <Button variant="default" loading={save.isPending} onClick={() => save.mutate()}>
              {pt.saveDraft}
            </Button>
          )}
          {editable && doc && needsManagement && (
            <Button
              leftSection={<IconSend size={16} />}
              loading={submit.isPending}
              onClick={() => submit.mutate()}
            >
              {pt.submit}
            </Button>
          )}
          {canApprove && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setApproveOpen(true)}
            >
              {pt.approve}
            </Button>
          )}
          {pending && hasAnyRole(user, ["yonetim"]) && (
            <Button variant="light" onClick={() => setReturnOpen(true)}>
              {pt.returnToDraft}
            </Button>
          )}
          {writer && doc && doc.status === "APPROVED" && (
            <Button leftSection={<IconSend size={16} />} onClick={() => setSendOpen(true)}>
              {pt.send}
            </Button>
          )}
          {receivable && (
            <Button
              leftSection={<IconPackageImport size={16} />}
              onClick={() => setReceiveOpen(true)}
            >
              {pt.receive}
            </Button>
          )}
          {writer && doc && doc.status !== "DRAFT" && (
            <Button
              variant="default"
              component="a"
              href={purchaseOrderPdfUrl(doc.id)}
              target="_blank"
              rel="noopener"
              leftSection={<IconFileTypePdf size={16} />}
            >
              {pt.pdf}
            </Button>
          )}
          {writer && doc && doc.status === "PARTIALLY_RECEIVED" && (
            <Button
              variant="light"
              leftSection={<IconLock size={16} />}
              onClick={() => setCloseOpen(true)}
            >
              {pt.close}
            </Button>
          )}
          {writer && doc && CANCELLABLE_STATUSES.includes(doc.status) && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {pt.cancelOrder}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      {needsManagement && (
        <Text size="sm" c="dimmed">
          {pt.needsManagement}
        </Text>
      )}

      {editable ? (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
            <Select
              label={pt.supplier}
              withAsterisk
              searchable
              data={suppliers.data ?? []}
              value={header.supplier}
              onChange={(value) => setHeader({ supplier: value })}
              nothingFoundMessage={pt.notFound}
            />
            <TextInput
              label={pt.orderDate}
              type="date"
              withAsterisk
              value={header.order_date}
              onChange={(event) => setHeader({ order_date: event.currentTarget.value })}
            />
            <Group gap="xs" grow wrap="nowrap">
              <Select
                label={pt.currencyLabel}
                data={CURRENCIES}
                value={header.currency}
                allowDeselect={false}
                onChange={(value) =>
                  setHeader({
                    currency: (value ?? "TRY") as Currency,
                    exchange_rate: value === "TRY" ? "1" : header.exchange_rate,
                  })
                }
              />
              {header.currency !== "TRY" && (
                <TextInput
                  label={pt.exchangeRate}
                  withAsterisk
                  inputMode="decimal"
                  value={header.exchange_rate}
                  onChange={(event) => setHeader({ exchange_rate: event.currentTarget.value })}
                />
              )}
            </Group>
            <Textarea
              label={pt.notes}
              autosize
              minRows={1}
              value={header.notes}
              onChange={(event) => setHeader({ notes: event.currentTarget.value })}
            />
          </SimpleGrid>
          {header.currency !== "TRY" && (
            <Text size="xs" c="dimmed" mt="xs">
              {pt.exchangeRateHint}
            </Text>
          )}
        </Paper>
      ) : (
        doc && (
          <Paper withBorder p="md" radius="md">
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
              <Info label={pt.supplier}>
                <Text size="sm">{`${doc.supplier_code} - ${doc.supplier_name}`}</Text>
              </Info>
              <Info label={pt.orderDate}>
                <Text size="sm">{formatDate(doc.order_date)}</Text>
              </Info>
              {showPrices && (
                <Info label={pt.total}>
                  <Text size="sm">
                    {doc.total ? formatMoney(doc.total, doc.currency) : ""}
                    {doc.currency !== "TRY" && doc.total_try
                      ? ` (${formatMoney(doc.total_try, "TRY")}, kur ${formatNumber(doc.exchange_rate)})`
                      : ""}
                  </Text>
                </Info>
              )}
              {doc.approved_at && (
                <Info label={pt.approvalInfo}>
                  <Text size="sm">{`${doc.approved_by_name ?? ""} · ${formatDateTime(doc.approved_at)}`}</Text>
                </Info>
              )}
              {doc.sent_at && (
                <Info label={pt.sentInfo}>
                  <Text size="sm">
                    {`${doc.sent_by_name ?? ""} · ${formatDateTime(doc.sent_at)}${doc.sent_to ? ` · ${doc.sent_to}` : ""}`}
                  </Text>
                </Info>
              )}
              <Info label={pt.notes}>
                <Text size="sm">{doc.notes}</Text>
              </Info>
              {doc.closed_note && (
                <Info label={pt.closedInfo}>
                  <Text size="sm">{doc.closed_note}</Text>
                </Info>
              )}
              {doc.status === "CANCELLED" && (
                <Info label={pt.cancelInfo}>
                  <Text size="sm">{doc.cancel_reason}</Text>
                </Info>
              )}
            </SimpleGrid>
            {!showPrices && (
              <Text size="xs" c="dimmed" mt="xs">
                {pt.pricesHidden}
              </Text>
            )}
          </Paper>
        )
      )}

      <Group justify="space-between">
        <Title order={4}>{pt.lines}</Title>
        {editable && (
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() =>
              setDraft((current) => ({ ...current, lines: [...current.lines, emptyLine()] }))
            }
          >
            {pt.addLine}
          </Button>
        )}
      </Group>

      {editable ? (
        <Stack gap="sm">
          {lines.map((line, index) => (
            <Paper key={line.key} withBorder p="sm" radius="md" data-testid="purchase-line">
              <Group justify="space-between" mb={4}>
                <Text size="sm" fw={600}>
                  {index + 1}
                </Text>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  aria-label={pt.removeLine}
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
                  label={pt.material}
                  withAsterisk
                  searchable
                  data={materialOptions}
                  value={line.material}
                  nothingFoundMessage={pt.notFound}
                  onChange={(value) => {
                    const picked = value ? materialById.get(value) : undefined;
                    setLine(line.key, {
                      material: value,
                      unit: line.unit ?? (picked ? String(picked.base_unit) : null),
                      requests: [],
                    });
                  }}
                />
                <Group gap="xs" grow wrap="nowrap">
                  <TextInput
                    label={pt.quantity}
                    withAsterisk
                    inputMode="decimal"
                    value={line.quantity}
                    onChange={(event) => setLine(line.key, { quantity: event.currentTarget.value })}
                  />
                  <Select
                    label={pt.unit}
                    withAsterisk
                    searchable
                    data={units.data ?? []}
                    value={line.unit}
                    onChange={(value) => setLine(line.key, { unit: value })}
                  />
                </Group>
                <TextInput
                  label={`${pt.unitPrice} (${pt.currency[header.currency]})`}
                  withAsterisk
                  inputMode="decimal"
                  value={line.unit_price}
                  onChange={(event) => setLine(line.key, { unit_price: event.currentTarget.value })}
                />
                <TextInput
                  label={pt.expectedDate}
                  type="date"
                  withAsterisk
                  value={line.expected_date}
                  onChange={(event) =>
                    setLine(line.key, { expected_date: event.currentTarget.value })
                  }
                />
                <MultiSelect
                  label={pt.requests}
                  placeholder={line.material ? pt.selectRequests : undefined}
                  data={requestOptions(line)}
                  value={line.requests}
                  disabled={!line.material}
                  clearable
                  onChange={(value) => setLine(line.key, { requests: value })}
                />
                <TextInput
                  label={pt.lineNote}
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
            <Table striped fz="sm" data-testid="purchase-lines">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{pt.material}</Table.Th>
                  <Table.Th ta="right">{pt.quantity}</Table.Th>
                  {showPrices && <Table.Th ta="right">{pt.unitPrice}</Table.Th>}
                  {showPrices && <Table.Th ta="right">{pt.lineTotal}</Table.Th>}
                  <Table.Th>{pt.expectedDate}</Table.Th>
                  <Table.Th ta="right">{pt.received}</Table.Th>
                  <Table.Th ta="right">{pt.pending}</Table.Th>
                  <Table.Th>{pt.requests}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {doc.lines.map((line) => (
                  <Table.Tr key={line.id}>
                    <Table.Td>{line.line_no}</Table.Td>
                    <Table.Td>{`${line.material_code} - ${line.material_name}`}</Table.Td>
                    <Table.Td ta="right">
                      <Qty value={line.quantity} unit={line.unit_code} />
                    </Table.Td>
                    {showPrices && (
                      <Table.Td ta="right">
                        {line.unit_price ? formatMoney(line.unit_price, doc.currency) : ""}
                      </Table.Td>
                    )}
                    {showPrices && (
                      <Table.Td ta="right">
                        {line.line_total ? formatMoney(line.line_total, doc.currency) : ""}
                      </Table.Td>
                    )}
                    <Table.Td>{formatDate(line.expected_date)}</Table.Td>
                    <Table.Td ta="right">
                      <Qty value={line.received_quantity} unit={line.base_unit_code} />
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={line.pending_quantity} unit={line.base_unit_code} />
                    </Table.Td>
                    <Table.Td>{(line.request_numbers ?? []).join(", ")}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )
      )}

      {doc && showPrices && doc.total && (
        <Group justify="flex-end" gap="lg" data-testid="purchase-total">
          <Text fw={600}>{`${pt.total}: ${formatMoney(doc.total, doc.currency)}`}</Text>
          {doc.currency !== "TRY" && doc.total_try && (
            <Text fw={600}>{`${pt.totalTry}: ${formatMoney(doc.total_try, "TRY")}`}</Text>
          )}
        </Group>
      )}

      {doc && doc.status !== "DRAFT" && doc.status !== "PENDING_APPROVAL" && (
        <Stack gap="xs">
          <Title order={4}>{pt.receipts}</Title>
          {doc.receipts.length === 0 ? (
            <Text size="sm" c="dimmed">
              {pt.noReceipts}
            </Text>
          ) : (
            <Group gap="sm">
              {doc.receipts.map((receipt) => (
                <Anchor key={receipt.id} component={Link} to={receiptPath(receipt.id)} size="sm">
                  {`${receipt.number} · ${formatDate(receipt.receipt_date)} · ${
                    receipt.status === "POSTED"
                      ? "Kaydedildi"
                      : receipt.status === "DRAFT"
                        ? "Taslak"
                        : "İptal"
                  }`}
                </Anchor>
              ))}
            </Group>
          )}
        </Stack>
      )}

      <ConfirmModal
        opened={approveOpen}
        message={pt.approveQuestion(doc?.total_try ? formatMoney(doc.total_try, "TRY") : "")}
        confirmLabel={pt.approve}
        loading={approve.isPending}
        onConfirm={() => approve.mutate()}
        onClose={() => setApproveOpen(false)}
      />
      {doc && returnOpen && (
        <NoteModal
          title={pt.returnTitle}
          confirmLabel={pt.returnToDraft}
          action={(note) => returnPurchaseOrder(doc.id, note)}
          done={pt.returned}
          onClose={() => setReturnOpen(false)}
          onDone={refresh}
        />
      )}
      {doc && closeOpen && (
        <NoteModal
          title={pt.closeTitle}
          confirmLabel={pt.close}
          action={(note) => closePurchaseOrder(doc.id, note)}
          done={pt.closed}
          onClose={() => setCloseOpen(false)}
          onDone={refresh}
        />
      )}
      {doc && sendOpen && (
        <SendModal doc={doc} onClose={() => setSendOpen(false)} onDone={refresh} />
      )}
      {doc && receiveOpen && (
        <ReceiveModal
          doc={doc}
          onClose={() => setReceiveOpen(false)}
          onDone={(receipt) => {
            setReceiveOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["purchasing"] });
            void queryClient.invalidateQueries({ queryKey: ["inventory"] });
            notifications.show({ color: "green", message: pt.receiptCreated(receipt.number) });
            navigate(receiptPath(receipt.id));
          }}
        />
      )}
      {doc && (
        <CancelModal
          opened={cancelOpen}
          cancel={(reason) => cancelPurchaseOrder(doc.id, reason)}
          onClose={() => setCancelOpen(false)}
          onDone={(saved) => {
            setCancelOpen(false);
            refresh(saved);
          }}
        />
      )}
    </Stack>
  );
}

function NoteModal({
  title,
  confirmLabel,
  action,
  done,
  onClose,
  onDone,
}: {
  title: string;
  confirmLabel: string;
  action: (note: string) => Promise<PurchaseOrderDetail>;
  done: string;
  onClose: () => void;
  onDone: (saved: PurchaseOrderDetail) => void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => action(note.trim()),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: done });
      onDone(saved);
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={title}>
      <Stack>
        <Textarea
          label={pt.noteLabel}
          withAsterisk
          autosize
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
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
            disabled={!note.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Gönderim: tedarikçi e-postası görünür ve düzenlenebilir; kullanıcı onaylayınca PDF gider. */
function SendModal({
  doc,
  onClose,
  onDone,
}: {
  doc: PurchaseOrderDetail;
  onClose: () => void;
  onDone: (saved: PurchaseOrderDetail) => void;
}) {
  const [byEmail, setByEmail] = useState(Boolean(doc.supplier_email));
  const [email, setEmail] = useState(doc.supplier_email);
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => sendPurchaseOrder(doc.id, byEmail ? email.trim() : ""),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: pt.sent });
      onDone(saved);
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={pt.sendTitle}>
      <Stack>
        <Checkbox
          label={pt.sendByEmail}
          checked={byEmail}
          onChange={(event) => setByEmail(event.currentTarget.checked)}
        />
        {byEmail ? (
          <TextInput
            label={pt.sendEmail}
            description={pt.sendHint}
            type="email"
            withAsterisk
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
          />
        ) : (
          <Text size="sm" c="dimmed">
            {pt.sendWithoutEmail}
          </Text>
        )}
        <Anchor href={purchaseOrderPdfUrl(doc.id)} target="_blank" rel="noopener" size="sm">
          {`${doc.number}.pdf`}
        </Anchor>
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
            leftSection={<IconSend size={16} />}
            disabled={byEmail && !email.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {pt.send}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

interface ReceiveLineDraft {
  order_line: number;
  label: string;
  unit: string;
  pending: string;
  selected: boolean;
  quantity: string;
  supplier_lot_no: string;
  manufactured_at: string;
  expiry_date: string;
}

/** Siparişten taslak mal kabul: satırlar bekleyen miktarla dolar; birim ve fiyat siparişten. */
function ReceiveModal({
  doc,
  onClose,
  onDone,
}: {
  doc: PurchaseOrderDetail;
  onClose: () => void;
  onDone: (receipt: { id: number; number: string }) => void;
}) {
  const locations = useLocations();
  const quarantineOptions = (locations.data ?? []).filter((row) => row.type === "QUARANTINE");
  const storageOptions = (locations.data ?? []).filter((row) => row.type !== "QUARANTINE");
  const [header, setHeader] = useState({
    receipt_date: today(),
    delivery_note_no: "",
    quarantine_location: null as string | null,
    storage_location: null as string | null,
    note: "",
  });
  const [rows, setRows] = useState<ReceiveLineDraft[]>(() =>
    doc.lines
      .filter((line) => Number(line.pending_quantity) > 0)
      .map((line) => ({
        order_line: line.id!,
        label: `${line.material_code} - ${line.material_name}`,
        unit: line.unit_code ?? "",
        pending: line.pending_quantity ?? "0",
        selected: true,
        // Bekleyen miktar temel birimde; satır birimi temel birimse aynen önerilir.
        quantity:
          line.unit_code === line.base_unit_code ? trimDecimal(line.pending_quantity ?? "") : "",
        supplier_lot_no: "",
        manufactured_at: "",
        expiry_date: "",
      })),
  );
  const [error, setError] = useState("");
  const setRow = (id: number, patch: Partial<ReceiveLineDraft>) =>
    setRows((current) =>
      current.map((row) => (row.order_line === id ? { ...row, ...patch } : row)),
    );
  const chosen = rows.filter((row) => row.selected);
  const mutation = useMutation({
    mutationFn: () =>
      receivePurchaseOrder(doc.id, {
        receipt_date: header.receipt_date,
        delivery_note_no: header.delivery_note_no.trim(),
        quarantine_location: idOrNull(header.quarantine_location),
        storage_location: idOrNull(header.storage_location),
        note: header.note.trim(),
        lines: chosen.map((row) => ({
          order_line: row.order_line,
          quantity: normalizeDecimal(row.quantity),
          supplier_lot_no: row.supplier_lot_no.trim(),
          manufactured_at: row.manufactured_at || null,
          expiry_date: row.expiry_date || null,
        })),
      }),
    onSuccess: onDone,
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={pt.receiveTitle} size="xl">
      <Stack>
        <Text size="sm" c="dimmed">
          {pt.receiveHint}
        </Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label={pt.receiptDate}
            type="date"
            withAsterisk
            value={header.receipt_date}
            onChange={(event) => setHeader({ ...header, receipt_date: event.currentTarget.value })}
          />
          <TextInput
            label={pt.deliveryNote}
            value={header.delivery_note_no}
            onChange={(event) =>
              setHeader({ ...header, delivery_note_no: event.currentTarget.value })
            }
          />
          <Select
            label={pt.quarantineLocation}
            clearable
            data={quarantineOptions}
            value={header.quarantine_location}
            onChange={(value) => setHeader({ ...header, quarantine_location: value })}
          />
          <Select
            label={pt.storageLocation}
            clearable
            searchable
            data={storageOptions}
            value={header.storage_location}
            onChange={(value) => setHeader({ ...header, storage_location: value })}
          />
        </SimpleGrid>
        {rows.map((row) => (
          <Paper key={row.order_line} withBorder p="sm" radius="md" data-testid="receive-line">
            <Checkbox
              label={`${row.label} · ${pt.pending}: ${formatNumber(row.pending)}`}
              checked={row.selected}
              onChange={(event) =>
                setRow(row.order_line, { selected: event.currentTarget.checked })
              }
              mb="xs"
            />
            {row.selected && (
              <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
                <TextInput
                  label={`${pt.receiveQuantity} (${row.unit})`}
                  withAsterisk
                  inputMode="decimal"
                  value={row.quantity}
                  onChange={(event) =>
                    setRow(row.order_line, { quantity: event.currentTarget.value })
                  }
                />
                <TextInput
                  label={pt.supplierLot}
                  value={row.supplier_lot_no}
                  onChange={(event) =>
                    setRow(row.order_line, { supplier_lot_no: event.currentTarget.value })
                  }
                />
                <TextInput
                  label={pt.manufacturedAt}
                  type="date"
                  value={row.manufactured_at}
                  onChange={(event) =>
                    setRow(row.order_line, { manufactured_at: event.currentTarget.value })
                  }
                />
                <TextInput
                  label={pt.expiryDate}
                  type="date"
                  value={row.expiry_date}
                  onChange={(event) =>
                    setRow(row.order_line, { expiry_date: event.currentTarget.value })
                  }
                />
              </SimpleGrid>
            )}
          </Paper>
        ))}
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
            leftSection={<IconPackageImport size={16} />}
            disabled={chosen.length === 0 || chosen.some((row) => !row.quantity.trim())}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {pt.receive}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
