import {
  Alert,
  Button,
  Group,
  Modal,
  Pagination,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
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
  createSpecification,
  listDecisions,
  listSamples,
  listSpecifications,
  reviewDecision,
  sampleQueue,
  type QualityDecision,
  type Sample,
  type SampleStage,
  type SampleStatus,
  type Specification,
  type SpecStatus,
  type TestDefinition,
} from "../../api/quality";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime, formatElapsed } from "../../i18n/format";
import { CrudPage, type EntityConfig } from "../common/CrudPage";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { idOrNull } from "../inventory/options";
import { APPROVAL_ROLES, LAB_ROLES, QUALITY_BASE, samplePath, specPath, STAGES } from "./config";
import { DecisionBadge, SampleStatusBadge, SpecStatusBadge } from "./shared";
import { qt } from "./strings";

const PAGE_SIZE = 50;
const STAGE_OPTIONS = STAGES.map((value) => ({ value, label: qt.stage[value] }));
const SAMPLE_STATUS_OPTIONS = (Object.keys(qt.sampleStatus) as SampleStatus[]).map((value) => ({
  value,
  label: qt.sampleStatus[value],
}));
const SPEC_STATUS_OPTIONS = (Object.keys(qt.specStatus) as SpecStatus[]).map((value) => ({
  value,
  label: qt.specStatus[value],
}));

interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
}

