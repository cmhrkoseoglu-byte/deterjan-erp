import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
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
  IconPlus,
  IconPrinter,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelGoodsReceipt,
  getGoodsReceipt,
  postGoodsReceipt,
  receiptLabelsUrl,
  saveGoodsReceipt,
  type GoodsReceiptDetail,
  type GoodsReceiptPayload,
} from "../../api/inventory";
import { listRecords, type Material } from "../../api/masterdata";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { CancelModal } from "./CancelModal";
import { INVENTORY_BASE, lotPath, receiptPath, STOCK_WRITE_ROLES, today } from "./config";
import { idOrNull, useLocations } from "./options";
import { DocStatusBadge, Info, LotStatusBadge, Qty } from "./shared";
import { it } from "./strings";

interface LineDraft {
  key: string;
  id?: number;
  material: string | null;
  quantity: string;
  unit: string | null;
  supplier_lot_no: string;
  manufactured_at: string;
  expiry_date: string;
  unit_price: string;
}

interface HeaderDraft {
  supplier: string | null;
  receipt_date: string;
  delivery_note_no: string;
  quarantine_location: string | null;
  storage_location: string | null;
  note: string;
}

let lineSeq = 0;
const newKey = () => `n${++lineSeq}`;

function emptyLine(): LineDraft {
  return {
    key: newKey(),
    material: null,
    quantity: "",
    unit: null,
    supplier_lot_no: "",
    manufactured_at: "",
    expiry_date: "",
    unit_price: "",
  };
}

const str = (value: number | null | undefined) => (value ? String(value) : null);

function toDraft(doc: GoodsReceiptDetail | null): { header: HeaderDraft; lines: LineDraft[] } {
  if (!doc) {
    return {
      header: {
        supplier: null,
        receipt_date: today(),
        delivery_note_no: "",
        quarantine_location: null,
        storage_location: null,
        note: "",
      },
      lines: [emptyLine()],
    };
  }
  return {
    header: {
      supplier: str(doc.supplier),
      receipt_date: doc.receipt_date,
      delivery_note_no: doc.delivery_note_no,
      quarantine_location: str(doc.quarantine_location),
      storage_location: str(doc.storage_location),
      note: doc.note,
    },
    lines: doc.lines.map((line) => ({
      key: `l${line.id}`,
      id: line.id,
      material: str(line.material),
      quantity: trimDecimal(line.quantity),
      unit: str(line.unit),
      supplier_lot_no: line.supplier_lot_no,
      manufactured_at: line.manufactured_at ?? "",
      expiry_date: line.expiry_date ?? "",
      unit_price: line.unit_price ? trimDecimal(line.unit_price) : "",
    })),
  };
}

function toPayload(header: HeaderDraft, lines: LineDraft[]): GoodsReceiptPayload {
  return {
    supplier: idOrNull(header.supplier),
    receipt_date: header.receipt_date,
    delivery_note_no: header.delivery_note_no.trim(),
    quarantine_location: idOrNull(header.quarantine_location),
    storage_location: idOrNull(header.storage_location),
    note: header.note.trim(),
    lines: lines
      .filter((line) => line.material || line.quantity.trim())
      .map((line) => ({
        ...(line.id ? { id: line.id } : {}),
        material: idOrNull(line.material)!,
        quantity: normalizeDecimal(line.quantity),
        unit: idOrNull(line.unit)!,
        supplier_lot_no: line.supplier_lot_no.trim(),
        manufactured_at: line.manufactured_at || null,
        expiry_date: line.expiry_date || null,
        unit_price: line.unit_price.trim() ? normalizeDecimal(line.unit_price) : null,
      })),
  };
}

/** Mal kabule girebilen malzemeler (hammadde ve ambalaj), temel birimleriyle. */
function useReceivableMaterials() {
  return useQuery({
    queryKey: ["options", "receivable-materials"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Material>("materials", {
        is_active: true,
        material_type__in: "RAW,PACKAGING",
        page_size: 500,
      });
      return page.results;
    },
  });
}

