import {
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Modal,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconFlagCheck, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { HazardIcon } from "../../components/hazard/HazardIcon";
import { getErrorMessage } from "../../api/client";
import {
  cancelBatch,
  consume,
  finishBatch,
  getBatch,
  type BatchLine,
  type ProductionBatchDetail,
} from "../../api/production";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ct } from "../common/strings";
import { errorFeedback } from "../../components/scan/feedback";
import { ScanInput, type ScanInputHandle } from "../../components/scan/ScanInput";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { lotPath } from "../inventory/config";
import { ExpiryText, Info, Qty } from "../inventory/shared";
import { deviationPct, gaugeValue, lineState, remaining } from "./calc";
import { BATCH_ROLES, LINE_STATE_COLOR, orderPath } from "./config";
import { BatchStatusBadge, LineStateBadge, ReasonModal } from "./shared";
import { rememberedScale, ScaleSelect, useScales } from "./ScaleSelect";
import { pt } from "./strings";

/** Üretim tablet ekranı: reçete sırasıyla tartım, tolerans göstergesi, şarjı bitirme. */
export function BatchPage() {
  const batchId = Number(useParams().batchId);
  const query = useQuery({
    queryKey: ["production", "batch", batchId],
    queryFn: () => getBatch(batchId),
  });
  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <Batch batch={query.data} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <RecordPanel contentType="production.productionbatch" objectId={query.data.id} />
      </Grid.Col>
    </Grid>
  );
}

