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
  IconFlame,
  IconPlus,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listLots } from "../../api/inventory";
import { listRecords, type Material } from "../../api/masterdata";
import { listShipments } from "../../api/sales";
import {
  cancelReturn,
  getReturn,
  receiveReturn,
  saveReturn,
  scrapReturnLine,
  type CustomerReturnDetail,
  type ReturnDisposition,
  type ReturnLine,
  type ReturnPayload,
} from "../../api/returns";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime } from "../../i18n/format";
import { MENU } from "../../layout/menu";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { CancelModal } from "../inventory/CancelModal";
import { lotPath, today } from "../inventory/config";
import { idOrNull, useLocations } from "../inventory/options";
import { Info, LotStatusBadge, Qty } from "../inventory/shared";
import { samplePath } from "../quality/config";
import { shipmentPath } from "../sales/config";
import {
  DISPOSITION_COLOR,
  RETURN_EDIT_ROLES,
  RETURN_RECEIVE_ROLES,
  RETURN_SCRAP_ROLES,
  RETURNS_BASE,
  returnPath,
} from "./config";
import { ReturnStatusBadge } from "./ReturnsPage";
import { rt } from "./strings";

interface LineDraft {
  key: string;
  id?: number;
  product: string | null;
  lot: string | null;
  quantity: string;
  unit: string | null;
}

interface HeaderDraft {
  customer: string | null;
  shipment: string | null;
  return_date: string;
  reason: string;
  quarantine_location: string | null;
  note: string;
}

/** Sevkiyat detayını açabilen roller: sevkiyat menüsünün rolleri (routes.tsx `salesPage`). */
const SHIPMENT_VIEW_ROLES = MENU.find((item) => item.key === "sales")!.roles;

let lineSeq = 0;
const newKey = () => `n${++lineSeq}`;
const str = (value: number | null | undefined) => (value ? String(value) : null);

function emptyLine(): LineDraft {
  return { key: newKey(), product: null, lot: null, quantity: "", unit: null };
}

function toDraft(doc: CustomerReturnDetail | null): { header: HeaderDraft; lines: LineDraft[] } {
  if (!doc) {
    return {
      header: {
        customer: null,
        shipment: null,
        return_date: today(),
        reason: "",
        quarantine_location: null,
        note: "",
      },
      lines: [emptyLine()],
    };
  }
  return {
    header: {
      customer: str(doc.customer),
      shipment: str(doc.shipment),
      return_date: doc.return_date,
      reason: doc.reason,
      quarantine_location: str(doc.quarantine_location),
      note: doc.note,
    },
    lines: doc.lines.map((line) => ({
      key: `l${line.id}`,
      id: line.id,
      product: str(line.product),
      lot: str(line.lot),
      quantity: trimDecimal(line.quantity),
      unit: str(line.unit),
    })),
  };
}

function toPayload(header: HeaderDraft, lines: LineDraft[]): ReturnPayload {
  return {
    customer: idOrNull(header.customer),
    shipment: idOrNull(header.shipment),
    return_date: header.return_date,
    reason: header.reason.trim(),
    quarantine_location: idOrNull(header.quarantine_location),
    note: header.note.trim(),
    lines: lines
      .filter((line) => line.product || line.lot || line.quantity.trim())
      .map((line) => ({
        ...(line.id ? { id: line.id } : {}),
        product: idOrNull(line.product)!,
        lot: idOrNull(line.lot)!,
        quantity: normalizeDecimal(line.quantity),
        unit: idOrNull(line.unit)!,
      })),
  };
}

/** İadeye girebilen mamul ürünler, temel birimleriyle. */
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

/** Müşterinin sevk edilmiş sevkiyatları (iade bağlantısı için, en yeni önce). */
function useCustomerShipments(customer: string | null) {
  return useQuery({
    queryKey: ["options", "dispatched-shipments", customer],
    enabled: Boolean(customer),
    staleTime: 30_000,
    queryFn: async () => {
      const page = await listShipments({ customer: customer!, page_size: 100 }, ["DISPATCHED"]);
      return page.results.map((row) => ({
        value: String(row.id),
        label: `${row.number} · ${row.order_number} · ${formatDate(row.planned_date)}`,
      }));
    },
  });
}

/** Ürünün lotları (en yeni önce). */
function useProductLots(product: string | null) {
  return useQuery({
    queryKey: ["options", "product-lots", product],
    enabled: Boolean(product),
    staleTime: 30_000,
    queryFn: async () => {
      const page = await listLots({ material: product!, page_size: 200 });
      return page.results.map((lot) => ({
        value: String(lot.id),
        label: lot.expiry_date ? `${lot.lot_no} (SKT ${formatDate(lot.expiry_date)})` : lot.lot_no,
      }));
    },
  });
}

