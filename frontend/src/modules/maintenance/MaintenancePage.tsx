import {
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  Pagination,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
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
import { IconPlayerPlay, IconPlayerStop, IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  createChangeoverRule,
  createWorkOrder,
  endDowntime,
  getCalibrationStatus,
  getDowntimeSummary,
  getMaintenanceSettings,
  listChangeoverRules,
  listDowntimes,
  listPlans,
  listWorkOrders,
  saveMaintenanceSettings,
  savePlan,
  setChangeoverRuleActive,
  setPlanActive,
  startDowntime,
  type Downtime,
  type DowntimeReason,
  type MaintenanceKind,
  type MaintenancePlan,
  type MaintenanceSettings,
  type PlanKind,
  type WorkOrder,
  type WorkOrderStatus,
} from "../../api/maintenance";
import { listRecords, type Material } from "../../api/masterdata";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { ct } from "../common/strings";
import { RowsTable } from "../filling/FillingPage";
import { today } from "../inventory/config";
import { idOrNull } from "../inventory/options";
import { BreakdownButton } from "./BreakdownButton";
import {
  CHANGEOVER_ROLES,
  DOWNTIME_REASONS,
  DOWNTIME_ROLES,
  MAINTENANCE_BASE,
  OPEN_STATUSES,
  PLAN_ROLES,
  READ_ROLES,
  SETTINGS_ROLES,
  workOrderPath,
} from "./config";
import { cleanItems, equipmentLabel, useEquipmentOptions } from "./options";
import { CalibrationBadge, ChecklistEditor, KindBadge, WorkOrderStatusBadge } from "./shared";
import { formatMinutes, mt } from "./strings";

const PAGE_SIZE = 50;

/** Sorumlu birim seçenekleri (bakım iş emirlerini yürüten roller). */
const ROLE_OPTIONS = (["uretim", "dolum", "laboratuvar", "planlama", "yonetim"] as Role[]).map(
  (value) => ({ value, label: tr.roles[value] }),
);

function useEquipmentSelect() {
  const equipment = useEquipmentOptions();
  return (equipment.data ?? []).map((row) => ({
    value: String(row.id),
    label: equipmentLabel(row),
  }));
}

function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert color="red" variant="light">
      {typeof error === "string" ? error : getErrorMessage(error)}
    </Alert>
  );
}

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

const positiveInt = (value: string) => /^\d+$/.test(value.trim()) && Number(value) > 0;

// --- iş emirleri ---

const WORK_KINDS: MaintenanceKind[] = ["PERIODIC", "CLEANING", "CALIBRATION", "REPAIR"];

function WorkOrderModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const equipment = useEquipmentSelect();
  const [draft, setDraft] = useState({
    equipment: null as string | null,
    kind: "PERIODIC" as MaintenanceKind,
    title: "",
    description: "",
    responsible_role: null as string | null,
    due_date: "",
    checklist: [] as string[],
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createWorkOrder({
        equipment: idOrNull(draft.equipment)!,
        kind: draft.kind,
        title: draft.title.trim(),
        description: draft.description.trim(),
        responsible_role: (draft.responsible_role ?? "") as Role | "",
        due_date: draft.due_date || null,
        checklist: cleanItems(draft.checklist),
      }),
    onSuccess: (order) => {
      notifications.show({ color: "green", message: mt.workOrderCreated });
      void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
      void queryClient.invalidateQueries({ queryKey: ["workflow"] });
      onClose();
      navigate(workOrderPath(order.id));
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={mt.newWorkOrder} size="lg">
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label={mt.equipment}
            withAsterisk
            searchable
            data={equipment}
            value={draft.equipment}
            onChange={(value) => setDraft({ ...draft, equipment: value })}
            nothingFoundMessage={mt.notFound}
          />
          <Select
            label={mt.kindLabel}
            withAsterisk
            allowDeselect={false}
            data={WORK_KINDS.map((value) => ({ value, label: mt.kind[value] }))}
            value={draft.kind}
            onChange={(value) =>
              setDraft({ ...draft, kind: (value ?? "PERIODIC") as MaintenanceKind })
            }
          />
        </SimpleGrid>
        <TextInput
          label={mt.titleLabel}
          value={draft.title}
          onChange={(event) => setDraft({ ...draft, title: event.currentTarget.value })}
        />
        <Textarea
          label={mt.description}
          autosize
          minRows={2}
          value={draft.description}
          onChange={(event) => setDraft({ ...draft, description: event.currentTarget.value })}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label={mt.responsibleRole}
            description={mt.responsibleRoleHint}
            clearable
            data={ROLE_OPTIONS}
            value={draft.responsible_role}
            onChange={(value) => setDraft({ ...draft, responsible_role: value })}
          />
          <TextInput
            label={mt.dueDate}
            type="date"
            value={draft.due_date}
            onChange={(event) => setDraft({ ...draft, due_date: event.currentTarget.value })}
          />
        </SimpleGrid>
        <ChecklistEditor
          items={draft.checklist}
          onChange={(checklist) => setDraft({ ...draft, checklist })}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button
            disabled={!draft.equipment}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

const OPEN_FILTER = "open";
const STATUS_OPTIONS = [
  { value: OPEN_FILTER, label: mt.openStatuses },
  ...(Object.keys(mt.status) as WorkOrderStatus[]).map((value) => ({
    value,
    label: mt.status[value],
  })),
];

function WorkOrdersTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<string | null>(OPEN_FILTER);
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const statuses: WorkOrderStatus[] =
    status === OPEN_FILTER ? OPEN_STATUSES : status ? [status as WorkOrderStatus] : [];
  const params = { page, page_size: PAGE_SIZE, search: debounced || undefined };
  const query = useQuery({
    queryKey: ["maintenance", "work-orders", statuses, params],
    queryFn: () => listWorkOrders(params, statuses),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const columns = [
    { header: mt.number, render: (r: WorkOrder) => r.number },
    {
      header: mt.equipment,
      render: (r: WorkOrder) => `${r.equipment_code} - ${r.equipment_name}`,
    },
    {
      header: mt.titleLabel,
      render: (r: WorkOrder) => (
        <Text size="sm" lineClamp={2}>
          {r.title}
        </Text>
      ),
    },
    { header: mt.kindLabel, render: (r: WorkOrder) => <KindBadge kind={r.kind} /> },
    { header: mt.sourceLabel, render: (r: WorkOrder) => r.source_display },
    { header: mt.responsibleRole, render: (r: WorkOrder) => r.responsible_role_display },
    { header: mt.dueDate, render: (r: WorkOrder) => formatDate(r.due_date) },
    {
      header: mt.statusLabel,
      render: (r: WorkOrder) => <WorkOrderStatusBadge status={r.status} />,
    },
  ];
  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={mt.searchWorkOrders}
            placeholder={mt.searchWorkOrders}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={300}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={mt.statusLabel}
            placeholder={mt.allStatuses}
            data={STATUS_OPTIONS}
            value={status}
            clearable
            w={220}
            onChange={(value) => {
              setStatus(value);
              setPage(1);
            }}
          />
        </Group>
        {hasAnyRole(user, PLAN_ROLES) && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
            {mt.newWorkOrder}
          </Button>
        )}
      </Group>
      <RowsTable
        testId="maintenance-work-orders"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(workOrderPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      {creating && <WorkOrderModal onClose={() => setCreating(false)} />}
    </Stack>
  );
}

// --- duruşlar ---

function StartDowntimeModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const equipment = useEquipmentSelect();
  const [draft, setDraft] = useState({
    equipment: null as string | null,
    reason: null as string | null,
    started_at: "",
    note: "",
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      startDowntime({
        equipment: idOrNull(draft.equipment)!,
        reason: draft.reason as DowntimeReason,
        ...(draft.started_at ? { started_at: new Date(draft.started_at).toISOString() } : {}),
        note: draft.note.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: mt.downtimeStarted });
      void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={mt.startDowntime}>
      <Stack>
        <Select
          label={mt.equipment}
          withAsterisk
          searchable
          size="md"
          data={equipment}
          value={draft.equipment}
          onChange={(value) => setDraft({ ...draft, equipment: value })}
          nothingFoundMessage={mt.notFound}
        />
        <Select
          label={mt.reasonLabel}
          withAsterisk
          size="md"
          data={DOWNTIME_REASONS.map((value) => ({ value, label: mt.reason[value] }))}
          value={draft.reason}
          onChange={(value) => setDraft({ ...draft, reason: value })}
        />
        <TextInput
          label={mt.startedAt}
          description={mt.startedAtHint}
          type="datetime-local"
          size="md"
          value={draft.started_at}
          onChange={(event) => setDraft({ ...draft, started_at: event.currentTarget.value })}
        />
        <Textarea
          label={mt.note}
          autosize
          minRows={2}
          value={draft.note}
          onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" size="md" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button
            color="red"
            size="md"
            disabled={!draft.equipment || !draft.reason}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.startDowntime}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function EndDowntimeModal({ downtime, onClose }: { downtime: Downtime; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => endDowntime(downtime.id, { note: note.trim() }),
    onSuccess: () => {
      notifications.show({ color: "green", message: mt.downtimeEnded });
      void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={mt.endDowntimeTitle}>
      <Stack>
        <Text fw={600}>
          {`${downtime.equipment_code} - ${downtime.equipment_name} · ${downtime.reason_display}`}
        </Text>
        <Textarea
          label={mt.note}
          autosize
          minRows={2}
          size="md"
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" size="md" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button size="md" loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {mt.endDowntime}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function OpenDowntimes({ onEnd }: { onEnd: (row: Downtime) => void }) {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ["maintenance", "downtimes", "open"],
    queryFn: () => listDowntimes({ is_open: true, page_size: 200 }),
  });
  const rows = query.data?.results ?? [];
  const writer = hasAnyRole(user, DOWNTIME_ROLES);
  return (
    <Stack gap="xs">
      <Title order={4}>{mt.openDowntimes}</Title>
      <ErrorAlert error={query.error} />
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {mt.noOpenDowntimes}
        </Text>
      )}
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} data-testid="open-downtimes">
        {rows.map((row) => (
          <Paper
            key={row.id}
            withBorder
            p="md"
            radius="md"
            style={{ borderColor: "var(--mantine-color-red-6)", borderWidth: 2 }}
            bg="var(--mantine-color-red-light)"
            data-testid="open-downtime"
          >
            <Stack gap={4}>
              <Group justify="space-between" wrap="nowrap">
                <Text fw={700}>{`${row.equipment_code} - ${row.equipment_name}`}</Text>
                <Badge color="red">{row.reason_display}</Badge>
              </Group>
              <Text size="sm">{`${mt.startedAt}: ${formatDateTime(row.started_at)}`}</Text>
              {row.work_order_number && (
                <Text size="sm">{`${mt.workOrder}: ${row.work_order_number}`}</Text>
              )}
              {row.note && (
                <Text size="sm" c="dimmed" lineClamp={2}>
                  {row.note}
                </Text>
              )}
              {writer && (
                <Button
                  mt="xs"
                  size="md"
                  leftSection={<IconPlayerStop size={18} />}
                  onClick={() => onEnd(row)}
                >
                  {mt.endDowntime}
                </Button>
              )}
            </Stack>
          </Paper>
        ))}
      </SimpleGrid>
    </Stack>
  );
}

function DowntimeSummary({ range, equipment }: { range: Range; equipment: string | null }) {
  const query = useQuery({
    queryKey: ["maintenance", "downtime-summary", range, equipment],
    queryFn: () =>
      getDowntimeSummary({
        date_from: range.date_from,
        date_to: range.date_to,
        equipment: idOrNull(equipment) ?? undefined,
      }),
    enabled: Boolean(range.date_from && range.date_to),
  });
  const rows = query.data ?? [];
  const total = rows.reduce((sum, row) => sum + row.minutes, 0);
  return (
    <Stack gap="xs">
      <Title order={4}>{mt.summary}</Title>
      <Text size="sm" c="dimmed">
        {mt.summaryIntro}
      </Text>
      <ErrorAlert error={query.error} />
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {mt.noSummary}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={560}>
          <Table striped fz="sm" data-testid="downtime-summary">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{mt.equipment}</Table.Th>
                <Table.Th>{mt.reasonLabel}</Table.Th>
                <Table.Th ta="right">{mt.count}</Table.Th>
                <Table.Th ta="right">{mt.minutes}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={`${row.equipment_id}-${row.reason}`}>
                  <Table.Td>{`${row.equipment_code} - ${row.equipment_name}`}</Table.Td>
                  <Table.Td>{row.reason_display}</Table.Td>
                  <Table.Td ta="right">{row.count}</Table.Td>
                  <Table.Td ta="right">{formatMinutes(row.minutes)}</Table.Td>
                </Table.Tr>
              ))}
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text size="sm" fw={700}>
                    {mt.total}
                  </Text>
                </Table.Td>
                <Table.Td ta="right">
                  <Text size="sm" fw={700}>
                    {formatMinutes(total)}
                  </Text>
                </Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