function Batch({ batch }: { batch: ProductionBatchDetail }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const open = batch.status === "IN_PROGRESS";
  const canWork = open && hasAnyRole(user, BATCH_ROLES);
  const firstOpen = batch.lines.find((line) => line.state === "pending" || line.state === "under");
  const [selected, setSelected] = useState<number | null>(firstOpen?.requirement ?? null);
  const [finishOpen, setFinishOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [scale, setScale] = useState<number | null>(rememberedScale);
  const current = batch.lines.find((line) => line.requirement === selected) ?? null;

  const refresh = (saved: ProductionBatchDetail) => {
    queryClient.setQueryData(["production", "batch", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["production"] });
  };

  return (
    <Stack>
      <Anchor component={Link} to={orderPath(batch.order)} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {pt.orderTitle(batch.order_number)}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{pt.batchTitle(batch.batch_no)}</Title>
          <BatchStatusBadge status={batch.status} />
        </Group>
        {canWork && (
          <Group gap="xs">
            <Button
              size="md"
              color="green"
              leftSection={<IconFlagCheck size={18} />}
              onClick={() => setFinishOpen(true)}
            >
              {pt.finish}
            </Button>
            {batch.consumptions.length === 0 && (
              <Button
                size="md"
                color="red"
                variant="light"
                leftSection={<IconX size={18} />}
                onClick={() => setCancelOpen(true)}
              >
                {pt.cancelBatch}
              </Button>
            )}
          </Group>
        )}
      </Group>

      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 2, md: 4 }}>
          <Info label={pt.product}>
            <Text size="sm">{`${batch.product_code} - ${batch.product_name}`}</Text>
          </Info>
          <Info label={pt.tank}>
            <Text size="sm">{batch.equipment_code}</Text>
          </Info>
          <Info label={pt.batchQuantity}>
            <Qty value={batch.planned_quantity} unit={batch.unit} />
          </Info>
          <Info label={pt.outputLot}>
            <Group gap={4}>
              <Anchor component={Link} to={lotPath(batch.output_lot)} size="sm">
                {batch.output_lot_no}
              </Anchor>
              <Text size="xs" c="dimmed">
                {batch.output_lot_status_display}
              </Text>
            </Group>
          </Info>
          <Info label={pt.startedBy}>
            <Text size="sm">{`${batch.started_by_name ?? ""} · ${formatDateTime(batch.started_at)}`}</Text>
          </Info>
          {batch.finished_at && (
            <>
              <Info label={pt.finishedBy}>
                <Text size="sm">{`${batch.finished_by_name ?? ""} · ${formatDateTime(batch.finished_at)}`}</Text>
              </Info>
              <Info label={pt.output}>
                <Qty value={batch.actual_output_quantity} unit={batch.unit} />
              </Info>
              <Info label={pt.yieldPct}>
                <Text size="sm">{batch.yield_pct ? `%${formatNumber(batch.yield_pct)}` : ""}</Text>
              </Info>
            </>
          )}
          {batch.finish_note && (
            <Info label={pt.finishNote}>
              <Text size="sm">{batch.finish_note}</Text>
            </Info>
          )}
          {batch.cancel_reason && (
            <Info label={pt.cancelReason}>
              <Text size="sm">{batch.cancel_reason}</Text>
            </Info>
          )}
        </SimpleGrid>
      </Paper>

      <Stack gap="xs" data-testid="batch-lines">
        {batch.lines.map((line) => (
          <LineRow
            key={line.requirement}
            line={line}
            active={canWork && line.requirement === selected}
            onSelect={() => setSelected(line.requirement)}
          />
        ))}
      </Stack>

      {canWork && current && (
        <WeighForm
          key={`${current.requirement}-${current.consumed_quantity}`}
          batch={batch}
          line={current}
          scale={scale}
          onScaleChange={setScale}
          onSaved={(saved) => {
            refresh(saved);
            const next = saved.lines.find(
              (line) =>
                line.requirement !== current.requirement &&
                (line.state === "pending" || line.state === "under"),
            );
            const same = saved.lines.find((line) => line.requirement === current.requirement);
            if (same?.state !== "under" && next) setSelected(next.requirement);
          }}
        />
      )}

      {batch.consumptions.length > 0 && (
        <>
          <Title order={4}>{pt.consumptions}</Title>
          <Table.ScrollContainer minWidth={640}>
            <Table striped fz="sm" data-testid="consumptions">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{pt.material}</Table.Th>
                  <Table.Th>{pt.lot}</Table.Th>
                  <Table.Th ta="right">{pt.weighed}</Table.Th>
                  <Table.Th ta="right">{pt.deviation}</Table.Th>
                  <Table.Th>{pt.deviationNote}</Table.Th>
                  <Table.Th>{pt.by}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {batch.consumptions.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.material_code}</Table.Td>
                    <Table.Td>
                      <Anchor component={Link} to={lotPath(row.lot)} size="sm">
                        {row.lot_no}
                      </Anchor>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.actual_quantity} unit={row.unit} />
                    </Table.Td>
                    <Table.Td ta="right">%{formatNumber(row.deviation_pct)}</Table.Td>
                    <Table.Td>{row.deviation_note}</Table.Td>
                    <Table.Td>{`${row.weighed_by_name ?? ""} · ${formatDateTime(row.weighed_at)}`}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}

      <FinishModal
        batch={batch}
        opened={finishOpen}
        onClose={() => setFinishOpen(false)}
        onDone={(saved) => {
          setFinishOpen(false);
          notifications.show({ color: "green", message: pt.finished });
          refresh(saved);
        }}
      />
      <ReasonModal
        opened={cancelOpen}
        title={pt.cancelBatchTitle}
        hint={pt.cancelBatchHint}
        label={pt.cancelReason}
        confirmLabel={pt.cancelBatch}
        submit={(reason) => cancelBatch(batch.id, reason)}
        onClose={() => setCancelOpen(false)}
        onDone={(saved) => {
          setCancelOpen(false);
          notifications.show({ color: "green", message: pt.cancelled });
          refresh(saved);
        }}
      />
    </Stack>
  );
}

