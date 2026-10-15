import {
  ActionIcon,
  Alert,
  Anchor,
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
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconCheck, IconPlus, IconTrash, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelAdjustment,
  getAdjustment,
  listLots,
  postAdjustment,
  saveAdjustment,
  type AdjustmentPayload,
  type StockAdjustmentDetail,
} from "../../api/inventory";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { CancelModal } from "./CancelModal";
import { adjustmentPath, INVENTORY_BASE, lotPath, STOCK_WRITE_ROLES, today } from "./config";
import { idOrNull, useLocations } from "./options";
import { DocStatusBadge, Info } from "./shared";
import { it } from "./strings";

interface LineDraft {
  key: string;
  id?: number;
  lot: string | null;
  lotLabel: string;
  location: string | null;
  counted_quantity: string;
  reason: string;
  system_quantity?: string;
  difference?: string;
  unit?: string;
}

let lineSeq = 0;
const newKey = () => `n${++lineSeq}`;

const emptyLine = (): LineDraft => ({
  key: newKey(),
  lot: null,
  lotLabel: "",
  location: null,
  counted_quantity: "",
  reason: "",
});

function toDraft(doc: StockAdjustmentDetail | null) {
  if (!doc) return { date: today(), note: "", lines: [emptyLine()] };
  return {
    date: doc.adjustment_date,
    note: doc.note,
    lines: doc.lines.map((line): LineDraft => ({
      key: `l${line.id}`,
      id: line.id,
      lot: String(line.lot),
      lotLabel: `${line.lot_no} · ${line.material_code} - ${line.material_name}`,
      location: String(line.location),
      counted_quantity: trimDecimal(line.counted_quantity),
      reason: line.reason,
      system_quantity: line.system_quantity,
      difference: line.difference,
      unit: line.unit,
    })),
  };
}

function toPayload(date: string, note: string, lines: LineDraft[]): AdjustmentPayload {
  return {
    adjustment_date: date,
    note: note.trim(),
    lines: lines
      .filter((line) => line.lot || line.counted_quantity.trim())
      .map((line) => ({
        ...(line.id ? { id: line.id } : {}),
        lot: idOrNull(line.lot)!,
        location: idOrNull(line.location)!,
        counted_quantity: normalizeDecimal(line.counted_quantity),
        reason: line.reason.trim(),
      })),
  };
}