/** Mal kabul: taslak (başlık + satırlar) düzenlenir; kaydedilince lotlar açılır ve stoka girer. */
export function GoodsReceiptPage() {
  const param = useParams().receiptId;
  const isNew = param === "yeni";
  const receiptId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["inventory", "receipt", receiptId],
    queryFn: () => getGoodsReceipt(receiptId!),
    enabled: receiptId !== null,
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
        <ReceiptForm key={doc ? `${doc.id}-${doc.status}` : "new"} doc={doc} />
      </Grid.Col>
      {doc && (
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <RecordPanel contentType="inventory.goodsreceipt" objectId={doc.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

function ReceiptForm({ doc }: { doc: GoodsReceiptDetail | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editable = hasAnyRole(user, STOCK_WRITE_ROLES) && (!doc || doc.status === "DRAFT");
  const [{ header, lines }, setDraft] = useState(() => toDraft(doc));
  const [error, setError] = useState("");
  const [confirmPost, setConfirmPost] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const suppliers = useOptions({ endpoint: "suppliers" });
  const units = useOptions({ endpoint: "units" });
  const materials = useReceivableMaterials();
  const locations = useLocations();

  useEffect(() => setDraft(toDraft(doc)), [doc]);

  const materialById = new Map((materials.data ?? []).map((row) => [String(row.id), row]));
  const materialOptions = (materials.data ?? []).map((row) => ({
    value: String(row.id),
    label: `${row.code} - ${row.name}`,
  }));
  const quarantineOptions = (locations.data ?? []).filter((row) => row.type === "QUARANTINE");
  const storageOptions = (locations.data ?? []).filter((row) => row.type !== "QUARANTINE");

  const setHeader = (patch: Partial<HeaderDraft>) =>
    setDraft((current) => ({ ...current, header: { ...current.header, ...patch } }));
  const setLine = (key: string, patch: Partial<LineDraft>) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));

  const refresh = (saved: GoodsReceiptDetail) => {
    queryClient.setQueryData(["inventory", "receipt", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["inventory"] });
  };

  const save = useMutation({
    mutationFn: () => saveGoodsReceipt(doc?.id ?? null, toPayload(header, lines)),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: it.saved });
      refresh(saved);
      if (!doc) navigate(receiptPath(saved.id), { replace: true });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const post = useMutation({
    mutationFn: async () => {
      const saved = await saveGoodsReceipt(doc!.id, toPayload(header, lines));
      return postGoodsReceipt(saved.id);
    },
    onSuccess: (saved) => {
      setError("");
      setConfirmPost(false);
      notifications.show({ color: "green", message: it.posted });
      refresh(saved);
    },
    onError: (err) => {
      setConfirmPost(false);
      setError(getErrorMessage(err));
    },
  });

  const title = doc ? it.receiptTitle(doc.number) : it.receiptNew;

  return (
    <Stack>
      <Anchor component={Link} to={`${INVENTORY_BASE}/mal-kabul`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {it.tabs.receipts}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{title}</Title>
          {doc && <DocStatusBadge status={doc.status} />}
        </Group>
        <Group gap="xs">
          {editable && (
            <Button variant="default" loading={save.isPending} onClick={() => save.mutate()}>
              {it.saveDraft}
            </Button>
          )}
          {editable && doc && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setConfirmPost(true)}
            >
              {it.post}
            </Button>
          )}
          {editable && doc && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {it.cancelDoc}
            </Button>
          )}
          {doc?.status === "POSTED" && (
            <Button
              component="a"
              href={receiptLabelsUrl(doc.id)}
              target="_blank"
              variant="default"
              leftSection={<IconPrinter size={16} />}
            >
              {it.labels}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      {doc && doc.status !== "DRAFT" && (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            {doc.posted_at && (
              <Info label={it.postedBy}>
                <Text size="sm">{`${doc.posted_by_name ?? ""} · ${formatDateTime(doc.posted_at)}`}</Text>
              </Info>
            )}
            {doc.status === "CANCELLED" && (
              <Info label={it.cancelReason}>
                <Text size="sm">{doc.cancel_reason}</Text>
              </Info>
            )}
          </SimpleGrid>
        </Paper>
      )}

      {editable ? (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
            <Select
              label={it.supplier}
              withAsterisk
              searchable
              data={suppliers.data ?? []}
              value={header.supplier}
              onChange={(value) => setHeader({ supplier: value })}
              nothingFoundMessage={it.notFound}
            />
            <TextInput
              label={it.receiptDate}
              type="date"
              withAsterisk
              value={header.receipt_date}
              onChange={(event) => setHeader({ receipt_date: event.currentTarget.value })}
            />
            <TextInput
              label={it.deliveryNote}
              value={header.delivery_note_no}
              onChange={(event) => setHeader({ delivery_note_no: event.currentTarget.value })}
            />
            <Select
              label={it.quarantineLocation}
              description={it.quarantineHint}
              clearable
              data={quarantineOptions}
              value={header.quarantine_location}
              onChange={(value) => setHeader({ quarantine_location: value })}
            />
            <Select
              label={it.storageLocation}
              description={it.storageHint}
              clearable
              searchable
              data={storageOptions}
              value={header.storage_location}
              onChange={(value) => setHeader({ storage_location: value })}
              nothingFoundMessage={it.notFound}
            />
            <Textarea
              label={it.note}
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
              <Info label={it.supplier}>
                <Text size="sm">{`${doc.supplier_code} - ${doc.supplier_name}`}</Text>
              </Info>
              <Info label={it.receiptDate}>
                <Text size="sm">{formatDate(doc.receipt_date)}</Text>
              </Info>
              <Info label={it.deliveryNote}>
                <Text size="sm">{doc.delivery_note_no}</Text>
              </Info>
              <Info label={it.quarantineLocation}>
                <Text size="sm">{doc.quarantine_location_code}</Text>
              </Info>
              <Info label={it.storageLocation}>
                <Text size="sm">{doc.storage_location_code}</Text>
              </Info>
              <Info label={it.note}>
                <Text size="sm">{doc.note}</Text>
              </Info>
            </SimpleGrid>
          </Paper>
        )
      )}

      <Group justify="space-between">
        <Title order={4}>{it.lines}</Title>
        {editable && (
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() =>
              setDraft((current) => ({ ...current, lines: [...current.lines, emptyLine()] }))
            }
          >
            {it.addLine}
          </Button>
        )}
      </Group>

      {editable ? (
        <Stack gap="sm">
          {lines.map((line, index) => {
            const material = line.material ? materialById.get(line.material) : undefined;
            return (
              <Paper key={line.key} withBorder p="sm" radius="md" data-testid="receipt-line">
                <Group justify="space-between" mb={4}>
                  <Group gap="xs">
                    <Text size="sm" fw={600}>
                      {index + 1}
                    </Text>
                    {material?.requires_incoming_qc && (
                      <Badge size="xs" color="yellow" variant="light">
                        {it.qcRequired}
                      </Badge>
                    )}
                  </Group>
                  <ActionIcon
                    variant="subtle"
                    color="red"
                    aria-label={it.removeLine}
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
                    label={it.material}
                    withAsterisk
                    searchable
                    data={materialOptions}
                    value={line.material}
                    nothingFoundMessage={it.notFound}
                    onChange={(value) => {
                      const picked = value ? materialById.get(value) : undefined;
                      setLine(line.key, {
                        material: value,
                        unit: line.unit ?? (picked ? String(picked.base_unit) : null),
                      });
                    }}
                  />
                  <Group gap="xs" grow wrap="nowrap">
                    <TextInput
                      label={it.quantity}
                      withAsterisk
                      inputMode="decimal"
                      value={line.quantity}
                      onChange={(event) =>
                        setLine(line.key, { quantity: event.currentTarget.value })
                      }
                    />
                    <Select
                      label={it.unit}
                      withAsterisk
                      searchable
                      data={units.data ?? []}
                      value={line.unit}
                      onChange={(value) => setLine(line.key, { unit: value })}
                    />
                  </Group>
                  <TextInput
                    label={it.supplierLotNo}
                    value={line.supplier_lot_no}
                    onChange={(event) =>
                      setLine(line.key, { supplier_lot_no: event.currentTarget.value })
                    }
                  />
                  <TextInput
                    label={it.unitPrice}
                    inputMode="decimal"
                    value={line.unit_price}
                    onChange={(event) =>
                      setLine(line.key, { unit_price: event.currentTarget.value })
                    }
                  />
                  <TextInput
                    label={it.manufactured}
                    type="date"
                    value={line.manufactured_at}
                    onChange={(event) =>
                      setLine(line.key, { manufactured_at: event.currentTarget.value })
                    }
                  />
                  <TextInput
                    label={it.expiry}
                    description={material?.shelf_life_days ? it.expiryHint : undefined}
                    type="date"
                    value={line.expiry_date}
                    onChange={(event) =>
                      setLine(line.key, { expiry_date: event.currentTarget.value })
                    }
                  />
                </SimpleGrid>
              </Paper>
            );
          })}
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
                  <Table.Th>{it.material}</Table.Th>
                  <Table.Th ta="right">{it.quantity}</Table.Th>
                  <Table.Th>{it.supplierLotNo}</Table.Th>
                  <Table.Th>{it.expiry}</Table.Th>
                  <Table.Th>{it.createdLot}</Table.Th>
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
                    <Table.Td>{line.supplier_lot_no}</Table.Td>
                    <Table.Td>{formatDate(line.expiry_date)}</Table.Td>
                    <Table.Td>
                      {line.created_lot && (
                        <Group gap="xs" wrap="nowrap">
                          <Anchor component={Link} to={lotPath(line.created_lot)} size="sm">
                            {line.created_lot_no}
                          </Anchor>
                          {line.created_lot_status && (
                            <LotStatusBadge status={line.created_lot_status} />
                          )}
                        </Group>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )
      )}

      <ConfirmModal
        opened={confirmPost}
        message={it.postConfirm}
        confirmLabel={it.post}
        loading={post.isPending}
        onConfirm={() => post.mutate()}
        onClose={() => setConfirmPost(false)}
      />
      {doc && (
        <CancelModal
          opened={cancelOpen}
          cancel={(reason) => cancelGoodsReceipt(doc.id, reason)}
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