/** Reçete satırı: plan, tartılan, tolerans göstergesi (yeşil/sarı/kırmızı). */
function LineRow({
  line,
  active,
  onSelect,
}: {
  line: BatchLine;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <UnstyledButton onClick={onSelect} aria-pressed={active}>
      <Paper
        withBorder
        p="sm"
        radius="md"
        style={{
          borderColor: active ? "var(--mantine-color-blue-6)" : undefined,
          borderWidth: active ? 2 : undefined,
        }}
      >
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Text fw={600}>{`${line.sequence}. ${line.material_code}`}</Text>
            {line.is_water && (
              <Badge size="xs" variant="light" color="cyan">
                {pt.water}
              </Badge>
            )}
          </Group>
          <LineStateBadge state={line.state} />
        </Group>
        <Group justify="space-between" mt={4} wrap="nowrap">
          <Text size="sm">
            {`${formatNumber(line.consumed_quantity)} / ${formatNumber(line.planned_quantity)} ${line.unit}`}
          </Text>
          <Text size="sm" c="dimmed">
            {`±%${formatNumber(line.tolerance_pct)}`}
            {line.state !== "pending" && ` · %${formatNumber(line.deviation_pct)}`}
          </Text>
        </Group>
        <Progress
          mt={6}
          size="lg"
          color={LINE_STATE_COLOR[line.state]}
          value={gaugeValue(line.planned_quantity, line.consumed_quantity)}
        />
      </Paper>
    </UnstyledButton>
  );
}

