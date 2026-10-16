import {
  Alert,
  Anchor,
  Button,
  Checkbox,
  Grid,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
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
import { IconArrowLeft, IconCheck, IconPlayerPlay, IconPlus, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listBalances } from "../../api/inventory";
import {
  addWorkOrderPart,
  cancelWorkOrder,
  completeWorkOrder,
  getWorkOrder,
  startWorkOrder,
  type CalibrationResult,
  type WorkOrder,
} from "../../api/maintenance";
import { listRecords, type Material } from "../../api/masterdata";
import { useAuth } from "../../auth/AuthContext";
import { AttachmentPanel } from "../../components/attachments/AttachmentPanel";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { normalizeDecimal } from "../common/forms";
import { CancelModal } from "../inventory/CancelModal";
import { idOrNull } from "../inventory/options";
import { Info, Qty } from "../inventory/shared";
import { canWork, MAINTENANCE_BASE, OPEN_STATUSES } from "./config";
import { KindBadge, WorkOrderStatusBadge } from "./shared";
import { formatMinutes, mt } from "./strings";

const CONTENT_TYPE = "maintenance.maintenanceworkorder";

// --- tamamla ---

function CompleteModal({
  order,
  onClose,
  onDone,
}: {
  order: WorkOrder;
  onClose: () => void;
  onDone: (saved: WorkOrder) => void;
}) {
  const [rows, setRows] = useState(() =>
    order.checklist_rows.map((row) => ({ item: row.item, done: row.done, note: row.note ?? "" })),
  );
  const [workDone, setWorkDone] = useState("");
  const [duration, setDuration] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [certificate, setCertificate] = useState("");
  const [error, setError] = useState("");
  const calibration = order.kind === "CALIBRATION";
  const durationInvalid = duration.trim() !== "" && !/^\d+$/.test(duration.trim());
  const ready =
    workDone.trim() !== "" &&
    rows.every((row) => row.done) &&
    !durationInvalid &&
    (!calibration || result !== null);
  const mutation = useMutation({
    mutationFn: () =>
      completeWorkOrder(order.id, {
        work_done: workDone.trim(),
        duration_minutes: duration.trim() ? Number(duration) : null,
        checklist: rows.map((row) => ({ done: row.done, note: row.note.trim() })),
        calibration_result: calibration ? (result as CalibrationResult) : "",
        certificate_no: calibration ? certificate.trim() : "",
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: mt.completedMsg });
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const setRow = (index: number, patch: Partial<(typeof rows)[number]>) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  return (
    <Modal opened onClose={onClose} title={mt.completeTitle} size="lg">
      <Stack>
        {rows.length > 0 && (
          <Stack gap="xs" data-testid="complete-checklist">
            <Text size="sm" fw={500}>
              {mt.checklist}
            </Text>
            <Text size="xs" c="dimmed">
              {mt.checklistHint}
            </Text>
            {rows.map((row, index) => (
              <Paper key={index} withBorder p="sm" radius="md">
                <Group wrap="nowrap" align="center">
                  <Checkbox
                    size="lg"
                    label={row.item}
                    checked={row.done}
                    onChange={(event) => setRow(index, { done: event.currentTarget.checked })}
                    style={{ flex: 1 }}
                  />
                  <TextInput
                    aria-label={`${mt.note}: ${row.item}`}
                    placeholder={mt.note}
                    value={row.note}
                    w={220}
                    onChange={(event) => setRow(index, { note: event.currentTarget.value })}
                  />
                </Group>
              </Paper>
            ))}
          </Stack>
        )}
        <Textarea
          label={mt.workDone}
          withAsterisk
          autosize
          minRows={3}
          size="md"
          value={workDone}
          onChange={(event) => setWorkDone(event.currentTarget.value)}
        />
        <TextInput
          label={mt.duration}
          inputMode="numeric"
          size="md"
          w={200}
          value={duration}
          error={durationInvalid || undefined}
          onChange={(event) => setDuration(event.currentTarget.value)}
        />
        {calibration && (
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <Select
              label={mt.calibrationResultLabel}
              withAsterisk
              size="md"
              data={(["PASSED", "FAILED"] as CalibrationResult[]).map((value) => ({
                value,
                label: mt.calibrationResult[value],
              }))}
              value={result}
              onChange={setResult}
            />
            <TextInput
              label={mt.certificateNo}
              size="md"
              value={certificate}
              onChange={(event) => setCertificate(event.currentTarget.value)}
            />
          </SimpleGrid>
        )}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" size="md" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button
            color="green"
            size="md"
            leftSection={<IconCheck size={18} />}
            disabled={!ready}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.complete}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// --- yedek parça ---

function useStockMaterials() {
  return useQuery({
    queryKey: ["options", "materials", "all-active"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Material>("materials", { is_active: true, page_size: 500 });
      return page.results;
    },
  });
}

function PartModal({
  order,
  onClose,
  onDone,
}: {
  order: WorkOrder;
  onClose: () => void;
  onDone: (saved: WorkOrder) => void;
}) {
  const materials = useStockMaterials();
  const [mode, setMode] = useState<"stocked" | "free">("stocked");
  const [material, setMaterial] = useState<string | null>(null);
  const [balance, setBalance] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("");
  const [description, setDescription] = useState("");
  const [unitText, setUnitText] = useState("");
  const [error, setError] = useState("");
  // Serbest (RELEASED) lotların bakiyeleri: lot + lokasyon birlikte seçilir.
  const balances = useQuery({
    queryKey: ["inventory", "balances", "maintenance-part", material],
    queryFn: () =>
      listBalances({ material: Number(material), lot_status: "RELEASED", page_size: 200 }),
    enabled: mode === "stocked" && Boolean(material),
  });
  const balanceRows = balances.data?.results ?? [];
  const selected = balanceRows.find((row) => String(row.id) === balance);
  const unit = (materials.data ?? []).find((row) => String(row.id) === material)?.base_unit_code;
  const mutation = useMutation({
    mutationFn: () =>
      addWorkOrderPart(
        order.id,
        mode === "stocked"
          ? {
              material: idOrNull(material),
              lot: selected?.lot ?? null,
              location: selected?.location ?? null,
              description: "",
              quantity: normalizeDecimal(quantity),
              unit_text: "",
            }
          : {
              material: null,
              lot: null,
              location: null,
              description: description.trim(),
              quantity: normalizeDecimal(quantity),
              unit_text: unitText.trim(),
            },
      ),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: mt.partAdded });
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const ready =
    quantity.trim() !== "" &&
    (mode === "stocked" ? Boolean(selected) : Boolean(description.trim()));
  return (
    <Modal opened onClose={onClose} title={mt.addPart} size="lg">
      <Stack>
        <SegmentedControl
          aria-label={mt.partKind}
          data={[
            { value: "stocked", label: mt.stocked },
            { value: "free", label: mt.freeText },
          ]}
          value={mode}
          onChange={(value) => setMode(value as "stocked" | "free")}
        />
        {mode === "stocked" ? (
          <>
            <Select
              label={mt.material}
              withAsterisk
              searchable
              data={(materials.data ?? []).map((row) => ({
                value: String(row.id),
                label: `${row.code} - ${row.name}`,
              }))}
              value={material}
              onChange={(value) => {
                setMaterial(value);
                setBalance(null);
              }}
              nothingFoundMessage={mt.notFound}
            />
            <Select
              label={mt.lotAndLocation}
              withAsterisk
              disabled={!material}
              data={balanceRows.map((row) => ({
                value: String(row.id),
                label: `${row.lot_no} · ${row.location_code} (${formatNumber(row.quantity)} ${row.unit})`,
              }))}
              value={balance}
              onChange={setBalance}
            />
            {material && !balances.isLoading && balanceRows.length === 0 && (
              <Text size="sm" c="orange">
                {mt.noStock}
              </Text>
            )}
            <TextInput
              label={`${mt.quantity}${unit ? ` (${unit})` : ""}`}
              withAsterisk
              inputMode="decimal"
              value={quantity}
              onChange={(event) => setQuantity(event.currentTarget.value)}
            />
          </>
        ) : (
          <>
            <TextInput
              label={mt.partDescription}
              withAsterisk
              value={description}
              onChange={(event) => setDescription(event.currentTarget.value)}
            />
            <Group grow>
              <TextInput
                label={mt.quantity}
                withAsterisk
                inputMode="decimal"
                value={quantity}
                onChange={(event) => setQuantity(event.currentTarget.value)}
              />
              <TextInput
                label={mt.unit}
                value={unitText}
                onChange={(event) => setUnitText(event.currentTarget.value)}
              />
            </Group>
          </>
        )}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button disabled={!ready} loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {mt.addPart}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// --- sayfa ---

function WorkOrderView({ order }: { order: WorkOrder }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [completing, setCompleting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [addingPart, setAddingPart] = useState(false);
  const [error, setError] = useState("");
  const refresh = (saved: WorkOrder) => {
    queryClient.setQueryData(["maintenance", "work-order", order.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
    void queryClient.invalidateQueries({ queryKey: ["workflow"] });
  };
  const start = useMutation({
    mutationFn: () => startWorkOrder(order.id),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: mt.started_ });
      refresh(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const isOpen = OPEN_STATUSES.includes(order.status);
  const worker = canWork(user, order);

  return (
    <Stack>
      <Anchor component={Link} to={`${MAINTENANCE_BASE}/is-emirleri`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {mt.tabs.workOrders}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{mt.workOrderTitle(order.number)}</Title>
          <WorkOrderStatusBadge status={order.status} />
          <KindBadge kind={order.kind} />
        </Group>
        {isOpen && worker && (
          <Group gap="xs">
            {order.status === "OPEN" && (
              <Button
                size="md"
                leftSection={<IconPlayerPlay size={18} />}
                loading={start.isPending}
                onClick={() => start.mutate()}
              >
                {mt.start}
              </Button>
            )}
            <Button
              size="md"
              color="green"
              leftSection={<IconCheck size={18} />}
              onClick={() => setCompleting(true)}
            >
              {mt.complete}
            </Button>
            <Button
              size="md"
              color="red"
              variant="light"
              leftSection={<IconX size={18} />}
              onClick={() => setCancelling(true)}
            >
              {mt.cancelOrder}
            </Button>
          </Group>
        )}
      </Group>
      {isOpen && !worker && (
        <Text size="sm" c="dimmed">
          {mt.notResponsible}
        </Text>
      )}
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={mt.equipment}>
            <Text size="sm" fw={600}>{`${order.equipment_code} - ${order.equipment_name}`}</Text>
          </Info>
          <Info label={mt.titleLabel}>
            <Text size="sm">{order.title}</Text>
          </Info>
          <Info label={mt.sourceLabel}>
            <Text size="sm">
              {order.source_display}
              {order.plan_title ? ` · ${order.plan_title}` : ""}
            </Text>
          </Info>
          <Info label={mt.responsibleRole}>
            <Text size="sm">{order.responsible_role_display}</Text>
          </Info>
          <Info label={mt.dueDate}>
            <Text size="sm">{formatDate(order.due_date)}</Text>
          </Info>
          <Info label={mt.createdAt}>
            <Text size="sm">
              {`${order.created_by_name ?? ""} · ${formatDateTime(order.created_at)}`}
            </Text>
          </Info>
          {order.previous_product_code && (
            <Info label={mt.previousProduct}>
              <Text size="sm">{order.previous_product_code}</Text>
            </Info>
          )}
          {order.started_at && (
            <Info label={mt.started}>
              <Text size="sm">
                {`${order.started_by_name ?? ""} · ${formatDateTime(order.started_at)}`}
              </Text>
            </Info>
          )}
          {order.completed_at && (
            <Info label={mt.completed}>
              <Text size="sm">
                {`${order.completed_by_name ?? ""} · ${formatDateTime(order.completed_at)}`}
              </Text>
            </Info>
          )}
          {order.duration_minutes !== null && (
            <Info label={mt.durationLabel}>
              <Text size="sm">{formatMinutes(order.duration_minutes)}</Text>
            </Info>
          )}
          {order.downtime_minutes !== null && (
            <Info label={mt.downtime}>
              <Text size="sm">{formatMinutes(order.downtime_minutes)}</Text>
            </Info>
          )}
          {order.calibration_result && (
            <Info label={mt.calibrationResultLabel}>
              <Text size="sm" c={order.calibration_result === "FAILED" ? "red" : "green"} fw={600}>
                {order.calibration_result_display}
                {order.certificate_no ? ` · ${order.certificate_no}` : ""}
              </Text>
            </Info>
          )}
          {order.status === "CANCELLED" && (
            <Info label={mt.cancelReason}>
              <Text size="sm">{order.cancel_reason}</Text>
            </Info>
          )}
        </SimpleGrid>
        {order.description && (
          <Stack gap={0} mt="sm">
            <Text size="xs" c="dimmed">
              {mt.description}
            </Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {order.description}
            </Text>
          </Stack>
        )}
        {order.work_done && (
          <Stack gap={0} mt="sm">
            <Text size="xs" c="dimmed">
              {mt.workDone}
            </Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {order.work_done}
            </Text>
          </Stack>
        )}
      </Paper>

      {order.checklist_rows.length > 0 && (
        <Stack gap="xs">
          <Title order={4}>{mt.checklist}</Title>
          <Table fz="sm" data-testid="work-order-checklist">
            <Table.Tbody>
              {order.checklist_rows.map((row, index) => (
                <Table.Tr key={index}>
                  <Table.Td w={40}>
                    <Checkbox checked={row.done} readOnly aria-label={row.item} />
                  </Table.Td>
                  <Table.Td>{row.item}</Table.Td>
                  <Table.Td c="dimmed">{row.note}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}

      <Stack gap="xs">
        <Group justify="space-between">
          <Title order={4}>{mt.parts}</Title>
          {isOpen && worker && (
            <Button
              variant="light"
              leftSection={<IconPlus size={16} />}
              onClick={() => setAddingPart(true)}
            >
              {mt.addPart}
            </Button>
          )}
        </Group>
        {order.parts.length === 0 ? (
          <Text size="sm" c="dimmed">
            {mt.noParts}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={640}>
            <Table striped fz="sm" data-testid="work-order-parts">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{mt.partDescription}</Table.Th>
                  <Table.Th>{mt.material}</Table.Th>
                  <Table.Th>{mt.lot}</Table.Th>
                  <Table.Th>{mt.location}</Table.Th>
                  <Table.Th ta="right">{mt.quantity}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {order.parts.map((part) => (
                  <Table.Tr key={part.id}>
                    <Table.Td>{part.description}</Table.Td>
                    <Table.Td>{part.material_code ?? ""}</Table.Td>
                    <Table.Td>{part.lot_no ?? ""}</Table.Td>
                    <Table.Td>{part.location_code ?? ""}</Table.Td>
                    <Table.Td ta="right">
                      <Qty value={part.quantity} unit={part.unit_text} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>

      <AttachmentPanel
        contentType={CONTENT_TYPE}
        objectId={order.id}
        defaultKind="PHOTO"
        title={mt.attachmentsTitle}
      />

      {completing && (
        <CompleteModal
          order={order}
          onClose={() => setCompleting(false)}
          onDone={(saved) => {
            setCompleting(false);
            refresh(saved);
          }}
        />
      )}
      {addingPart && (
        <PartModal
          order={order}
          onClose={() => setAddingPart(false)}
          onDone={(saved) => {
            setAddingPart(false);
            refresh(saved);
          }}
        />
      )}
      <CancelModal
        opened={cancelling}
        cancel={(reason) => cancelWorkOrder(order.id, reason)}
        onClose={() => setCancelling(false)}
        onDone={(saved) => {
          setCancelling(false);
          refresh(saved);
        }}
      />
    </Stack>
  );
}

/** Bakım iş emri (`BK-`): sorumlu birim ya da yönetim başlatır, kontrol listesini işaretleyip
 * tamamlar, yedek parça ekler; ekler ve yorumlar kayda bağlıdır. */
export function WorkOrderPage() {
  const orderId = Number(useParams().workOrderId);
  const query = useQuery({
    queryKey: ["maintenance", "work-order", orderId],
    queryFn: () => getWorkOrder(orderId),
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
        <WorkOrderView order={query.data} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <RecordPanel contentType={CONTENT_TYPE} objectId={query.data.id} />
      </Grid.Col>
    </Grid>
  );
}