interface Range {
  date_from: string;
  date_to: string;
}

function DowntimesTab() {
  const { user } = useAuth();
  const equipmentOptions = useEquipmentSelect();
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState<Downtime | null>(null);
  const [equipment, setEquipment] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [range, setRange] = useState<Range>({ date_from: daysAgo(30), date_to: today() });
  const [page, setPage] = useState(1);
  const params = {
    page,
    page_size: PAGE_SIZE,
    equipment: idOrNull(equipment) ?? undefined,
    reason: (reason ?? undefined) as DowntimeReason | undefined,
    is_open: onlyOpen ? true : undefined,
    date_from: range.date_from || undefined,
    date_to: range.date_to || undefined,
  };
  const query = useQuery({
    queryKey: ["maintenance", "downtimes", "list", params],
    queryFn: () => listDowntimes(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const rows = query.data?.results ?? [];
  const writer = hasAnyRole(user, DOWNTIME_ROLES);
  const resetPage = () => setPage(1);

  return (
    <Stack gap="lg">
      {writer && (
        <Group justify="flex-end">
          <Button
            color="red"
            size="md"
            leftSection={<IconPlayerPlay size={18} />}
            onClick={() => setStarting(true)}
          >
            {mt.startDowntime}
          </Button>
        </Group>
      )}
      <OpenDowntimes onEnd={setEnding} />

      <Stack gap="xs">
        <Title order={4}>{mt.history}</Title>
        <Group align="flex-end">
          <Select
            label={mt.equipment}
            placeholder={mt.allEquipment}
            searchable
            clearable
            data={equipmentOptions}
            value={equipment}
            w={240}
            onChange={(value) => {
              setEquipment(value);
              resetPage();
            }}
          />
          <Select
            label={mt.reasonLabel}
            placeholder={mt.allReasons}
            clearable
            data={DOWNTIME_REASONS.map((value) => ({ value, label: mt.reason[value] }))}
            value={reason}
            w={200}
            onChange={(value) => {
              setReason(value);
              resetPage();
            }}
          />
          <TextInput
            label={mt.dateFrom}
            type="date"
            value={range.date_from}
            onChange={(event) => {
              setRange({ ...range, date_from: event.currentTarget.value });
              resetPage();
            }}
          />
          <TextInput
            label={mt.dateTo}
            type="date"
            value={range.date_to}
            onChange={(event) => {
              setRange({ ...range, date_to: event.currentTarget.value });
              resetPage();
            }}
          />
          <Checkbox
            mb={8}
            label={mt.onlyOpen}
            checked={onlyOpen}
            onChange={(event) => {
              setOnlyOpen(event.currentTarget.checked);
              resetPage();
            }}
          />
        </Group>
        <ErrorAlert error={query.error} />
        <Table.ScrollContainer minWidth={900}>
          <Table striped fz="sm" data-testid="downtimes">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{mt.equipment}</Table.Th>
                <Table.Th>{mt.reasonLabel}</Table.Th>
                <Table.Th>{mt.startedAt}</Table.Th>
                <Table.Th>{mt.endedAt}</Table.Th>
                <Table.Th ta="right">{mt.minutes}</Table.Th>
                <Table.Th>{mt.workOrder}</Table.Th>
                <Table.Th>{mt.note}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr
                  key={row.id}
                  bg={row.ended_at ? undefined : "var(--mantine-color-red-light)"}
                >
                  <Table.Td>{`${row.equipment_code} - ${row.equipment_name}`}</Table.Td>
                  <Table.Td>{row.reason_display}</Table.Td>
                  <Table.Td>{formatDateTime(row.started_at)}</Table.Td>
                  <Table.Td>
                    {row.ended_at ? (
                      formatDateTime(row.ended_at)
                    ) : (
                      <Badge color="red" variant="light">
                        {mt.ongoing}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">{formatMinutes(row.minutes)}</Table.Td>
                  <Table.Td>{row.work_order_number ?? ""}</Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={2}>
                      {[row.note, row.end_note].filter(Boolean).join(" · ")}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {writer && !row.ended_at && (
                      <Button size="compact-sm" variant="light" onClick={() => setEnding(row)}>
                        {mt.endDowntime}
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
              {!query.isLoading && rows.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={8}>
                    <Text c="dimmed" ta="center" py="md">
                      {ct.empty}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
        {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      </Stack>

      <DowntimeSummary range={range} equipment={equipment} />

      {starting && <StartDowntimeModal onClose={() => setStarting(false)} />}
      {ending && <EndDowntimeModal downtime={ending} onClose={() => setEnding(null)} />}
    </Stack>
  );
}

// --- bakım planları ---

const PLAN_KINDS: PlanKind[] = ["PERIODIC", "CLEANING", "CALIBRATION"];

function PlanModal({ plan, onClose }: { plan: MaintenancePlan | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const equipment = useEquipmentSelect();
  const [draft, setDraft] = useState(() => ({
    equipment: plan ? String(plan.equipment) : (null as string | null),
    kind: (plan?.kind ?? "PERIODIC") as PlanKind,
    title: plan?.title ?? "",
    periodType: (plan?.interval_runs ? "runs" : "days") as "days" | "runs",
    period: String(plan?.interval_runs ?? plan?.interval_days ?? ""),
    next_due_date: plan?.next_due_date ?? "",
    responsible_role: (plan?.responsible_role || null) as string | null,
    checklist: plan?.checklist ?? [],
    note: plan?.note ?? "",
  }));
  const [error, setError] = useState("");
  const byDays = draft.periodType === "days" || draft.kind === "CALIBRATION";
  const mutation = useMutation({
    mutationFn: () =>
      savePlan(plan?.id ?? null, {
        equipment: idOrNull(draft.equipment)!,
        kind: draft.kind,
        title: draft.title.trim(),
        interval_days: byDays ? Number(draft.period) : null,
        interval_runs: byDays ? null : Number(draft.period),
        checklist: cleanItems(draft.checklist),
        responsible_role: (draft.responsible_role ?? "") as Role | "",
        next_due_date: byDays && draft.next_due_date ? draft.next_due_date : null,
        note: draft.note.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: mt.planSaved });
      void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={plan ? mt.editPlan : mt.newPlan} size="lg">
      <Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label={mt.equipment}
            withAsterisk
            searchable
            data={equipment}
            value={draft.equipment}
            onChange={(value) => setDraft({ ...draft, equipment: value })}
            nothingFoundMessage={mt.notFound}
          />
          <Select
            label={mt.kindLabel}
            withAsterisk
            allowDeselect={false}
            data={PLAN_KINDS.map((value) => ({ value, label: mt.kind[value] }))}
            value={draft.kind}
            onChange={(value) => setDraft({ ...draft, kind: (value ?? "PERIODIC") as PlanKind })}
          />
        </SimpleGrid>
        <TextInput
          label={mt.titleLabel}
          withAsterisk
          value={draft.title}
          onChange={(event) => setDraft({ ...draft, title: event.currentTarget.value })}
        />
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {mt.periodType}
          </Text>
          <SegmentedControl
            data={[
              { value: "days", label: mt.byDays },
              { value: "runs", label: mt.byRuns, disabled: draft.kind === "CALIBRATION" },
            ]}
            value={byDays ? "days" : "runs"}
            onChange={(value) => setDraft({ ...draft, periodType: value as "days" | "runs" })}
          />
        </Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <TextInput
            label={`${mt.periodValue} (${byDays ? mt.byDays : mt.byRuns})`}
            description={byDays ? undefined : mt.runsHint}
            withAsterisk
            inputMode="numeric"
            value={draft.period}
            onChange={(event) => setDraft({ ...draft, period: event.currentTarget.value })}
          />
          {byDays && (
            <TextInput
              label={mt.nextDue}
              description={mt.nextDueHint}
              type="date"
              value={draft.next_due_date}
              onChange={(event) => setDraft({ ...draft, next_due_date: event.currentTarget.value })}
            />
          )}
          <Select
            label={mt.responsibleRole}
            description={mt.responsibleRoleHint}
            clearable
            data={ROLE_OPTIONS}
            value={draft.responsible_role}
            onChange={(value) => setDraft({ ...draft, responsible_role: value })}
          />
        </SimpleGrid>
        <ChecklistEditor
          items={draft.checklist}
          onChange={(checklist) => setDraft({ ...draft, checklist })}
        />
        <Textarea
          label={mt.note}
          autosize
          minRows={1}
          value={draft.note}
          onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button
            disabled={!draft.equipment || !draft.title.trim() || !positiveInt(draft.period)}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function periodText(plan: MaintenancePlan): string {
  if (plan.interval_runs) return mt.periodRuns(plan.interval_runs);
  if (plan.interval_days) return mt.periodDays(plan.interval_days);
  return "";
}

function PlansTab() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [showInactive, setShowInactive] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<MaintenancePlan | "new" | null>(null);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    is_active: showInactive ? undefined : true,
  };
  const query = useQuery({
    queryKey: ["maintenance", "plans", params],
    queryFn: () => listPlans(params),
    placeholderData: keepPreviousData,
  });
  const toggle = useMutation({
    mutationFn: (plan: MaintenancePlan) => setPlanActive(plan.id, !plan.is_active),
    onSuccess: () => {
      notifications.show({ color: "green", message: mt.planSaved });
      void queryClient.invalidateQueries({ queryKey: ["maintenance", "plans"] });
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const rows = query.data?.results ?? [];
  const writer = hasAnyRole(user, PLAN_ROLES);
  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={mt.searchPlans}
            placeholder={mt.searchPlans}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={300}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Checkbox
            label={mt.showInactive}
            checked={showInactive}
            onChange={(event) => {
              setShowInactive(event.currentTarget.checked);
              setPage(1);
            }}
          />
        </Group>
        {writer && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            {mt.newPlan}
          </Button>
        )}
      </Group>
      <ErrorAlert error={query.error} />
      <Table.ScrollContainer minWidth={1000}>
        <Table striped fz="sm" data-testid="maintenance-plans">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{mt.equipment}</Table.Th>
              <Table.Th>{mt.titleLabel}</Table.Th>
              <Table.Th>{mt.kindLabel}</Table.Th>
              <Table.Th>{mt.period}</Table.Th>
              <Table.Th>{mt.responsibleRole}</Table.Th>
              <Table.Th>{mt.nextDue}</Table.Th>
              <Table.Th ta="right">{mt.runsDone}</Table.Th>
              <Table.Th>{mt.lastDone}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((plan) => (
              <Table.Tr key={plan.id} opacity={plan.is_active ? 1 : 0.6}>
                <Table.Td>{`${plan.equipment_code} - ${plan.equipment_name}`}</Table.Td>
                <Table.Td>{plan.title}</Table.Td>
                <Table.Td>
                  <KindBadge kind={plan.kind} />
                </Table.Td>
                <Table.Td>{periodText(plan)}</Table.Td>
                <Table.Td>{plan.responsible_role_display}</Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    {formatDate(plan.next_due_date)}
                    {plan.is_overdue ? (
                      <Badge color="red" variant="light" size="sm">
                        {mt.overdue}
                      </Badge>
                    ) : (
                      plan.is_due && (
                        <Badge color="yellow" variant="light" size="sm">
                          {mt.due}
                        </Badge>
                      )
                    )}
                    {!plan.is_active && (
                      <Badge color="gray" variant="light" size="sm">
                        {mt.inactive}
                      </Badge>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td ta="right">
                  {plan.runs_done !== null && plan.interval_runs
                    ? `${plan.runs_done} / ${plan.interval_runs}`
                    : ""}
                </Table.Td>
                <Table.Td>{formatDateTime(plan.last_done_at)}</Table.Td>
                <Table.Td>
                  {writer && (
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => setEditing(plan)}>
                        {ct.edit}
                      </Button>
                      <Button
                        size="compact-xs"
                        variant="light"
                        color={plan.is_active ? "red" : "green"}
                        loading={toggle.isPending && toggle.variables?.id === plan.id}
                        onClick={() => toggle.mutate(plan)}
                      >
                        {plan.is_active ? mt.deactivate : mt.activate}
                      </Button>
                    </Group>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
            {!query.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={9}>
                  <Text c="dimmed" ta="center" py="md">
                    {ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      {editing && (
        <PlanModal plan={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
    </Stack>
  );
}

// --- kalibrasyon ---

function CalibrationTab() {
  const query = useQuery({
    queryKey: ["maintenance", "calibration"],
    queryFn: getCalibrationStatus,
  });
  const rows = query.data ?? [];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {mt.calibrationIntro}
      </Text>
      <ErrorAlert error={query.error} />
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {mt.noScales}
        </Text>
      )}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={640}>
          <Table striped fz="sm" data-testid="calibration-status">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{mt.equipment}</Table.Th>
                <Table.Th>{mt.statusLabel}</Table.Th>
                <Table.Th>{mt.nextDue}</Table.Th>
                <Table.Th ta="right">{mt.daysLeft}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.equipment}>
                  <Table.Td>{`${row.equipment_code} - ${row.equipment_name}`}</Table.Td>
                  <Table.Td>
                    <CalibrationBadge status={row.status} label={row.label} />
                  </Table.Td>
                  <Table.Td>{formatDate(row.next_due_date)}</Table.Td>
                  <Table.Td ta="right">
                    {row.days_left === null ? "" : mt.daysLeftValue(row.days_left)}
                  </Table.Td>
                  <Table.Td>
                    {row.is_down && (
                      <Badge color="red" variant="filled">
                        {mt.isDown}
                      </Badge>
                    )}
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

// --- temizliksiz geçişler ---

function useBulkProducts() {
  return useQuery({
    queryKey: ["options", "materials", "BULK"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Material>("materials", {
        material_type: "BULK",
        is_active: true,
        page_size: 500,
      });
      return page.results.map((row) => ({
        value: String(row.id),
        label: `${row.code} - ${row.name}`,
      }));
    },
  });
}

function ChangeoverModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const products = useBulkProducts();
  const [draft, setDraft] = useState({
    from: null as string | null,
    to: null as string | null,
    note: "",
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createChangeoverRule({
        from_product: idOrNull(draft.from)!,
        to_product: idOrNull(draft.to)!,
        note: draft.note.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: mt.ruleSaved });
      void queryClient.invalidateQueries({ queryKey: ["maintenance", "changeovers"] });
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const data = products.data ?? [];
  return (
    <Modal opened onClose={onClose} title={mt.newRule}>
      <Stack>
        <Select
          label={mt.fromProduct}
          withAsterisk
          searchable
          data={data}
          value={draft.from}
          onChange={(value) => setDraft({ ...draft, from: value })}
          nothingFoundMessage={mt.notFound}
        />
        <Select
          label={mt.toProduct}
          withAsterisk
          searchable
          data={data.filter((row) => row.value !== draft.from)}
          value={draft.to}
          onChange={(value) => setDraft({ ...draft, to: value })}
          nothingFoundMessage={mt.notFound}
        />
        <Textarea
          label={mt.note}
          autosize
          minRows={2}
          value={draft.note}
          onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button
            disabled={!draft.from || !draft.to}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ChangeoversTab() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [creating, setCreating] = useState(false);
  const query = useQuery({
    queryKey: ["maintenance", "changeovers"],
    queryFn: () => listChangeoverRules({ page_size: 500 }),
  });
  const toggle = useMutation({
    mutationFn: (rule: { id: number; is_active: boolean }) =>
      setChangeoverRuleActive(rule.id, !rule.is_active),
    onSuccess: () => {
      notifications.show({ color: "green", message: mt.ruleChanged });
      void queryClient.invalidateQueries({ queryKey: ["maintenance", "changeovers"] });
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });
  const rows = query.data?.results ?? [];
  const writer = hasAnyRole(user, CHANGEOVER_ROLES);
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={720}>
          {mt.changeoverIntro}
        </Text>
        {writer && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
            {mt.newRule}
          </Button>
        )}
      </Group>
      <ErrorAlert error={query.error} />
      <Table.ScrollContainer minWidth={640}>
        <Table striped fz="sm" data-testid="changeover-rules">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{mt.fromProduct}</Table.Th>
              <Table.Th>{mt.toProduct}</Table.Th>
              <Table.Th>{mt.note}</Table.Th>
              <Table.Th>{mt.statusLabel}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((rule) => (
              <Table.Tr key={rule.id}>
                <Table.Td>{`${rule.from_product_code} - ${rule.from_product_name}`}</Table.Td>
                <Table.Td>{`${rule.to_product_code} - ${rule.to_product_name}`}</Table.Td>
                <Table.Td>{rule.note}</Table.Td>
                <Table.Td>
                  <Badge color={rule.is_active ? "green" : "gray"} variant="light">
                    {rule.is_active ? mt.active : mt.inactive}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {writer && (
                    <Button
                      size="compact-xs"
                      variant="light"
                      color={rule.is_active ? "red" : "green"}
                      loading={toggle.isPending && toggle.variables?.id === rule.id}
                      onClick={() => toggle.mutate(rule)}
                    >
                      {rule.is_active ? mt.deactivate : mt.activate}
                    </Button>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
            {!query.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed" ta="center" py="md">
                    {ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {creating && <ChangeoverModal onClose={() => setCreating(false)} />}
    </Stack>
  );
}

// --- ayarlar (yönetim) ---

function SettingsForm({
  initial,
  onSaved,
}: {
  initial: MaintenanceSettings;
  onSaved: (saved: MaintenanceSettings) => void;
}) {
  const [values, setValues] = useState({
    warning: String(initial.calibration_warning_days),
    lead: String(initial.plan_lead_days),
  });
  const [error, setError] = useState("");
  const valid = /^\d+$/.test(values.warning.trim()) && /^\d+$/.test(values.lead.trim());
  const mutation = useMutation({
    mutationFn: () =>
      saveMaintenanceSettings({
        calibration_warning_days: Number(values.warning),
        plan_lead_days: Number(values.lead),
      }),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: mt.settingsSaved });
      onSaved(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Paper withBorder p="md" radius="md" maw={520}>
      <Stack>
        <TextInput
          label={mt.calibrationWarningDays}
          description={mt.calibrationWarningHint}
          inputMode="numeric"
          value={values.warning}
          onChange={(event) => setValues({ ...values, warning: event.currentTarget.value })}
        />
        <TextInput
          label={mt.planLeadDays}
          description={mt.planLeadHint}
          inputMode="numeric"
          value={values.lead}
          onChange={(event) => setValues({ ...values, lead: event.currentTarget.value })}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button disabled={!valid} loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {mt.save}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function SettingsTab() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["maintenance", "settings"],
    queryFn: getMaintenanceSettings,
  });
  if (query.isLoading) return null;
  if (query.error || !query.data) return <ErrorAlert error={query.error} />;
  return (
    <SettingsForm
      initial={query.data}
      onSaved={(saved) => queryClient.setQueryData(["maintenance", "settings"], saved)}
    />
  );
}

interface TabDef {
  slug: string;
  label: string;
  roles: readonly Role[];
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  {
    slug: "is-emirleri",
    label: mt.tabs.workOrders,
    roles: READ_ROLES,
    render: () => <WorkOrdersTab />,
  },
  { slug: "duruslar", label: mt.tabs.downtimes, roles: READ_ROLES, render: () => <DowntimesTab /> },
  { slug: "planlar", label: mt.tabs.plans, roles: READ_ROLES, render: () => <PlansTab /> },
  {
    slug: "kalibrasyon",
    label: mt.tabs.calibration,
    roles: READ_ROLES,
    render: () => <CalibrationTab />,
  },
  {
    slug: "temizliksiz-gecisler",
    label: mt.tabs.changeovers,
    roles: READ_ROLES,
    render: () => <ChangeoversTab />,
  },
  {
    slug: "ayarlar",
    label: mt.tabs.settings,
    roles: SETTINGS_ROLES,
    render: () => <SettingsTab />,
  },
];

/** Bakım: sekmeler (`/bakim/<sekme>`). Arıza bildirimi her rolde açıktır. */
export function MaintenancePage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const current = visible.find((item) => item.slug === (tab ?? "is-emirleri"));
  if (!current) return <Navigate to={MAINTENANCE_BASE} replace />;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{mt.title}</Title>
        <BreakdownButton />
      </Group>
      <Tabs
        value={current.slug}
        onChange={(value) => value && navigate(`${MAINTENANCE_BASE}/${value}`)}
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