function WeighForm({
  batch,
  line,
  scale,
  onScaleChange,
  onSaved,
}: {
  batch: ProductionBatchDetail;
  line: BatchLine;
  scale: number | null;
  onScaleChange: (id: number | null) => void;
  onSaved: (batch: ProductionBatchDetail) => void;
}) {
  // Su (D-1) sayaçtan okunur; diğer satırlarda tanımlı terazi varsa seçim zorunludur.
  const scales = useScales();
  const needsScale = !line.is_water && (scales.data ?? []).length > 0;
  const scanRef = useRef<ScanInputHandle>(null);
  const quantityRef = useRef<HTMLInputElement>(null);
  const toWeigh = remaining(line.planned_quantity, line.consumed_quantity);
  const single = line.available.length === 1 ? line.available[0] : null;
  const [lotNo, setLotNo] = useState(single?.lot_no ?? "");
  const [lotId, setLotId] = useState<number | null>(single?.lot ?? null);
  const [quantity, setQuantity] = useState(toWeigh > 0 ? trimDecimal(String(toWeigh)) : "");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const total = Number(line.consumed_quantity) + Number(normalizeDecimal(quantity) || 0);
  const preview = lineState(line.planned_quantity, total, line.tolerance_pct);
  const previewPct = deviationPct(line.planned_quantity, total);
  const needsNote = preview === "over";

  const mutation = useMutation({
    mutationFn: () =>
      consume(batch.id, {
        requirement: line.requirement,
        ...(lotId ? { lot: lotId } : { lot_no: lotNo.trim() }),
        quantity: normalizeDecimal(quantity),
        note: note.trim(),
        ...(needsScale ? { scale } : {}),
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: pt.weighedOk(line.material_code) });
      onSaved(saved);
    },
    onError: (err) => {
      setError(getErrorMessage(err));
      errorFeedback();
      scanRef.current?.focus();
    },
  });
  const canSubmit =
    (!needsScale || scale !== null) &&
    (lotId !== null || lotNo.trim() !== "") &&
    quantity.trim() !== "" &&
    (!needsNote || note.trim() !== "");
  const submitOnEnter = (event: React.KeyboardEvent) => {
    if (event.key === "Enter" && canSubmit) mutation.mutate();
  };

  return (
    <Paper withBorder p="md" radius="md" data-testid="weigh-form">
      <Stack>
        <Group justify="space-between">
          <Group gap="xs">
            {line.is_hazardous && <HazardIcon size={22} />}
            <Title order={4}>{`${line.material_code} - ${line.material_name}`}</Title>
          </Group>
          <Text size="sm">
            {`${pt.planned}: `}
            <Qty value={line.planned_quantity} unit={line.unit} />
          </Text>
        </Group>
        {line.instruction && (
          <Alert color="blue" variant="light" title={pt.instruction}>
            {line.instruction}
          </Alert>
        )}
        {needsScale && <ScaleSelect value={scale} onChange={onScaleChange} />}
        <Group align="flex-start" grow>
          <ScanInput
            ref={scanRef}
            expect="lot"
            expectedMaterial={{ id: line.material, code: line.material_code }}
            label={pt.scan}
            placeholder={pt.scanPlaceholder}
            autoFocus
            onLot={(lot) => {
              setLotNo(lot.lot_no);
              setLotId(lot.id);
              setError("");
              quantityRef.current?.focus();
              quantityRef.current?.select();
            }}
          />
          <TextInput
            ref={quantityRef}
            size="lg"
            label={`${pt.actualQuantity} (${line.unit})`}
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.currentTarget.value)}
            onKeyDown={submitOnEnter}
          />
        </Group>
        {lotNo && (
          <Text size="sm">
            {`${pt.lotNo}: `}
            <Text span fw={700}>
              {lotNo}
            </Text>
          </Text>
        )}
        {quantity.trim() !== "" && (
          <Group gap="xs">
            <LineStateBadge state={preview} />
            <Text size="sm" c="dimmed">
              {`${pt.deviation}: %${formatNumber(previewPct)}`}
            </Text>
          </Group>
        )}
        {needsNote && (
          <Textarea
            label={pt.deviationNote}
            description={pt.deviationNoteRequired}
            withAsterisk
            autosize
            minRows={2}
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
          />
        )}
        {error && (
          <Alert color="red" variant="light" data-testid="weigh-error">
            {error}
          </Alert>
        )}
        <Text fw={600} size="sm">
          {pt.availableLots}
        </Text>
        {line.available.length === 0 ? (
          <Text size="sm" c="dimmed">
            {pt.noAvailable}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={360}>
            <Table fz="md" verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{pt.lotNo}</Table.Th>
                  <Table.Th>{pt.from}</Table.Th>
                  <Table.Th>SKT</Table.Th>
                  <Table.Th ta="right">{pt.quantity}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {line.available.map((row) => (
                  <Table.Tr
                    key={`${row.lot}-${row.location}`}
                    style={{ cursor: "pointer" }}
                    bg={lotId === row.lot ? "var(--mantine-color-blue-light)" : undefined}
                    onClick={() => {
                      setLotId(row.lot);
                      setLotNo(row.lot_no);
                    }}
                  >
                    <Table.Td>{row.lot_no}</Table.Td>
                    <Table.Td>{row.location_code}</Table.Td>
                    <Table.Td>
                      <ExpiryText date={row.expiry_date} />
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.quantity} unit={line.unit} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        <Group justify="flex-end">
          <Button
            size="lg"
            disabled={!canSubmit}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {pt.weigh}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function FinishModal({
  batch,
  opened,
  onClose,
  onDone,
}: {
  batch: ProductionBatchDetail;
  opened: boolean;
  onClose: () => void;
  onDone: (batch: ProductionBatchDetail) => void;
}) {
  const consumed = batch.consumptions.reduce((sum, row) => sum + Number(row.actual_quantity), 0);
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const short = batch.lines.some((line) => line.state === "under" || line.state === "pending");
  const mutation = useMutation({
    mutationFn: () =>
      finishBatch(batch.id, { output_quantity: normalizeDecimal(quantity), note: note.trim() }),
    onSuccess: (saved) => {
      setError("");
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened={opened} onClose={onClose} title={pt.finishTitle}>
      <Stack>
        <Text size="sm" c="dimmed">
          {`${pt.consumed}: ${formatNumber(consumed)} ${batch.unit}`}
        </Text>
        <TextInput
          label={`${pt.outputQuantity} (${batch.unit})`}
          withAsterisk
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.currentTarget.value)}
        />
        <Textarea
          label={pt.finishNote}
          description={pt.finishNoteHint}
          withAsterisk={short}
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
            color="green"
            disabled={!quantity.trim() || (short && !note.trim())}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {pt.finish}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