/** Sayım düzeltme: lot + lokasyon için sayılan miktar; kaydedilince fark stoka yazılır. */
export function AdjustmentPage() {
  const param = useParams().adjustmentId;
  const isNew = param === "yeni";
  const adjustmentId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["inventory", "adjustment", adjustmentId],
    queryFn: () => getAdjustment(adjustmentId!),
    enabled: adjustmentId !== null,
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
        <AdjustmentForm key={doc ? `${doc.id}-${doc.status}` : "new"} doc={doc} />
      </Grid.Col>
      {doc && (
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <RecordPanel contentType="inventory.stockadjustment" objectId={doc.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

/** Lot arama kutusu: lot no ya da malzeme yazılır (barkod okuyucu da yazar). */
function LotSelect({
  value,
  label,
  onChange,
}: {
  value: string | null;
  label: string;
  onChange: (value: string | null, label: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const lots = useQuery({
    queryKey: ["inventory", "lot-search", debounced],
    queryFn: () => listLots({ search: debounced, page_size: 20 }),
    enabled: debounced.trim().length >= 2,
  });
  const options = (lots.data?.results ?? []).map((lot) => ({
    value: String(lot.id),
    label: `${lot.lot_no} · ${lot.material_code} - ${lot.material_name}`,
  }));
  if (value && !options.some((option) => option.value === value)) {
    options.unshift({ value, label });
  }
  return (
    <Select
      label={it.lot}
      placeholder={it.lotSearch}
      withAsterisk
      searchable
      filter={({ options: all }) => all}
      data={options}
      value={value}
      searchValue={search}
      onSearchChange={setSearch}
      nothingFoundMessage={debounced.trim().length >= 2 ? it.notFound : undefined}
      onChange={(next) => {
        const option = options.find((item) => item.value === next);
        onChange(next, option?.label ?? "");
      }}
    />
  );
}

function AdjustmentForm({ doc }: { doc: StockAdjustmentDetail | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const editable = hasAnyRole(user, STOCK_WRITE_ROLES) && (!doc || doc.status === "DRAFT");
  const [{ date, note, lines }, setDraft] = useState(() => toDraft(doc));
  const [error, setError] = useState("");
  const [confirmPost, setConfirmPost] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const locations = useLocations();

  useEffect(() => setDraft(toDraft(doc)), [doc]);

  const setLine = (key: string, patch: Partial<LineDraft>) =>
    setDraft((current) => ({
      ...current,
      lines: current.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    }));

  const refresh = (saved: StockAdjustmentDetail) => {
    queryClient.setQueryData(["inventory", "adjustment", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["inventory"] });
  };

  const save = useMutation({
    mutationFn: () => saveAdjustment(doc?.id ?? null, toPayload(date, note, lines)),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: it.saved });
      refresh(saved);
      if (!doc) navigate(adjustmentPath(saved.id), { replace: true });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const post = useMutation({
    mutationFn: async () => {
      const saved = await saveAdjustment(doc!.id, toPayload(date, note, lines));
      return postAdjustment(saved.id);
    },
    onSuccess: (saved) => {
      setError("");
      setConfirmPost(false);
      notifications.show({ color: "green", message: it.adjustmentPosted });
      refresh(saved);
    },
    onError: (err) => {
      setConfirmPost(false);
      setError(getErrorMessage(err));
    },
  });

  return (
    <Stack>
      <Anchor component={Link} to={`${INVENTORY_BASE}/sayim`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {it.tabs.adjustments}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{doc ? it.adjustmentTitle(doc.number) : it.adjustmentNew}</Title>
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
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        {editable ? (
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={it.adjustmentDate}
              type="date"
              withAsterisk
              value={date}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setDraft((current) => ({ ...current, date: value }));
              }}
            />
            <Textarea
              label={it.note}
              autosize
              minRows={1}
              value={note}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setDraft((current) => ({ ...current, note: value }));
              }}
            />
          </SimpleGrid>
        ) : (
          doc && (
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
              <Info label={it.adjustmentDate}>
                <Text size="sm">{formatDate(doc.adjustment_date)}</Text>
              </Info>
              <Info label={it.note}>
                <Text size="sm">{doc.note}</Text>
              </Info>
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
          )
        )}
      </Paper>

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
      {editable && (
        <Text size="xs" c="dimmed">
          {it.systemQtyHint}
        </Text>
      )}

      {editable ? (
        <Stack gap="sm">
          {lines.map((line, index) => (
            <Paper key={line.key} withBorder p="sm" radius="md" data-testid="adjustment-line">
              <Group justify="space-between" mb={4}>
                <Text size="sm" fw={600}>
                  {index + 1}
                </Text>
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
              <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
                <LotSelect
                  value={line.lot}
                  label={line.lotLabel}
                  onChange={(lot, lotLabel) => setLine(line.key, { lot, lotLabel })}
                />
                <Select
                  label={it.location}
                  withAsterisk
                  searchable
                  data={locations.data ?? []}
                  value={line.location}
                  onChange={(value) => setLine(line.key, { location: value })}
                  nothingFoundMessage={it.notFound}
                />
                <TextInput
                  label={it.countedQty}
                  withAsterisk
                  inputMode="decimal"
                  description={
                    line.system_quantity !== undefined
                      ? `${it.systemQty}: ${formatNumber(line.system_quantity)} ${line.unit ?? ""}`
                      : undefined
                  }
                  value={line.counted_quantity}
                  onChange={(event) =>
                    setLine(line.key, { counted_quantity: event.currentTarget.value })
                  }
                />
                <TextInput
                  label={it.reason}
                  withAsterisk
                  value={line.reason}
                  onChange={(event) => setLine(line.key, { reason: event.currentTarget.value })}
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
          <Table.ScrollContainer minWidth={720}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{it.lot}</Table.Th>
                  <Table.Th>{it.location}</Table.Th>
                  <Table.Th ta="right">{it.systemQty}</Table.Th>
                  <Table.Th ta="right">{it.countedQty}</Table.Th>
                  <Table.Th ta="right">{it.difference}</Table.Th>
                  <Table.Th>{it.reason}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {doc.lines.map((line) => {
                  const diff = Number(line.difference ?? 0);
                  return (
                    <Table.Tr key={line.id}>
                      <Table.Td>{line.line_no}</Table.Td>
                      <Table.Td>
                        <Anchor component={Link} to={lotPath(line.lot)} size="sm">
                          {line.lot_no}
                        </Anchor>
                        <Text size="xs" c="dimmed">
                          {`${line.material_code} - ${line.material_name}`}
                        </Text>
                      </Table.Td>
                      <Table.Td>{line.location_code}</Table.Td>
                      <Table.Td ta="right">{`${formatNumber(line.system_quantity)} ${line.unit}`}</Table.Td>
                      <Table.Td ta="right">{`${formatNumber(line.counted_quantity)} ${line.unit}`}</Table.Td>
                      <Table.Td ta="right" c={diff < 0 ? "red" : diff > 0 ? "green" : undefined}>
                        {`${diff > 0 ? "+" : ""}${formatNumber(line.difference)} ${line.unit}`}
                      </Table.Td>
                      <Table.Td>{line.reason}</Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )
      )}

      <ConfirmModal
        opened={confirmPost}
        message={it.adjustmentPostConfirm}
        confirmLabel={it.post}
        loading={post.isPending}
        onConfirm={() => post.mutate()}
        onClose={() => setConfirmPost(false)}
      />
      {doc && (
        <CancelModal
          opened={cancelOpen}
          cancel={(reason) => cancelAdjustment(doc.id, reason)}
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
