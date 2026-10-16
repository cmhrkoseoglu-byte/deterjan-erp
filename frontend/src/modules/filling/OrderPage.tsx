import {
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
import { notifications } from "@mantine/notifications";
import {
  IconArrowLeft,
  IconCheck,
  IconFlagCheck,
  IconPackage,
  IconPlayerPlay,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelFillingOrder,
  fillingOrderAction,
  getFillingOrder,
  orderReport,
  saveFillingOrder,
  startRun,
  type FillingOrderDetail,
} from "../../api/filling";
import { listRecords, type Equipment } from "../../api/masterdata";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { useOptions } from "../common/useOptions";
import { lotPath, today } from "../inventory/config";
import { idOrNull, useLocations } from "../inventory/options";
import { Info, Qty } from "../inventory/shared";
import { ReasonModal } from "../production/shared";
import {
  FILLING_BASE,
  fillingOrderPath,
  fillingPrepPath,
  LINE_ROLES,
  PLAN_ROLES,
  PREP_ROLES,
  PREP_STATUSES,
  runPath,
  STARTABLE_STATUSES,
} from "./config";
import { ReportTable } from "./ReportTable";
import { FillingOrderStatusBadge, RunStatusBadge } from "./shared";
import { ft } from "./strings";

// Ambalaj hazır olduktan sonra da ek hazırlama yapılabilir (ör. ikinci parti için).
const PICKABLE = [...PREP_STATUSES, "MATERIAL_READY", "IN_PROGRESS"];

/** Dolum emri: yeni/taslak formu ya da detay (ambalaj ihtiyacı, hazırlanan lotlar, partiler). */
export function FillingOrderPage() {
  const param = useParams().orderId;
  const isNew = param === "yeni";
  const orderId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["filling", "order", orderId],
    queryFn: () => getFillingOrder(orderId!),
    enabled: orderId !== null,
  });

  if (!isNew && query.isLoading) return <Loader />;
  if (!isNew && (query.isError || !query.data))
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const order = query.data ?? null;

  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: order ? 8 : 12 }}>
        {order ? <OrderDetail order={order} /> : <OrderForm order={null} />}
      </Grid.Col>
      {order && (
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <RecordPanel contentType="filling.fillingorder" objectId={order.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

function BackLink() {
  return (
    <Anchor component={Link} to={`${FILLING_BASE}/emirler`} size="sm">
      <Group gap={4}>
        <IconArrowLeft size={14} />
        {ft.tabs.orders}
      </Group>
    </Anchor>
  );
}

interface Draft {
  finished_product: string | null;
  planned_units: string;
  filling_line: string | null;
  output_location: string | null;
  planned_date: string;
  notes: string;
}

function toDraft(order: FillingOrderDetail | null): Draft {
  return {
    finished_product: order ? String(order.finished_product) : null,
    planned_units: order ? String(order.planned_units) : "",
    filling_line: order ? String(order.filling_line) : null,
    output_location: order ? String(order.output_location) : null,
    planned_date: order?.planned_date ?? today(),
    notes: order?.notes ?? "",
  };
}

function useFillingLines() {
  return useQuery({
    queryKey: ["options", "filling-lines"],
    staleTime: 60_000,
    queryFn: async () =>
      (
        await listRecords<Equipment>("equipment", {
          is_active: true,
          equipment_type: "FILLING_LINE",
          page_size: 500,
        })
      ).results,
  });
}

function OrderForm({
  order,
  onSaved,
}: {
  order: FillingOrderDetail | null;
  onSaved?: (saved: FillingOrderDetail) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => toDraft(order));
  const [error, setError] = useState("");
  const products = useOptions({ endpoint: "materials", params: { material_type: "FINISHED" } });
  const lines = useFillingLines();
  const locations = useLocations();
  const set = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));
  const lineOptions = (lines.data ?? []).map((row) => ({
    value: String(row.id),
    label: `${row.code} - ${row.name}`,
  }));
  const storeOptions = (locations.data ?? []).filter((row) => row.type === "STORAGE");

  const save = useMutation({
    mutationFn: () =>
      saveFillingOrder(order?.id ?? null, {
        finished_product: idOrNull(draft.finished_product),
        planned_units: Number(draft.planned_units),
        filling_line: idOrNull(draft.filling_line),
        output_location: idOrNull(draft.output_location),
        planned_date: draft.planned_date,
        notes: draft.notes.trim(),
      }),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: ft.saved });
      queryClient.setQueryData(["filling", "order", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["filling"] });
      if (!order) navigate(fillingOrderPath(saved.id), { replace: true });
      onSaved?.(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Stack>
      {!order && (
        <>
          <BackLink />
          <Title order={2}>{ft.newOrder}</Title>
        </>
      )}
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
          <Select
            label={ft.product}
            withAsterisk
            searchable
            data={products.data ?? []}
            value={draft.finished_product}
            onChange={(value) => set({ finished_product: value })}
          />
          <TextInput
            label={ft.plannedUnits}
            withAsterisk
            inputMode="numeric"
            value={draft.planned_units}
            onChange={(event) =>
              set({ planned_units: event.currentTarget.value.replace(/\D/g, "") })
            }
          />
          <TextInput
            label={ft.plannedDate}
            type="date"
            withAsterisk
            value={draft.planned_date}
            onChange={(event) => set({ planned_date: event.currentTarget.value })}
          />
          <Select
            label={ft.line}
            withAsterisk
            data={lineOptions}
            value={draft.filling_line}
            onChange={(value) => set({ filling_line: value })}
          />
          <Select
            label={ft.outputLocation}
            withAsterisk
            data={storeOptions}
            value={draft.output_location}
            onChange={(value) => set({ output_location: value })}
          />
        </SimpleGrid>
        <Textarea
          mt="sm"
          label={ft.notes}
          autosize
          minRows={1}
          value={draft.notes}
          onChange={(event) => set({ notes: event.currentTarget.value })}
        />
      </Paper>
      <Group justify="flex-end">
        <Button loading={save.isPending} onClick={() => save.mutate()}>
          {ft.saveDraft}
        </Button>
      </Group>
    </Stack>
  );
}

function OrderDetail({ order }: { order: FillingOrderDetail }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<"approve" | "finish" | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const canPlan = hasAnyRole(user, PLAN_ROLES);
  const canPrep = hasAnyRole(user, PREP_ROLES);
  const canFill = hasAnyRole(user, LINE_ROLES);
  const isDraft = order.status === "DRAFT";
  const openRun = order.runs.find((run) => run.status === "IN_PROGRESS");
  const hasFinishedRun = order.runs.some((run) => run.status === "COMPLETED");
  const report = useQuery({
    queryKey: ["filling", "order-report", order.id, order.status],
    queryFn: () => orderReport(order.id),
    enabled: hasFinishedRun,
  });

  const refresh = (saved: FillingOrderDetail) => {
    setError("");
    queryClient.setQueryData(["filling", "order", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["filling"] });
  };
  const action = useMutation({
    mutationFn: (name: "approve" | "finish") => fillingOrderAction(order.id, name),
    onSuccess: (saved, name) => {
      setConfirm(null);
      notifications.show({ color: "green", message: name === "approve" ? ft.approved : ft.saved });
      refresh(saved);
    },
    onError: (err) => {
      setConfirm(null);
      setError(getErrorMessage(err));
    },
  });
  const start = useMutation({
    mutationFn: () => startRun(order.id),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["filling"] });
      navigate(runPath(run.id));
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Stack>
      <BackLink />
      <Group justify="space-between">
        <Group>
          <Title order={2}>{ft.orderTitle(order.number)}</Title>
          <FillingOrderStatusBadge status={order.status} />
        </Group>
        <Group gap="xs">
          {canPlan && isDraft && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setConfirm("approve")}
            >
              {ft.approve}
            </Button>
          )}
          {canPrep && PICKABLE.includes(order.status) && (
            <Button
              leftSection={<IconPackage size={16} />}
              onClick={() => navigate(fillingPrepPath(order.id))}
            >
              {ft.openPrep}
            </Button>
          )}
          {canFill && STARTABLE_STATUSES.includes(order.status) && !openRun && (
            <Button
              color="violet"
              leftSection={<IconPlayerPlay size={16} />}
              loading={start.isPending}
              onClick={() => start.mutate()}
            >
              {ft.startRun}
            </Button>
          )}
          {canFill && order.status === "IN_PROGRESS" && !openRun && hasFinishedRun && (
            <Button
              color="teal"
              leftSection={<IconFlagCheck size={16} />}
              onClick={() => setConfirm("finish")}
            >
              {ft.finishFilling}
            </Button>
          )}
          {canPlan && order.allowed_transitions.includes("CANCELLED") && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {ft.cancelOrder}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      {canPlan && isDraft ? (
        <OrderForm key={order.id} order={order} onSaved={refresh} />
      ) : (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            <Info label={ft.product}>
              <Text size="sm">{`${order.finished_product_code} - ${order.finished_product_name}`}</Text>
            </Info>
            <Info label={ft.spec}>
              <Text size="sm">
                {`${ft.specVersion(order.packaging_spec_version)} · ${formatNumber(order.fill_quantity)} ${order.fill_unit_code} · ${order.units_per_case}/koli`}
              </Text>
            </Info>
            <Info label={ft.bulk}>
              <Text size="sm">{order.bulk_product_code}</Text>
            </Info>
            <Info label={ft.plannedUnits}>
              <Text size="sm">{`${formatNumber(order.planned_units)} ${order.unit}`}</Text>
            </Info>
            <Info label={ft.plannedDate}>
              <Text size="sm">{formatDate(order.planned_date)}</Text>
            </Info>
            <Info label={ft.line}>
              <Text size="sm">
                {`${order.filling_line_code} - ${order.filling_line_name} (${order.line_location_code ?? "—"})`}
              </Text>
            </Info>
            <Info label={ft.outputLocation}>
              <Text size="sm">{order.output_location_code}</Text>
            </Info>
            {order.approved_at && (
              <Info label={ft.approvedBy}>
                <Text size="sm">{`${order.approved_by_name ?? ""} · ${formatDateTime(order.approved_at)}`}</Text>
              </Info>
            )}
            {order.completed_at && (
              <Info label={ft.completedAt}>
                <Text size="sm">{formatDateTime(order.completed_at)}</Text>
              </Info>
            )}
            {order.status === "CANCELLED" && (
              <Info label={ft.cancelReason}>
                <Text size="sm">{order.cancel_reason}</Text>
              </Info>
            )}
            {order.notes && (
              <Info label={ft.notes}>
                <Text size="sm">{order.notes}</Text>
              </Info>
            )}
          </SimpleGrid>
        </Paper>
      )}

      {order.requirements.length > 0 && (
        <>
          <Title order={4}>{ft.requirements}</Title>
          <Table.ScrollContainer minWidth={680}>
            <Table striped fz="sm" data-testid="requirements">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{ft.material}</Table.Th>
                  <Table.Th ta="right">{ft.perUnit}</Table.Th>
                  <Table.Th ta="right">{ft.allowance}</Table.Th>
                  <Table.Th ta="right">{ft.required}</Table.Th>
                  <Table.Th ta="right">{ft.net}</Table.Th>
                  <Table.Th ta="right">{ft.picked}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {order.requirements.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.sequence}</Table.Td>
                    <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
                    <Table.Td ta="right">{formatNumber(row.quantity_per_unit)}</Table.Td>
                    <Table.Td ta="right">%{formatNumber(row.scrap_allowance_pct)}</Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.required_quantity} unit={row.unit} />
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.net_quantity} unit={row.unit} />
                    </Table.Td>
                    <Table.Td ta="right">
                      <Text span size="sm" c={row.is_ready ? "green" : undefined}>
                        {`${formatNumber(row.picked_quantity)} ${row.unit}`}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}

      {order.picks.length > 0 && (
        <>
          <Title order={4}>{ft.picks}</Title>
          <Table.ScrollContainer minWidth={600}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{ft.material}</Table.Th>
                  <Table.Th>{ft.lotNo}</Table.Th>
                  <Table.Th ta="right">{ft.quantity}</Table.Th>
                  <Table.Th>{ft.from}</Table.Th>
                  <Table.Th>{ft.picked}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {order.picks.map((pick) => (
                  <Table.Tr key={pick.id} c={pick.returned_at ? "dimmed" : undefined}>
                    <Table.Td>{pick.material_code}</Table.Td>
                    <Table.Td>
                      <Anchor component={Link} to={lotPath(pick.lot)} size="sm">
                        {pick.lot_no}
                      </Anchor>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={pick.quantity} unit={pick.unit} />
                    </Table.Td>
                    <Table.Td>{`${pick.from_location_code} → ${pick.to_location_code}`}</Table.Td>
                    <Table.Td>{`${pick.picked_by_name ?? ""} · ${formatDateTime(pick.picked_at)}`}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}

      <Title order={4}>{ft.runs}</Title>
      {order.runs.length === 0 ? (
        <Text size="sm" c="dimmed">
          {ft.noRuns}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={600}>
          <Table striped highlightOnHover fz="sm" data-testid="runs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{ft.outputLot}</Table.Th>
                <Table.Th ta="right">{ft.goodUnits}</Table.Th>
                <Table.Th ta="right">{ft.variancePct}</Table.Th>
                <Table.Th>{ft.startedAt}</Table.Th>
                <Table.Th>{ft.status}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {order.runs.map((run) => (
                <Table.Tr
                  key={run.id}
                  style={{ cursor: "pointer" }}
                  onClick={() => navigate(runPath(run.id))}
                >
                  <Table.Td>{`${run.output_lot_no} (${run.output_lot_status_display})`}</Table.Td>
                  <Table.Td ta="right">
                    {run.good_units === null ? "—" : formatNumber(run.good_units)}
                  </Table.Td>
                  <Table.Td ta="right">
                    {run.bulk_variance_pct === null
                      ? "—"
                      : `%${formatNumber(run.bulk_variance_pct)}`}
                  </Table.Td>
                  <Table.Td>{formatDateTime(run.started_at)}</Table.Td>
                  <Table.Td>
                    <RunStatusBadge status={run.status} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {report.data && <ReportTable report={report.data} />}

      <ConfirmModal
        opened={confirm !== null}
        message={confirm === "approve" ? ft.approveConfirm : ft.finishFillingConfirm}
        confirmLabel={confirm === "approve" ? ft.approve : ft.finishFilling}
        loading={action.isPending}
        onConfirm={() => confirm && action.mutate(confirm)}
        onClose={() => setConfirm(null)}
      />
      <ReasonModal
        opened={cancelOpen}
        title={ft.cancelTitle}
        hint={ft.cancelHint}
        label={ft.cancelReason}
        confirmLabel={ft.cancelOrder}
        submit={(reason) => cancelFillingOrder(order.id, reason)}
        onClose={() => setCancelOpen(false)}
        onDone={(saved) => {
          setCancelOpen(false);
          refresh(saved);
        }}
      />
    </Stack>
  );
}