export function DispositionBadge({ value }: { value: ReturnDisposition }) {
  return (
    <Badge color={DISPOSITION_COLOR[value]} variant="light">
      {rt.dispositionLabel[value]}
    </Badge>
  );
}

/** Müşteri iadesi: taslak düzenlenir; teslim alınınca karantinaya girer ve QC kararını bekler. */
export function ReturnPage() {
  const param = useParams().returnId;
  const isNew = param === "yeni";
  const returnId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["returns", "detail", returnId],
    queryFn: () => getReturn(returnId!),
    enabled: returnId !== null,
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
        <ReturnForm key={doc ? `${doc.id}-${doc.status}` : "new"} doc={doc} />
      </Grid.Col>
      {doc && (
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <RecordPanel contentType="returns.customerreturn" objectId={doc.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

function LineEditor({
  line,
  index,
  products,
  units,
  onChange,
  onRemove,
}: {
  line: LineDraft;
  index: number;
  products: Material[];
  units: { value: string; label: string }[];
  onChange: (patch: Partial<LineDraft>) => void;
  onRemove: () => void;
}) {
  const lots = useProductLots(line.product);
  return (
    <Paper withBorder p="sm" radius="md" data-testid="return-line">
      <Group justify="space-between" mb={4}>
        <Text size="sm" fw={600}>
          {index + 1}
        </Text>
        <ActionIcon variant="subtle" color="red" aria-label={rt.removeLine} onClick={onRemove}>
          <IconTrash size={16} />
        </ActionIcon>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Select
          label={rt.product}
          withAsterisk
          searchable
          data={products.map((row) => ({
            value: String(row.id),
            label: `${row.code} - ${row.name}`,
          }))}
          value={line.product}
          nothingFoundMessage={rt.notFound}
          onChange={(value) => {
            const picked = products.find((row) => String(row.id) === value);
            onChange({
              product: value,
              lot: null,
              unit: line.unit ?? (picked ? String(picked.base_unit) : null),
            });
          }}
        />
        <Select
          label={rt.lot}
          description={line.product ? undefined : rt.lotHint}
          withAsterisk
          searchable
          disabled={!line.product}
          data={lots.data ?? []}
          value={line.lot}
          nothingFoundMessage={rt.notFound}
          onChange={(value) => onChange({ lot: value })}
        />
        <Group gap="xs" grow wrap="nowrap">
          <TextInput
            label={rt.quantity}
            withAsterisk
            inputMode="decimal"
            value={line.quantity}
            onChange={(event) => onChange({ quantity: event.currentTarget.value })}
          />
          <Select
            label={rt.unit}
            withAsterisk
            searchable
            data={units}
            value={line.unit}
            onChange={(value) => onChange({ unit: value })}
          />
        </Group>
      </SimpleGrid>
    </Paper>
  );
}

function ReturnForm({ doc }: { doc: CustomerReturnDetail | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editable = hasAnyRole(user, RETURN_EDIT_ROLES) && (!doc || doc.status === "DRAFT");
  const canReceive = hasAnyRole(user, RETURN_RECEIVE_ROLES) && doc?.status === "DRAFT";
  const canCancel = hasAnyRole(user, RETURN_EDIT_ROLES) && doc?.status === "DRAFT";
  const canScrap = hasAnyRole(user, RETURN_SCRAP_ROLES) && doc?.status === "RECEIVED";
  const canOpenShipment = hasAnyRole(user, SHIPMENT_VIEW_ROLES);
  const [{ header, lines }, setDraft] = useState(() => toDraft(doc));
  const [error, setError] = useState("");
  const [confirmReceive, setConfirmReceive] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [scrapLine, setScrapLine] = useState<ReturnLine | null>(null);
  const customers = useOptions({ endpoint: "customers" });
  const units = useOptions({ endpoint: "units" });
  const shipments = useCustomerShipments(header.customer);
  const products = useFinishedProducts();
  const locations = useLocations();
  const quarantineOptions = (locations.data ?? []).filter((row) => row.type === "QUARANTINE");

  useEffect(() => setDraft(toDraft(doc)), [doc]);

  const setHeader = (patch: Partial<HeaderDraft>) =>
    setDraft((current) => ({ ...current, header: { ...current.header, ...patch } }));
  const setLine = (key: string, patch: Partial<LineDraft>) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));

  const refresh = (saved: CustomerReturnDetail) => {
    queryClient.setQueryData(["returns", "detail", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["returns"] });
  };

  const save = useMutation({
    mutationFn: () => saveReturn(doc?.id ?? null, toPayload(header, lines)),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: rt.saved });
      refresh(saved);
      if (!doc) navigate(returnPath(saved.id), { replace: true });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const receive = useMutation({
    mutationFn: async () => {
      if (editable) await saveReturn(doc!.id, toPayload(header, lines));
      return receiveReturn(doc!.id);
    },
    onSuccess: (saved) => {
      setError("");
      setConfirmReceive(false);
      notifications.show({ color: "green", message: rt.received });
      refresh(saved);
    },
    onError: (err) => {
      setConfirmReceive(false);
      setError(getErrorMessage(err));
    },
  });

  return (
    <Stack>
      <Anchor component={Link} to={RETURNS_BASE} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {rt.title}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{doc ? rt.returnTitle(doc.number) : rt.newReturn}</Title>
          {doc && <ReturnStatusBadge status={doc.status} />}
        </Group>
        <Group gap="xs">
          {editable && (
            <Button variant="default" loading={save.isPending} onClick={() => save.mutate()}>
              {rt.saveDraft}
            </Button>
          )}
          {canReceive && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setConfirmReceive(true)}
            >
              {rt.receive}
            </Button>
          )}
          {canCancel && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {rt.cancelDoc}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      {(!doc || doc.status === "DRAFT") && (
        <Alert color="blue" variant="light">
          {rt.holdInfo}
        </Alert>
      )}

      {editable ? (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
            <Select
              label={rt.customer}
              withAsterisk
              searchable
              data={customers.data ?? []}
              value={header.customer}
              onChange={(value) =>
                setHeader({
                  customer: value,
                  shipment: value === header.customer ? header.shipment : null,
                })
              }
              nothingFoundMessage={rt.notFound}
            />
            <Select
              label={rt.shipment}
              description={rt.shipmentHint}
              searchable
              clearable
              disabled={!header.customer}
              data={shipments.data ?? []}
              value={header.shipment}
              onChange={(value) => setHeader({ shipment: value })}
              nothingFoundMessage={rt.notFound}
            />
            <TextInput
              label={rt.returnDate}
              type="date"
              withAsterisk
              value={header.return_date}
              onChange={(event) => setHeader({ return_date: event.currentTarget.value })}
            />
            <Select
              label={rt.quarantineLocation}
              description={rt.quarantineHint}
              withAsterisk
              data={quarantineOptions}
              value={header.quarantine_location}
              onChange={(value) => setHeader({ quarantine_location: value })}
            />
            <Textarea
              label={rt.reason}
              withAsterisk
              autosize
              minRows={1}
              value={header.reason}
              onChange={(event) => setHeader({ reason: event.currentTarget.value })}
            />
            <Textarea
              label={rt.note}
              autosize
              minRows={1}
              value={header.note}
              onChange={(event) => setHeader({ note: event.currentTarget.value })}
            />
          </SimpleGrid>
        </Paper>
      ) : (
        doc && (
          <Paper withBorder p="md" radius="md">
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
              <Info label={rt.customer}>
                <Text size="sm">{`${doc.customer_code} - ${doc.customer_name}`}</Text>
              </Info>
              {doc.shipment && (
                <Info label={rt.shipment}>
                  {canOpenShipment ? (
                    <Anchor component={Link} to={shipmentPath(doc.shipment)} size="sm">
                      {doc.shipment_number}
                    </Anchor>
                  ) : (
                    <Text size="sm">{doc.shipment_number}</Text>
                  )}
                </Info>
              )}
              <Info label={rt.returnDate}>
                <Text size="sm">{formatDate(doc.return_date)}</Text>
              </Info>
              <Info label={rt.quarantineLocation}>
                <Text size="sm">{doc.quarantine_location_code}</Text>
              </Info>
              <Info label={rt.reason}>
                <Text size="sm">{doc.reason}</Text>
              </Info>
              {doc.received_at && (
                <Info label={rt.receivedBy}>
                  <Text size="sm">{`${doc.received_by_name ?? ""} · ${formatDateTime(doc.received_at)}`}</Text>
                </Info>
              )}
              {doc.closed_at && (
                <Info label={rt.closedAt}>
                  <Text size="sm">{formatDateTime(doc.closed_at)}</Text>
                </Info>
              )}
              {doc.status === "CANCELLED" && (
                <Info label={rt.cancelReason}>
                  <Text size="sm">{doc.cancel_reason}</Text>
                </Info>
              )}
              <Info label={rt.note}>
                <Text size="sm">{doc.note}</Text>
              </Info>
            </SimpleGrid>
          </Paper>
        )
      )}

      <Group justify="space-between">
        <Title order={4}>{rt.lines}</Title>
        {editable && (
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() =>
              setDraft((current) => ({ ...current, lines: [...current.lines, emptyLine()] }))
            }
          >
            {rt.addLine}
          </Button>
        )}
      </Group>

      {editable ? (
        <Stack gap="sm">
          {lines.map((line, index) => (
            <LineEditor
              key={line.key}
              line={line}
              index={index}
              products={products.data ?? []}
              units={units.data ?? []}
              onChange={(patch) => setLine(line.key, patch)}
              onRemove={() =>
                setDraft((current) => ({
                  ...current,
                  lines: current.lines.filter((row) => row.key !== line.key),
                }))
              }
            />
          ))}
          {lines.length === 0 && (
            <Text size="sm" c="dimmed">
              {ct.empty}
            </Text>
          )}
        </Stack>
      ) : (
        doc && (
          <Table.ScrollContainer minWidth={760}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{rt.product}</Table.Th>
                  <Table.Th>{rt.lot}</Table.Th>
                  <Table.Th ta="right">{rt.quantity}</Table.Th>
                  <Table.Th>{rt.sample}</Table.Th>
                  <Table.Th>{rt.disposition}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {doc.lines.map((line) => (
                  <Table.Tr key={line.id}>
                    <Table.Td>{line.line_no}</Table.Td>
                    <Table.Td>{`${line.product_code} - ${line.product_name}`}</Table.Td>
                    <Table.Td>
                      <Group gap="xs" wrap="nowrap">
                        <Anchor component={Link} to={lotPath(line.lot)} size="sm">
                          {line.lot_no}
                        </Anchor>
                        {line.lot_status && <LotStatusBadge status={line.lot_status} />}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={line.quantity} unit={line.unit_code} />
                    </Table.Td>
                    <Table.Td>
                      {line.sample && (
                        <Anchor component={Link} to={samplePath(line.sample)} size="sm">
                          {line.sample_number}
                        </Anchor>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {doc.status !== "DRAFT" && doc.status !== "CANCELLED" && line.disposition && (
                        <DispositionBadge value={line.disposition} />
                      )}
                    </Table.Td>
                    <Table.Td>
                      {line.disposition === "SCRAP" &&
                        (line.is_scrapped ? (
                          <Text size="xs" c="dimmed">
                            {rt.scrapDone}
                          </Text>
                        ) : (
                          canScrap && (
                            <Button
                              size="xs"
                              color="red"
                              variant="light"
                              leftSection={<IconFlame size={14} />}
                              onClick={() => setScrapLine(line)}
                            >
                              {rt.scrap}
                            </Button>
                          )
                        ))}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )
      )}

      <ConfirmModal
        opened={confirmReceive}
        message={rt.receiveConfirm}
        confirmLabel={rt.receive}
        loading={receive.isPending}
        onConfirm={() => receive.mutate()}
        onClose={() => setConfirmReceive(false)}
      />
      {doc && (
        <CancelModal
          opened={cancelOpen}
          cancel={(reason) => cancelReturn(doc.id, reason)}
          onClose={() => setCancelOpen(false)}
          onDone={(saved) => {
            setCancelOpen(false);
            refresh(saved);
          }}
        />
      )}
      {doc && scrapLine && (
        <ScrapModal
          doc={doc}
          line={scrapLine}
          onClose={() => setScrapLine(null)}
          onDone={(saved) => {
            setScrapLine(null);
            refresh(saved);
          }}
        />
      )}
    </Stack>
  );
}

function ScrapModal({
  doc,
  line,
  onClose,
  onDone,
}: {
  doc: CustomerReturnDetail;
  line: ReturnLine;
  onClose: () => void;
  onDone: (saved: CustomerReturnDetail) => void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => scrapReturnLine(doc.id, line.id!, note.trim()),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: rt.scrapped });
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={rt.scrapTitle}>
      <Stack>
        <Text size="sm">
          {`${line.lot_no} · `}
          <Qty value={line.base_quantity ?? line.quantity} unit={line.base_unit_code} />
        </Text>
        <Text size="sm" c="dimmed">
          {rt.scrapHint}
        </Text>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Textarea
          label={rt.note}
          autosize
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button color="red" loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {rt.scrap}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