function RowsTable<T extends { id: number }>(props: {
  columns: Column<T>[];
  rows: T[];
  loading: boolean;
  error: unknown;
  empty?: string;
  onOpen?: (row: T) => void;
  testId?: string;
}) {
  const { columns, rows, loading, error, onOpen } = props;
  return (
    <>
      {Boolean(error) && (
        <Alert color="red" variant="light">
          {getErrorMessage(error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={720}>
        <Table striped highlightOnHover={Boolean(onOpen)} data-testid={props.testId}>
          <Table.Thead>
            <Table.Tr>
              {columns.map((column) => (
                <Table.Th key={column.header}>{column.header}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                style={onOpen ? { cursor: "pointer" } : undefined}
                onClick={onOpen ? () => onOpen(row) : undefined}
              >
                {columns.map((column) => (
                  <Table.Td key={column.header}>{column.render(row)}</Table.Td>
                ))}
              </Table.Tr>
            ))}
            {!loading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={columns.length}>
                  <Text c="dimmed" ta="center" py="md">
                    {props.empty ?? ct.empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

function SearchBox(props: { value: string; onChange: (value: string) => void }) {
  return (
    <TextInput
      aria-label={qt.search}
      placeholder={qt.search}
      leftSection={<IconSearch size={16} />}
      value={props.value}
      w={300}
      onChange={(event) => props.onChange(event.currentTarget.value)}
    />
  );
}

const sampleColumns: Column<Sample>[] = [
  { header: qt.number, render: (r) => r.number },
  { header: qt.lot, render: (r) => r.lot_no },
  { header: qt.material, render: (r) => `${r.material_code} - ${r.material_name}` },
  { header: qt.stageLabel, render: (r) => qt.stage[r.stage] },
  { header: qt.spec, render: (r) => r.specification_label ?? "—" },
  { header: qt.openedAt, render: (r) => formatDateTime(r.created_at) },
  { header: qt.status, render: (r) => <SampleStatusBadge status={r.status} /> },
];

/** Laboratuvar kuyruğu: kararı verilmemiş numuneler, en eski önce, bekleme süresiyle. */
function QueueTab() {
  const navigate = useNavigate();
  const [stage, setStage] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["quality", "queue", stage, page],
    queryFn: () => sampleQueue({ stage: stage ?? undefined, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const columns: Column<Sample>[] = [
    ...sampleColumns,
    { header: qt.waiting, render: (r) => formatElapsed(r.created_at) },
  ];
  return (
    <Stack>
      <Select
        aria-label={qt.stageLabel}
        placeholder={qt.allStages}
        data={STAGE_OPTIONS}
        value={stage}
        clearable
        w={240}
        onChange={(value) => {
          setStage(value);
          setPage(1);
        }}
      />
      <RowsTable
        testId="sample-queue"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        empty={qt.queueEmpty}
        onOpen={(row) => navigate(samplePath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

function SamplesTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const params = {
    search: debounced || undefined,
    status: status ?? undefined,
    stage: stage ?? undefined,
    page,
    page_size: PAGE_SIZE,
  };
  const query = useQuery({
    queryKey: ["quality", "samples", params],
    queryFn: () => listSamples(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  return (
    <Stack>
      <Group>
        <SearchBox
          value={search}
          onChange={(value) => {
            setSearch(value);
            setPage(1);
          }}
        />
        <Select
          aria-label={qt.stageLabel}
          placeholder={qt.allStages}
          data={STAGE_OPTIONS}
          value={stage}
          clearable
          w={220}
          onChange={(value) => {
            setStage(value);
            setPage(1);
          }}
        />
        <Select
          aria-label={qt.status}
          placeholder={qt.allStatuses}
          data={SAMPLE_STATUS_OPTIONS}
          value={status}
          clearable
          w={200}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        />
      </Group>
      <RowsTable
        columns={sampleColumns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(samplePath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Yönetim: onay bekleyen şartlı kabul kararları. */
function ApprovalsTab() {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<{ row: QualityDecision; approve: boolean } | null>(null);
  const query = useQuery({
    queryKey: ["quality", "decisions", "pending"],
    queryFn: () => listDecisions({ approval_status: "PENDING", page_size: 200 }),
  });
  const columns: Column<QualityDecision>[] = [
    {
      header: qt.number,
      render: (r) => (
        <Link to={samplePath(r.sample)} onClick={(event) => event.stopPropagation()}>
          {r.sample_number}
        </Link>
      ),
    },
    { header: qt.lot, render: (r) => r.lot_no },
    { header: qt.material, render: (r) => `${r.material_code} - ${r.material_name}` },
    { header: qt.decisionLabel, render: (r) => <DecisionBadge decision={r.decision} /> },
    { header: qt.reason, render: (r) => r.reason },
    {
      header: qt.decidedBy,
      render: (r) => `${r.decided_by_name ?? ""} · ${formatDateTime(r.decided_at)}`,
    },
    {
      header: ct.actions,
      render: (r) => (
        <Group gap={4} wrap="nowrap">
          <Button
            size="compact-sm"
            color="green"
            onClick={() => setTarget({ row: r, approve: true })}
          >
            {qt.approve}
          </Button>
          <Button
            size="compact-sm"
            color="red"
            variant="light"
            onClick={() => setTarget({ row: r, approve: false })}
          >
            {qt.refuse}
          </Button>
        </Group>
      ),
    },
  ];
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {qt.approvalsIntro}
      </Text>
      <RowsTable
        testId="pending-approvals"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        empty={qt.approvalsEmpty}
      />
      <ReviewModal
        target={target}
        onClose={() => setTarget(null)}
        onDone={() => {
          setTarget(null);
          void queryClient.invalidateQueries({ queryKey: ["quality"] });
        }}
      />
    </Stack>
  );
}

export function ReviewModal({
  target,
  onClose,
  onDone,
}: {
  target: { row: QualityDecision; approve: boolean } | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => reviewDecision(target!.row.id, target!.approve, note.trim()),
    onSuccess: () => {
      setNote("");
      setError("");
      notifications.show({ color: "green", message: qt.reviewed });
      onDone();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  if (!target) return null;
  const noteRequired = !target.approve;
  return (
    <Modal
      opened
      onClose={onClose}
      title={`${target.approve ? qt.approve : qt.refuse}: ${target.row.lot_no}`}
    >
      <Stack>
        <Text size="sm">{`${qt.reason}: ${target.row.reason}`}</Text>
        <Textarea
          label={noteRequired ? qt.reviewNoteRequired : qt.reviewNote}
          withAsterisk={noteRequired}
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
            color={target.approve ? "green" : "red"}
            disabled={noteRequired && !note.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {target.approve ? qt.approve : qt.refuse}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function SpecsTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [stage, setStage] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>("APPROVED");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const params = {
    search: debounced || undefined,
    sample_stage: stage ?? undefined,
    status: status ?? undefined,
    page,
    page_size: PAGE_SIZE,
  };
  const query = useQuery({
    queryKey: ["quality", "specs", params],
    queryFn: () => listSpecifications(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const columns: Column<Specification>[] = [
    { header: qt.material, render: (r) => `${r.material_code} - ${r.material_name}` },
    { header: qt.stageLabel, render: (r) => qt.stage[r.sample_stage] },
    { header: qt.version, render: (r) => `v${r.version_no}` },
    { header: qt.lineCount, render: (r) => r.line_count ?? "" },
    { header: qt.changeNote, render: (r) => r.change_note },
    { header: qt.status, render: (r) => <SpecStatusBadge status={r.status} /> },
  ];
  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={ct.search}
            placeholder={ct.search}
            leftSection={<IconSearch size={16} />}
            value={search}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={qt.stageLabel}
            placeholder={qt.allStages}
            data={STAGE_OPTIONS}
            value={stage}
            clearable
            w={220}
            onChange={(value) => {
              setStage(value);
              setPage(1);
            }}
          />
          <Select
            aria-label={qt.status}
            placeholder={qt.allStatuses}
            data={SPEC_STATUS_OPTIONS}
            value={status}
            clearable
            w={180}
            onChange={(value) => {
              setStatus(value);
              setPage(1);
            }}
          />
        </Group>
        {hasAnyRole(user, LAB_ROLES) && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
            {qt.newSpec}
          </Button>
        )}
      </Group>
      <RowsTable
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(specPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      <NewSpecModal opened={creating} onClose={() => setCreating(false)} />
    </Stack>
  );
}

function NewSpecModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const materials = useOptions({ endpoint: "materials" });
  const [material, setMaterial] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>("INCOMING");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      createSpecification({
        material: idOrNull(material)!,
        sample_stage: stage as SampleStage,
        change_note: note.trim(),
      }),
    onSuccess: (spec) => {
      void queryClient.invalidateQueries({ queryKey: ["quality"] });
      navigate(specPath(spec.id));
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened={opened} onClose={onClose} title={qt.newSpec}>
      <Stack>
        <Select
          label={qt.material}
          withAsterisk
          searchable
          data={materials.data ?? []}
          value={material}
          onChange={setMaterial}
        />
        <Select
          label={qt.stageLabel}
          withAsterisk
          data={STAGE_OPTIONS}
          value={stage}
          allowDeselect={false}
          onChange={setStage}
        />
        <Textarea
          label={qt.changeNote}
          autosize
          minRows={1}
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
            disabled={!material || !stage}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {ct.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

const RESULT_TYPE_OPTIONS = (["NUMERIC", "PASS_FAIL", "TEXT"] as const).map((value) => ({
  value,
  label: qt.resultType[value],
}));

const testConfig: EntityConfig<TestDefinition> = {
  endpoint: "quality/tests",
  title: qt.tabs.tests,
  singular: qt.testSingular,
  writeRoles: LAB_ROLES,
  columns: [
    { key: "code", label: qt.code },
    { key: "name", label: qt.name },
    { key: "result_type", label: qt.resultTypeLabel, render: (r) => r.result_type_display },
    { key: "unit", label: qt.unit },
    { key: "method", label: qt.method },
  ],
  fields: [
    { name: "code", label: qt.code, type: "text", required: true },
    { name: "name", label: qt.name, type: "text", required: true },
    {
      name: "result_type",
      label: qt.resultTypeLabel,
      type: "select",
      required: true,
      options: RESULT_TYPE_OPTIONS,
    },
    { name: "unit", label: qt.unit, type: "text" },
    { name: "decimal_places", label: qt.decimalPlaces, type: "integer" },
    { name: "method", label: qt.method, type: "textarea", wide: true },
  ],
  defaults: { result_type: "NUMERIC", decimal_places: "2" },
};

interface TabDef {
  slug: string;
  label: string;
  roles: readonly Role[];
  render: () => ReactNode;
}

const TABS: TabDef[] = [
  { slug: "kuyruk", label: qt.tabs.queue, roles: LAB_ROLES, render: () => <QueueTab /> },
  { slug: "numuneler", label: qt.tabs.samples, roles: [], render: () => <SamplesTab /> },
  { slug: "onay", label: qt.tabs.approvals, roles: APPROVAL_ROLES, render: () => <ApprovalsTab /> },
  { slug: "spesifikasyonlar", label: qt.tabs.specs, roles: [], render: () => <SpecsTab /> },
  {
    slug: "testler",
    label: qt.tabs.tests,
    roles: [],
    render: () => <CrudPage config={testConfig} />,
  },
];

/** Kalite kontrol: sekmeler (`/kalite/<sekme>`). Laboratuvar kuyruğa, yönetim onaya düşer. */
export function QualityPage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const fallback = visible.some((item) => item.slug === "kuyruk")
    ? hasAnyRole(user, APPROVAL_ROLES) && !user?.roles.includes("laboratuvar")
      ? "onay"
      : "kuyruk"
    : visible.some((item) => item.slug === "onay")
      ? "onay"
      : "numuneler";
  const current = visible.find((item) => item.slug === (tab ?? fallback));
  if (!current) return <Navigate to={QUALITY_BASE} replace />;

  return (
    <Stack>
      <Title order={2}>{qt.title}</Title>
      <Tabs
        value={current.slug}
        onChange={(value) => value && navigate(`${QUALITY_BASE}/${value}`)}
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
