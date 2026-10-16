import {
  Badge,
  Button,
  Checkbox,
  Group,
  Modal,
  Pagination,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconFileSpreadsheet, IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelWasteRecord,
  createSds,
  createStatement,
  createWasteRecord,
  getHseSettings,
  getHseSummary,
  getSdsGaps,
  getStorageUtilisation,
  listContractors,
  listIncidents,
  listMaterialHazards,
  listSds,
  listStatements,
  listStorageLimits,
  listWasteRecords,
  saveContractor,
  saveHseSettings,
  saveStorageLimit,
  SDS_GAPS_EXPORT_URL,
  setContractorActive,
  setStatementActive,
  setStorageLimitActive,
  updateSds,
  updateStatement,
  type HazardClass,
  type HazardStatement,
  type HseSettings,
  type Incident,
  type IncidentStatus,
  type MaterialHazard,
  type SafetyDataSheet,
  type StatementKind,
  type StorageLimit,
  type WasteContractor,
  type WasteRecord,
} from "../../api/hse";
import { listRecords, type Material, type Partner } from "../../api/masterdata";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { AttachmentPanel } from "../../components/attachments/AttachmentPanel";
import { WithHazard } from "../../components/hazard/HazardIcon";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { RowsTable } from "../filling/FillingPage";
import { today } from "../inventory/config";
import { CancelModal } from "../inventory/CancelModal";
import { idOrNull, useLocations } from "../inventory/options";
import { Info } from "../inventory/shared";
import {
  HAZARD_CLASSES,
  HAZARD_ROLES,
  HSE_BASE,
  HSE_ROLES,
  INCIDENT_ROLES,
  INCIDENT_TYPES,
  OPEN_INCIDENT_STATUSES,
  SDS_READ_ROLES,
  STORAGE_READ_ROLES,
  incidentPath,
} from "./config";
import { IncidentReportButton } from "./IncidentReportModal";
import { MaterialHazardModal } from "./MaterialHazardModal";
import {
  ErrorAlert,
  IncidentStatusBadge,
  PictogramBadges,
  SdsStateBadge,
  SeverityBadge,
  SignalWordBadge,
  UtilisationBar,
} from "./shared";
import { hs } from "./strings";

const PAGE_SIZE = 50;

function daysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

const SDS_CONTENT_TYPE = "hse.safetydatasheet";
const WASTE_CONTENT_TYPE = "hse.wasterecord";

function useMaterialOptions() {
  return useQuery({
    queryKey: ["options", "materials", "all-active"],
    staleTime: 60_000,
    queryFn: async () => {
      const page = await listRecords<Material>("materials", { is_active: true, page_size: 500 });
      return page.results;
    },
  });
}

function useMaterialSelect() {
  const materials = useMaterialOptions();
  return (materials.data ?? []).map((row) => ({
    value: String(row.id),
    label: `${row.code} - ${row.name}`,
  }));
}

function useSupplierSelect() {
  const suppliers = useQuery({
    queryKey: ["options", "suppliers", "all-active"],
    staleTime: 60_000,
    queryFn: async () =>
      (await listRecords<Partner>("suppliers", { is_active: true, page_size: 500 })).results,
  });
  return (suppliers.data ?? []).map((row) => ({
    value: String(row.id),
    label: `${row.code} - ${row.name}`,
  }));
}

function ActiveBadge({ active }: { active: boolean }) {
  return (
    <Badge color={active ? "green" : "gray"} variant="light">
      {active ? hs.active : hs.inactive}
    </Badge>
  );
}

/** Basit kayıt penceresi: alanlar + hata + Vazgeç / Kaydet. */
function FormModal({
  title,
  children,
  error,
  ready,
  pending,
  onSave,
  onClose,
  size,
}: {
  title: string;
  children: ReactNode;
  error: string;
  ready: boolean;
  pending: boolean;
  onSave: () => void;
  onClose: () => void;
  size?: string;
}) {
  return (
    <Modal opened onClose={onClose} title={title} size={size}>
      <Stack>
        {children}
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {hs.cancel}
          </Button>
          <Button disabled={!ready} loading={pending} onClick={onSave}>
            {hs.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Kaydı kaydeden / aktifliği değiştiren mutasyon (bildirim + "hse" önbelleğini tazeler). */
function useSave<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  message: string | ((result: TResult) => string),
  onDone?: (result: TResult) => void,
) {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      setError("");
      notifications.show({
        color: "green",
        message: typeof message === "string" ? message : message(result),
      });
      void queryClient.invalidateQueries({ queryKey: ["hse"] });
      onDone?.(result);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return { mutation, error, setError };
}

function useToggle<T extends { id: number; is_active: boolean }>(
  fn: (id: number, active: boolean) => Promise<T>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (row: T) => fn(row.id, !row.is_active),
    onSuccess: () => {
      notifications.show({ color: "green", message: hs.changed });
      void queryClient.invalidateQueries({ queryKey: ["hse"] });
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });
}

function ToggleButton<T extends { id: number; is_active: boolean }>({
  row,
  toggle,
}: {
  row: T;
  toggle: ReturnType<typeof useToggle<T>>;
}) {
  return (
    <Button
      size="compact-xs"
      variant="light"
      color={row.is_active ? "red" : "green"}
      loading={toggle.isPending && toggle.variables?.id === row.id}
      onClick={(event) => {
        event.stopPropagation();
        toggle.mutate(row);
      }}
    >
      {row.is_active ? hs.deactivate : hs.activate}
    </Button>
  );
}

function EmptyRow({ colSpan, text = ct.empty }: { colSpan: number; text?: string }) {
  return (
    <Table.Tr>
      <Table.Td colSpan={colSpan}>
        <Text c="dimmed" ta="center" py="md">
          {text}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}

// --- olaylar ---

const OPEN_FILTER = "open";
const STATUS_OPTIONS = [
  { value: OPEN_FILTER, label: hs.openStatuses },
  ...(Object.keys(hs.incidentStatus) as IncidentStatus[]).map((value) => ({
    value,
    label: hs.incidentStatus[value],
  })),
];

function IncidentsTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [status, setStatus] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const statuses: IncidentStatus[] =
    status === OPEN_FILTER ? OPEN_INCIDENT_STATUSES : status ? [status as IncidentStatus] : [];
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    incident_type: type ?? undefined,
  };
  const query = useQuery({
    queryKey: ["hse", "incidents", statuses, params],
    queryFn: () => listIncidents(params, statuses),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const columns = [
    { header: hs.number, render: (r: Incident) => r.number },
    { header: hs.occurredAt, render: (r: Incident) => formatDateTime(r.occurred_at) },
    { header: hs.incidentTypeLabel, render: (r: Incident) => r.incident_type_display },
    {
      header: hs.place,
      render: (r: Incident) => (
        <Text size="sm" lineClamp={2}>
          {[r.place, r.location_code, r.equipment_code].filter(Boolean).join(" · ")}
        </Text>
      ),
    },
    {
      header: hs.injury,
      render: (r: Incident) =>
        r.injury ? (
          <Badge color="red" variant="light">
            {hs.yes}
          </Badge>
        ) : (
          hs.no
        ),
    },
    { header: hs.severityLabel, render: (r: Incident) => <SeverityBadge severity={r.severity} /> },
    { header: hs.reportedBy, render: (r: Incident) => r.created_by_name ?? "" },
    { header: hs.statusLabel, render: (r: Incident) => <IncidentStatusBadge status={r.status} /> },
  ];
  return (
    <Stack>
      <Group>
        <TextInput
          aria-label={hs.searchIncidents}
          placeholder={hs.searchIncidents}
          leftSection={<IconSearch size={16} />}
          value={search}
          w={280}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Select
          aria-label={hs.statusLabel}
          placeholder={hs.allStatuses}
          data={STATUS_OPTIONS}
          value={status}
          clearable
          w={220}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        />
        <Select
          aria-label={hs.incidentTypeLabel}
          placeholder={hs.allTypes}
          data={INCIDENT_TYPES.map((value) => ({ value, label: hs.incidentType[value] }))}
          value={type}
          clearable
          w={200}
          onChange={(value) => {
            setType(value);
            setPage(1);
          }}
        />
      </Group>
      {!hasAnyRole(user, HSE_ROLES) && (
        <Text size="sm" c="dimmed">
          {hs.onlyOwn}
        </Text>
      )}
      <RowsTable
        testId="hse-incidents"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => navigate(incidentPath(row.id))}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

// --- GBF ---

function SdsModal({ sheet, onClose }: { sheet: SafetyDataSheet | null; onClose: () => void }) {
  const { user } = useAuth();
  const writer = hasAnyRole(user, HSE_ROLES);
  const materials = useMaterialSelect();
  const suppliers = useSupplierSelect();
  const [saved, setSaved] = useState<SafetyDataSheet | null>(sheet);
  const [draft, setDraft] = useState({
    material: sheet ? String(sheet.material) : (null as string | null),
    supplier: sheet?.supplier ? String(sheet.supplier) : (null as string | null),
    revision_no: sheet?.revision_no ?? "",
    revision_date: sheet?.revision_date ?? today(),
    valid_until: sheet?.valid_until ?? "",
    language: sheet?.language ?? "tr",
    note: sheet?.note ?? "",
  });
  const { mutation, error } = useSave(
    () => {
      const common = {
        supplier: idOrNull(draft.supplier),
        revision_no: draft.revision_no.trim(),
        revision_date: draft.revision_date,
        valid_until: draft.valid_until || null,
        language: draft.language.trim() || "tr",
        note: draft.note.trim(),
      };
      return saved
        ? updateSds(saved.id, common)
        : createSds({ material: idOrNull(draft.material)!, ...common });
    },
    hs.sdsSaved,
    // Yeni GBF kaydedilince pencere açık kalır: PDF hemen yüklenebilir.
    (result) => setSaved(result),
  );
  const editable = writer && (saved === null || saved.is_current);
  const ready =
    Boolean(draft.material) && draft.revision_no.trim() !== "" && draft.revision_date !== "";
  return (
    <Modal
      opened
      onClose={onClose}
      title={saved ? `${saved.material_code} · rev. ${saved.revision_no}` : hs.newSds}
      size="lg"
    >
      <Stack>
        {!saved && (
          <Text size="xs" c="dimmed">
            {hs.newRevisionHint}
          </Text>
        )}
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label={hs.material}
            withAsterisk
            searchable
            disabled={saved !== null}
            data={
              saved && !materials.some((row) => row.value === String(saved.material))
                ? [
                    ...materials,
                    {
                      value: String(saved.material),
                      label: `${saved.material_code} - ${saved.material_name}`,
                    },
                  ]
                : materials
            }
            value={draft.material}
            onChange={(value) => setDraft({ ...draft, material: value })}
            nothingFoundMessage={hs.notFound}
          />
          <Select
            label={hs.supplier}
            clearable
            searchable
            disabled={!editable}
            data={suppliers}
            value={draft.supplier}
            onChange={(value) => setDraft({ ...draft, supplier: value })}
            nothingFoundMessage={hs.notFound}
          />
          <TextInput
            label={hs.revisionNo}
            withAsterisk
            disabled={!editable}
            value={draft.revision_no}
            onChange={(event) => setDraft({ ...draft, revision_no: event.currentTarget.value })}
          />
          <TextInput
            label={hs.revisionDate}
            withAsterisk
            type="date"
            disabled={!editable}
            value={draft.revision_date}
            onChange={(event) => setDraft({ ...draft, revision_date: event.currentTarget.value })}
          />
          <TextInput
            label={hs.validUntil}
            type="date"
            disabled={!editable}
            value={draft.valid_until}
            onChange={(event) => setDraft({ ...draft, valid_until: event.currentTarget.value })}
          />
          <TextInput
            label={hs.language}
            disabled={!editable}
            value={draft.language}
            onChange={(event) => setDraft({ ...draft, language: event.currentTarget.value })}
          />
        </SimpleGrid>
        <Textarea
          label={hs.note}
          autosize
          minRows={2}
          disabled={!editable}
          value={draft.note}
          onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {editable ? hs.cancel : hs.close}
          </Button>
          {editable && (
            <Button
              disabled={!ready}
              loading={mutation.isPending}
              onClick={() => mutation.mutate(undefined)}
            >
              {hs.save}
            </Button>
          )}
        </Group>
        {saved && (
          <AttachmentPanel
            contentType={SDS_CONTENT_TYPE}
            objectId={saved.id}
            defaultKind="DOCUMENT"
            title={hs.sdsFiles}
          />
        )}
      </Stack>
    </Modal>
  );
}

function SdsGapReport() {
  const query = useQuery({ queryKey: ["hse", "sds-gaps"], queryFn: getSdsGaps });
  const rows = query.data ?? [];
  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>{hs.gapReport}</Title>
            <Text size="sm" c="dimmed" maw={720}>
              {hs.gapIntro}
            </Text>
          </Stack>
          <Button
            component="a"
            href={SDS_GAPS_EXPORT_URL}
            variant="default"
            leftSection={<IconFileSpreadsheet size={16} />}
          >
            {hs.excel}
          </Button>
        </Group>
        <ErrorAlert error={query.error} />
        <Table.ScrollContainer minWidth={640}>
          <Table striped fz="sm" data-testid="sds-gaps">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{hs.material}</Table.Th>
                <Table.Th>{hs.materialType}</Table.Th>
                <Table.Th>{hs.sdsState}</Table.Th>
                <Table.Th>{hs.revisionNo}</Table.Th>
                <Table.Th>{hs.revisionDate}</Table.Th>
                <Table.Th>{hs.validUntil}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.material_id}>
                  <Table.Td>
                    <WithHazard hazardous={row.is_hazardous}>
                      {`${row.material_code} - ${row.material_name}`}
                    </WithHazard>
                  </Table.Td>
                  <Table.Td>{row.material_type_display}</Table.Td>
                  <Table.Td>
                    <SdsStateBadge status={row.status} label={row.status_display} />
                  </Table.Td>
                  <Table.Td>{row.revision_no}</Table.Td>
                  <Table.Td>{formatDate(row.revision_date)}</Table.Td>
                  <Table.Td>{formatDate(row.valid_until)}</Table.Td>
                </Table.Tr>
              ))}
              {!query.isLoading && rows.length === 0 && <EmptyRow colSpan={6} text={hs.noGaps} />}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Stack>
    </Paper>
  );
}

function SdsTab() {
  const { user } = useAuth();
  const materials = useMaterialSelect();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [material, setMaterial] = useState<string | null>(null);
  const [onlyCurrent, setOnlyCurrent] = useState(true);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<SafetyDataSheet | "new" | null>(null);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    material: material ?? undefined,
    current: onlyCurrent ? true : undefined,
  };
  const query = useQuery({
    queryKey: ["hse", "sds", params],
    queryFn: () => listSds(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const columns = [
    {
      header: hs.material,
      render: (r: SafetyDataSheet) => `${r.material_code} - ${r.material_name}`,
    },
    { header: hs.supplier, render: (r: SafetyDataSheet) => r.supplier_name ?? "" },
    { header: hs.revisionNo, render: (r: SafetyDataSheet) => r.revision_no },
    { header: hs.revisionDate, render: (r: SafetyDataSheet) => formatDate(r.revision_date) },
    { header: hs.validUntil, render: (r: SafetyDataSheet) => formatDate(r.valid_until) },
    {
      header: hs.files,
      render: (r: SafetyDataSheet) =>
        r.file_count > 0 ? (
          String(r.file_count)
        ) : (
          <Text span size="sm" c="orange">
            {hs.noFile}
          </Text>
        ),
    },
    {
      header: hs.statusLabel,
      render: (r: SafetyDataSheet) => (
        <Badge color={r.is_current ? "green" : "gray"} variant="light">
          {r.is_current ? hs.current : hs.superseded}
        </Badge>
      ),
    },
  ];
  return (
    <Stack>
      <SdsGapReport />
      <Group justify="space-between">
        <Title order={4}>{hs.sdsArchive}</Title>
        {hasAnyRole(user, HSE_ROLES) && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            {hs.newSds}
          </Button>
        )}
      </Group>
      <Group>
        <TextInput
          aria-label={hs.searchSds}
          placeholder={hs.searchSds}
          leftSection={<IconSearch size={16} />}
          value={search}
          w={260}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Select
          aria-label={hs.material}
          placeholder={hs.allMaterials}
          searchable
          clearable
          data={materials}
          value={material}
          w={260}
          onChange={(value) => {
            setMaterial(value);
            setPage(1);
          }}
        />
        <Switch
          label={hs.onlyCurrent}
          checked={onlyCurrent}
          onChange={(event) => {
            setOnlyCurrent(event.currentTarget.checked);
            setPage(1);
          }}
        />
      </Group>
      <RowsTable
        testId="hse-sds"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => setEditing(row)}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      {editing && (
        <SdsModal sheet={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
    </Stack>
  );
}

// --- tehlike bilgileri ---

function HazardsTab() {
  const { user } = useAuth();
  const materials = useMaterialSelect();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [pictogram, setPictogram] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<{ id: number; code: string } | null>(null);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    pictogram: pictogram ?? undefined,
  };
  const query = useQuery({
    queryKey: ["hse", "material-hazards", params],
    queryFn: () => listMaterialHazards(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const rows = (query.data?.results ?? []).map((row) => ({ ...row, id: row.material }));
  const columns = [
    {
      header: hs.material,
      render: (r: MaterialHazard) => `${r.material_code} - ${r.material_name}`,
    },
    {
      header: hs.pictograms,
      render: (r: MaterialHazard) => <PictogramBadges codes={r.pictograms} />,
    },
    {
      header: hs.signalWordLabel,
      render: (r: MaterialHazard) => <SignalWordBadge word={r.signal_word} />,
    },
    {
      header: hs.statements,
      render: (r: MaterialHazard) => (
        <Text size="sm" lineClamp={2}>
          {r.statement_rows.map((row) => row.code).join(", ")}
        </Text>
      ),
    },
  ];
  return (
    <Stack>
      <Text size="sm" c="dimmed" maw={720}>
        {hs.hazardIntro}
      </Text>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={hs.searchHazards}
            placeholder={hs.searchHazards}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={260}
            onChange={(event) => {
              setSearch(event.currentTarget.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={hs.pictograms}
            placeholder={hs.allPictograms}
            clearable
            data={HAZARD_CLASSES.map((value) => ({
              value,
              label: `${value} ${hs.hazardClass[value]}`,
            }))}
            value={pictogram}
            w={260}
            onChange={(value) => {
              setPictogram(value);
              setPage(1);
            }}
          />
        </Group>
        {hasAnyRole(user, HAZARD_ROLES) && (
          <Select
            aria-label={hs.selectMaterial}
            placeholder={hs.selectMaterial}
            searchable
            data={materials}
            value={null}
            w={280}
            onChange={(value) => {
              const row = materials.find((item) => item.value === value);
              if (row) setOpen({ id: Number(row.value), code: row.label.split(" - ")[0] });
            }}
            nothingFoundMessage={hs.notFound}
          />
        )}
      </Group>
      <RowsTable
        testId="hse-hazards"
        columns={columns}
        rows={rows}
        loading={query.isLoading}
        error={query.error}
        onOpen={(row) => setOpen({ id: row.material, code: row.material_code })}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      {open && (
        <MaterialHazardModal materialId={open.id} title={open.code} onClose={() => setOpen(null)} />
      )}
    </Stack>
  );
}

// --- H/P ifadeleri ---

const STATEMENT_KINDS: StatementKind[] = ["H", "P", "EUH"];

function StatementModal({
  statement,
  onClose,
}: {
  statement: HazardStatement | null;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState({
    code: statement?.code ?? "",
    kind: (statement?.kind ?? "H") as StatementKind,
    text: statement?.text ?? "",
  });
  const { mutation, error } = useSave(
    () =>
      statement
        ? updateStatement(statement.id, draft.text.trim())
        : createStatement({ code: draft.code.trim(), kind: draft.kind, text: draft.text.trim() }),
    hs.statementSaved,
    onClose,
  );
  return (
    <FormModal
      title={statement ? hs.editStatement : hs.newStatement}
      error={error}
      ready={draft.code.trim() !== "" && draft.text.trim() !== ""}
      pending={mutation.isPending}
      onSave={() => mutation.mutate(undefined)}
      onClose={onClose}
    >
      <SimpleGrid cols={2}>
        <TextInput
          label={hs.code}
          withAsterisk
          disabled={statement !== null}
          value={draft.code}
          onChange={(event) => setDraft({ ...draft, code: event.currentTarget.value })}
        />
        <Select
          label={hs.kind}
          withAsterisk
          allowDeselect={false}
          disabled={statement !== null}
          data={STATEMENT_KINDS.map((value) => ({ value, label: hs.statementKind[value] }))}
          value={draft.kind}
          onChange={(value) => setDraft({ ...draft, kind: (value ?? "H") as StatementKind })}
        />
      </SimpleGrid>
      <Textarea
        label={hs.text}
        withAsterisk
        autosize
        minRows={2}
        value={draft.text}
        onChange={(event) => setDraft({ ...draft, text: event.currentTarget.value })}
      />
    </FormModal>
  );
}

function StatementsTab() {
  const { user } = useAuth();
  const writer = hasAnyRole(user, HAZARD_ROLES);
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const [kind, setKind] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<HazardStatement | "new" | null>(null);
  const params = {
    page_size: 500,
    search: debounced || undefined,
    kind: kind ?? undefined,
    is_active: showInactive ? undefined : true,
  };
  const query = useQuery({
    queryKey: ["hse", "statements", params],
    queryFn: () => listStatements(params),
    placeholderData: keepPreviousData,
  });
  const toggle = useToggle(setStatementActive);
  const rows = query.data?.results ?? [];
  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <TextInput
            aria-label={hs.searchStatements}
            placeholder={hs.searchStatements}
            leftSection={<IconSearch size={16} />}
            value={search}
            w={260}
            onChange={(event) => setSearch(event.currentTarget.value)}
          />
          <Select
            aria-label={hs.kind}
            placeholder={hs.allKinds}
            clearable
            data={STATEMENT_KINDS.map((value) => ({ value, label: hs.statementKind[value] }))}
            value={kind}
            w={200}
            onChange={setKind}
          />
          <Switch
            label={hs.showInactive}
            checked={showInactive}
            onChange={(event) => setShowInactive(event.currentTarget.checked)}
          />
        </Group>
        {writer && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            {hs.newStatement}
          </Button>
        )}
      </Group>
      <ErrorAlert error={query.error} />
      <Table.ScrollContainer minWidth={640}>
        <Table striped fz="sm" data-testid="hse-statements">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{hs.code}</Table.Th>
              <Table.Th>{hs.kind}</Table.Th>
              <Table.Th>{hs.text}</Table.Th>
              <Table.Th>{hs.statusLabel}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td fw={600}>{row.code}</Table.Td>
                <Table.Td>{row.kind_display}</Table.Td>
                <Table.Td>{row.text}</Table.Td>
                <Table.Td>
                  <ActiveBadge active={row.is_active} />
                </Table.Td>
                <Table.Td>
                  {writer && (
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => setEditing(row)}>
                        {hs.edit}
                      </Button>
                      <ToggleButton row={row} toggle={toggle} />
                    </Group>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
            {!query.isLoading && rows.length === 0 && <EmptyRow colSpan={5} />}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {editing && (
        <StatementModal
          statement={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}

// --- depolama limitleri ---

function StorageLimitModal({
  limit,
  onClose,
}: {
  limit: StorageLimit | null;
  onClose: () => void;
}) {
  const locations = useLocations();
  const [draft, setDraft] = useState({
    location: limit ? String(limit.location) : (null as string | null),
    hazard_class: (limit?.hazard_class ?? null) as string | null,
    max_kg: limit ? trimDecimal(limit.max_kg) : "",
    note: limit?.note ?? "",
  });
  const { mutation, error } = useSave(
    () =>
      saveStorageLimit(limit?.id ?? null, {
        location: idOrNull(draft.location)!,
        hazard_class: draft.hazard_class as HazardClass,
        max_kg: normalizeDecimal(draft.max_kg),
        note: draft.note.trim(),
      }),
    hs.limitSaved,
    onClose,
  );
  return (
    <FormModal
      title={limit ? hs.editLimit : hs.newLimit}
      error={error}
      ready={Boolean(draft.location && draft.hazard_class && draft.max_kg.trim())}
      pending={mutation.isPending}
      onSave={() => mutation.mutate(undefined)}
      onClose={onClose}
    >
      <Select
        label={hs.location}
        withAsterisk
        searchable
        data={locations.data ?? []}
        value={draft.location}
        onChange={(value) => setDraft({ ...draft, location: value })}
        nothingFoundMessage={hs.notFound}
      />
      <Select
        label={hs.hazardClassLabel}
        withAsterisk
        data={HAZARD_CLASSES.map((value) => ({
          value,
          label: `${value} ${hs.hazardClass[value]}`,
        }))}
        value={draft.hazard_class}
        onChange={(value) => setDraft({ ...draft, hazard_class: value })}
      />
      <TextInput
        label={hs.maxKg}
        withAsterisk
        inputMode="decimal"
        value={draft.max_kg}
        onChange={(event) => setDraft({ ...draft, max_kg: event.currentTarget.value })}
      />
      <Textarea
        label={hs.note}
        autosize
        minRows={2}
        value={draft.note}
        onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
      />
    </FormModal>
  );
}

function StorageTab() {
  const { user } = useAuth();
  const writer = hasAnyRole(user, HSE_ROLES);
  const locations = useLocations();
  const [location, setLocation] = useState<string | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<StorageLimit | "new" | null>(null);
  const utilisation = useQuery({
    queryKey: ["hse", "storage-utilisation", location],
    queryFn: () => getStorageUtilisation(idOrNull(location) ?? undefined),
  });
  const limitParams = {
    page_size: 500,
    location: location ?? undefined,
    is_active: showInactive ? undefined : true,
  };
  const limits = useQuery({
    queryKey: ["hse", "storage-limits", limitParams],
    queryFn: () => listStorageLimits(limitParams),
  });
  const toggle = useToggle(setStorageLimitActive);
  const usage = utilisation.data ?? [];
  const rows = limits.data?.results ?? [];
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={720}>
          {hs.utilisationIntro}
        </Text>
        <Select
          aria-label={hs.location}
          placeholder={hs.allLocations}
          searchable
          clearable
          data={locations.data ?? []}
          value={location}
          w={260}
          onChange={setLocation}
        />
      </Group>
      <Paper withBorder p="md" radius="md">
        <Stack>
          <Title order={4}>{hs.utilisation}</Title>
          <ErrorAlert error={utilisation.error} />
          {usage.map((row) => (
            <UtilisationBar key={row.limit_id} row={row} />
          ))}
          {!utilisation.isLoading && usage.length === 0 && (
            <Text size="sm" c="dimmed">
              {hs.noLimits}
            </Text>
          )}
        </Stack>
      </Paper>
      <Group justify="space-between">
        <Group>
          <Title order={4}>{hs.limits}</Title>
          <Switch
            label={hs.showInactive}
            checked={showInactive}
            onChange={(event) => setShowInactive(event.currentTarget.checked)}
          />
        </Group>
        {writer && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing("new")}>
            {hs.newLimit}
          </Button>
        )}
      </Group>
      <ErrorAlert error={limits.error} />
      <Table.ScrollContainer minWidth={640}>
        <Table striped fz="sm" data-testid="hse-storage-limits">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{hs.location}</Table.Th>
              <Table.Th>{hs.hazardClassLabel}</Table.Th>
              <Table.Th ta="right">{hs.maxKg}</Table.Th>
              <Table.Th>{hs.note}</Table.Th>
              <Table.Th>{hs.statusLabel}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td>{`${row.location_code} - ${row.location_name}`}</Table.Td>
                <Table.Td>{`${row.hazard_class} ${row.hazard_class_display}`}</Table.Td>
                <Table.Td ta="right">{formatNumber(row.max_kg)}</Table.Td>
                <Table.Td>{row.note}</Table.Td>
                <Table.Td>
                  <ActiveBadge active={row.is_active} />
                </Table.Td>
                <Table.Td>
                  {writer && (
                    <Group gap={4} wrap="nowrap">
                      <Button size="compact-xs" variant="light" onClick={() => setEditing(row)}>
                        {hs.edit}
                      </Button>
                      <ToggleButton row={row} toggle={toggle} />
                    </Group>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
            {!limits.isLoading && rows.length === 0 && <EmptyRow colSpan={6} />}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {editing && (
        <StorageLimitModal
          limit={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}

// --- atık ---

function WasteRecordModal({ onClose }: { onClose: () => void }) {
  const contractors = useQuery({
    queryKey: ["hse", "contractors", "options"],
    queryFn: () => listContractors({ is_active: true, page_size: 500 }),
  });
  const [draft, setDraft] = useState({
    waste_code: "",
    description: "",
    is_hazardous: false,
    quantity_kg: "",
    contractor: null as string | null,
    delivered_on: today(),
    document_no: "",
    note: "",
  });
  const { mutation, error } = useSave(
    () =>
      createWasteRecord({
        waste_code: draft.waste_code.trim(),
        description: draft.description.trim(),
        is_hazardous: draft.is_hazardous,
        quantity_kg: normalizeDecimal(draft.quantity_kg),
        contractor: idOrNull(draft.contractor)!,
        delivered_on: draft.delivered_on,
        document_no: draft.document_no.trim(),
        note: draft.note.trim(),
      }),
    (record) => hs.wasteSaved(record.number),
    onClose,
  );
  const ready =
    draft.waste_code.trim() !== "" &&
    draft.description.trim() !== "" &&
    draft.quantity_kg.trim() !== "" &&
    Boolean(draft.contractor) &&
    draft.delivered_on !== "";
  return (
    <FormModal
      title={hs.newWaste}
      size="lg"
      error={error}
      ready={ready}
      pending={mutation.isPending}
      onSave={() => mutation.mutate(undefined)}
      onClose={onClose}
    >
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TextInput
          label={hs.wasteCode}
          description={hs.wasteCodeHint}
          withAsterisk
          value={draft.waste_code}
          onChange={(event) => setDraft({ ...draft, waste_code: event.currentTarget.value })}
        />
        <TextInput
          label={hs.wasteDescription}
          withAsterisk
          value={draft.description}
          onChange={(event) => setDraft({ ...draft, description: event.currentTarget.value })}
        />
        <TextInput
          label={hs.quantityKg}
          withAsterisk
          inputMode="decimal"
          value={draft.quantity_kg}
          onChange={(event) => setDraft({ ...draft, quantity_kg: event.currentTarget.value })}
        />
        <TextInput
          label={hs.deliveredOn}
          withAsterisk
          type="date"
          value={draft.delivered_on}
          onChange={(event) => setDraft({ ...draft, delivered_on: event.currentTarget.value })}
        />
        <Select
          label={hs.contractor}
          withAsterisk
          searchable
          data={(contractors.data?.results ?? []).map((row) => ({
            value: String(row.id),
            label: row.license_expired ? `${row.name} (${hs.licenseExpired})` : row.name,
            disabled: row.license_expired,
          }))}
          value={draft.contractor}
          onChange={(value) => setDraft({ ...draft, contractor: value })}
          nothingFoundMessage={hs.notFound}
        />
        <TextInput
          label={hs.documentNo}
          value={draft.document_no}
          onChange={(event) => setDraft({ ...draft, document_no: event.currentTarget.value })}
        />
      </SimpleGrid>
      <Checkbox
        label={hs.hazardousWaste}
        checked={draft.is_hazardous}
        onChange={(event) => setDraft({ ...draft, is_hazardous: event.currentTarget.checked })}
      />
      <Textarea
        label={hs.note}
        autosize
        minRows={2}
        value={draft.note}
        onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
      />
    </FormModal>
  );
}

function WasteDetailModal({ record, onClose }: { record: WasteRecord; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [cancelling, setCancelling] = useState(false);
  return (
    <Modal opened onClose={onClose} title={`${record.number} · ${record.waste_code}`} size="lg">
      <Stack>
        <SimpleGrid cols={{ base: 1, xs: 2 }}>
          <Info label={hs.wasteDescription}>
            <Text size="sm">{record.description}</Text>
          </Info>
          <Info label={hs.quantityKg}>
            <Text size="sm">{formatNumber(record.quantity_kg)}</Text>
          </Info>
          <Info label={hs.contractor}>
            <Text size="sm">{`${record.contractor_name} (${record.contractor_license_no})`}</Text>
          </Info>
          <Info label={hs.deliveredOn}>
            <Text size="sm">{formatDate(record.delivered_on)}</Text>
          </Info>
          <Info label={hs.documentNo}>
            <Text size="sm">{record.document_no}</Text>
          </Info>
          <Info label={hs.statusLabel}>
            <Badge color={record.status === "CANCELLED" ? "gray" : "green"} variant="light">
              {record.status_display}
            </Badge>
          </Info>
          {record.status === "CANCELLED" && (
            <Info label={hs.cancelReason}>
              <Text size="sm">{record.cancel_reason}</Text>
            </Info>
          )}
        </SimpleGrid>
        {record.note && <Text size="sm">{record.note}</Text>}
        <AttachmentPanel
          contentType={WASTE_CONTENT_TYPE}
          objectId={record.id}
          defaultKind="DOCUMENT"
        />
        <Group justify="flex-end">
          {record.status === "RECORDED" && (
            <Button color="red" variant="light" onClick={() => setCancelling(true)}>
              {hs.cancelWaste}
            </Button>
          )}
          <Button variant="default" onClick={onClose}>
            {hs.close}
          </Button>
        </Group>
      </Stack>
      <CancelModal
        opened={cancelling}
        cancel={(reason) => cancelWasteRecord(record.id, reason)}
        onClose={() => setCancelling(false)}
        onDone={() => {
          setCancelling(false);
          void queryClient.invalidateQueries({ queryKey: ["hse"] });
          onClose();
        }}
      />
    </Modal>
  );
}

function ContractorModal({
  contractor,
  onClose,
}: {
  contractor: WasteContractor | null;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState({
    name: contractor?.name ?? "",
    license_no: contractor?.license_no ?? "",
    license_valid_until: contractor?.license_valid_until ?? "",
    phone: contractor?.phone ?? "",
    note: contractor?.note ?? "",
  });
  const { mutation, error } = useSave(
    () =>
      saveContractor(contractor?.id ?? null, {
        name: draft.name.trim(),
        license_no: draft.license_no.trim(),
        license_valid_until: draft.license_valid_until,
        phone: draft.phone.trim(),
        note: draft.note.trim(),
      }),
    hs.contractorSaved,
    onClose,
  );
  return (
    <FormModal
      title={contractor ? hs.editContractor : hs.newContractor}
      error={error}
      ready={Boolean(draft.name.trim() && draft.license_no.trim() && draft.license_valid_until)}
      pending={mutation.isPending}
      onSave={() => mutation.mutate(undefined)}
      onClose={onClose}
    >
      <TextInput
        label={hs.name}
        withAsterisk
        value={draft.name}
        onChange={(event) => setDraft({ ...draft, name: event.currentTarget.value })}
      />
      <SimpleGrid cols={2}>
        <TextInput
          label={hs.licenseNo}
          withAsterisk
          value={draft.license_no}
          onChange={(event) => setDraft({ ...draft, license_no: event.currentTarget.value })}
        />
        <TextInput
          label={hs.licenseValidUntil}
          withAsterisk
          type="date"
          value={draft.license_valid_until}
          onChange={(event) =>
            setDraft({ ...draft, license_valid_until: event.currentTarget.value })
          }
        />
      </SimpleGrid>
      <TextInput
        label={hs.phone}
        value={draft.phone}
        onChange={(event) => setDraft({ ...draft, phone: event.currentTarget.value })}
      />
      <Textarea
        label={hs.note}
        autosize
        minRows={2}
        value={draft.note}
        onChange={(event) => setDraft({ ...draft, note: event.currentTarget.value })}
      />
    </FormModal>
  );
}

function ContractorsSection() {
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<WasteContractor | "new" | null>(null);
  const params = { page_size: 500, is_active: showInactive ? undefined : true };
  const query = useQuery({
    queryKey: ["hse", "contractors", params],
    queryFn: () => listContractors(params),
  });
  const toggle = useToggle(setContractorActive);
  const rows = query.data?.results ?? [];
  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Title order={4}>{hs.contractors}</Title>
          <Switch
            label={hs.showInactive}
            checked={showInactive}
            onChange={(event) => setShowInactive(event.currentTarget.checked)}
          />
        </Group>
        <Button
          variant="light"
          leftSection={<IconPlus size={16} />}
          onClick={() => setEditing("new")}
        >
          {hs.newContractor}
        </Button>
      </Group>
      <ErrorAlert error={query.error} />
      <Table.ScrollContainer minWidth={640}>
        <Table striped fz="sm" data-testid="hse-contractors">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{hs.name}</Table.Th>
              <Table.Th>{hs.licenseNo}</Table.Th>
              <Table.Th>{hs.licenseValidUntil}</Table.Th>
              <Table.Th>{hs.phone}</Table.Th>
              <Table.Th>{hs.statusLabel}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td>{row.name}</Table.Td>
                <Table.Td>{row.license_no}</Table.Td>
                <Table.Td>
                  <Text
                    span
                    size="sm"
                    c={row.license_expired ? "red" : undefined}
                    fw={row.license_expired ? 600 : undefined}
                  >
                    {formatDate(row.license_valid_until)}
                    {row.license_expired ? ` · ${hs.licenseExpired}` : ""}
                  </Text>
                </Table.Td>
                <Table.Td>{row.phone}</Table.Td>
                <Table.Td>
                  <ActiveBadge active={row.is_active} />
                </Table.Td>
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <Button size="compact-xs" variant="light" onClick={() => setEditing(row)}>
                      {hs.edit}
                    </Button>
                    <ToggleButton row={row} toggle={toggle} />
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
            {!query.isLoading && rows.length === 0 && <EmptyRow colSpan={6} />}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {editing && (
        <ContractorModal
          contractor={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}

function WasteTab() {
  const contractors = useQuery({
    queryKey: ["hse", "contractors", "options"],
    queryFn: () => listContractors({ page_size: 500 }),
  });
  const [contractor, setContractor] = useState<string | null>(null);
  const [onlyHazardous, setOnlyHazardous] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<WasteRecord | null>(null);
  const params = {
    page,
    page_size: PAGE_SIZE,
    contractor: contractor ?? undefined,
    is_hazardous: onlyHazardous ? true : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  };
  const query = useQuery({
    queryKey: ["hse", "waste-records", params],
    queryFn: () => listWasteRecords(params),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  const columns = [
    { header: hs.number, render: (r: WasteRecord) => r.number },
    { header: hs.deliveredOn, render: (r: WasteRecord) => formatDate(r.delivered_on) },
    {
      header: hs.wasteCode,
      render: (r: WasteRecord) => (
        <WithHazard hazardous={r.is_hazardous}>{r.waste_code}</WithHazard>
      ),
    },
    { header: hs.wasteDescription, render: (r: WasteRecord) => r.description },
    {
      header: hs.quantityKg,
      align: "right" as const,
      render: (r: WasteRecord) => formatNumber(r.quantity_kg),
    },
    { header: hs.contractor, render: (r: WasteRecord) => r.contractor_name },
    { header: hs.documentNo, render: (r: WasteRecord) => r.document_no },
    {
      header: hs.statusLabel,
      render: (r: WasteRecord) => (
        <Badge color={r.status === "CANCELLED" ? "gray" : "green"} variant="light">
          {r.status_display}
        </Badge>
      ),
    },
  ];
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={4}>{hs.wasteRecords}</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          {hs.newWaste}
        </Button>
      </Group>
      <Group align="flex-end">
        <Select
          label={hs.contractor}
          placeholder={hs.allContractors}
          clearable
          data={(contractors.data?.results ?? []).map((row) => ({
            value: String(row.id),
            label: row.name,
          }))}
          value={contractor}
          w={240}
          onChange={(value) => {
            setContractor(value);
            setPage(1);
          }}
        />
        <TextInput
          label={hs.dateFrom}
          type="date"
          value={dateFrom}
          onChange={(event) => {
            setDateFrom(event.currentTarget.value);
            setPage(1);
          }}
        />
        <TextInput
          label={hs.dateTo}
          type="date"
          value={dateTo}
          onChange={(event) => {
            setDateTo(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Switch
          label={hs.hazardousWaste}
          checked={onlyHazardous}
          mb={8}
          onChange={(event) => {
            setOnlyHazardous(event.currentTarget.checked);
            setPage(1);
          }}
        />
      </Group>
      <RowsTable
        testId="hse-waste"
        columns={columns}
        rows={query.data?.results ?? []}
        loading={query.isLoading}
        error={query.error}
        onOpen={setOpen}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      <ContractorsSection />
      {creating && <WasteRecordModal onClose={() => setCreating(false)} />}
      {open && <WasteDetailModal record={open} onClose={() => setOpen(null)} />}
    </Stack>
  );
}

// --- özet ---

function CountTable({ title, rows }: { title: string; rows: { label: string; count: number }[] }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Title order={5} mb="xs">
        {title}
      </Title>
      <Table fz="sm">
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.label}>
              <Table.Td>{row.label}</Table.Td>
              <Table.Td ta="right">{row.count}</Table.Td>
            </Table.Tr>
          ))}
          {rows.length === 0 && <EmptyRow colSpan={2} />}
        </Table.Tbody>
      </Table>
    </Paper>
  );
}

function SummaryTab() {
  const [dateFrom, setDateFrom] = useState(daysAgo(30));
  const [dateTo, setDateTo] = useState(today());
  const query = useQuery({
    queryKey: ["hse", "summary", dateFrom, dateTo],
    queryFn: () => getHseSummary({ date_from: dateFrom, date_to: dateTo }),
  });
  const data = query.data;
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {hs.summaryIntro}
      </Text>
      <Group>
        <TextInput
          label={hs.dateFrom}
          type="date"
          value={dateFrom}
          onChange={(event) => setDateFrom(event.currentTarget.value)}
        />
        <TextInput
          label={hs.dateTo}
          type="date"
          value={dateTo}
          onChange={(event) => setDateTo(event.currentTarget.value)}
        />
      </Group>
      <ErrorAlert error={query.error} />
      {data && (
        <>
          <SimpleGrid cols={{ base: 1, sm: 3 }}>
            {(
              [
                [hs.totalIncidents, data.incidents.total],
                [hs.injuryCount, data.incidents.injury_count],
                [hs.openCount, data.incidents.open_count],
              ] as const
            ).map(([label, value]) => (
              <Paper key={label} withBorder p="md" radius="md">
                <Text size="xs" c="dimmed">
                  {label}
                </Text>
                <Text fz={28} fw={700}>
                  {value}
                </Text>
              </Paper>
            ))}
          </SimpleGrid>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <CountTable title={hs.byType} rows={data.incidents.by_type} />
            <CountTable title={hs.bySeverity} rows={data.incidents.by_severity} />
          </SimpleGrid>
          <Paper withBorder p="md" radius="md">
            <Title order={5} mb="xs">
              {hs.wasteSummary}
            </Title>
            <Table fz="sm" data-testid="hse-waste-summary">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{hs.wasteCode}</Table.Th>
                  <Table.Th>{hs.wasteDescription}</Table.Th>
                  <Table.Th ta="right">{hs.count}</Table.Th>
                  <Table.Th ta="right">{hs.quantityKg}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.waste.map((row) => (
                  <Table.Tr key={`${row.waste_code}-${row.description}`}>
                    <Table.Td>
                      <WithHazard hazardous={row.is_hazardous}>{row.waste_code}</WithHazard>
                    </Table.Td>
                    <Table.Td>{row.description}</Table.Td>
                    <Table.Td ta="right">{row.count}</Table.Td>
                    <Table.Td ta="right">{formatNumber(row.quantity_kg)}</Table.Td>
                  </Table.Tr>
                ))}
                {data.waste.length === 0 && <EmptyRow colSpan={4} text={hs.noWaste} />}
              </Table.Tbody>
            </Table>
          </Paper>
        </>
      )}
    </Stack>
  );
}

// --- ayarlar ---

function SettingsForm({
  initial,
  onSaved,
}: {
  initial: HseSettings;
  onSaved: (saved: HseSettings) => void;
}) {
  const [months, setMonths] = useState(String(initial.sds_max_age_months));
  const valid = /^\d+$/.test(months.trim()) && Number(months) > 0;
  const { mutation, error } = useSave(
    () => saveHseSettings({ sds_max_age_months: Number(months) }),
    hs.settingsSaved,
    onSaved,
  );
  return (
    <Paper withBorder p="md" radius="md" maw={520}>
      <Stack>
        <TextInput
          label={hs.sdsMaxAge}
          description={hs.sdsMaxAgeHint}
          inputMode="numeric"
          value={months}
          onChange={(event) => setMonths(event.currentTarget.value)}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button
            disabled={!valid}
            loading={mutation.isPending}
            onClick={() => mutation.mutate(undefined)}
          >
            {hs.save}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function SettingsTab() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["hse", "settings"], queryFn: getHseSettings });
  if (query.isLoading) return null;
  if (query.error || !query.data) return <ErrorAlert error={query.error} />;
  return (
    <SettingsForm
      initial={query.data}
      onSaved={(saved) => queryClient.setQueryData(["hse", "settings"], saved)}
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
    slug: "olaylar",
    label: hs.tabs.incidents,
    roles: INCIDENT_ROLES,
    render: () => <IncidentsTab />,
  },
  { slug: "gbf", label: hs.tabs.sds, roles: SDS_READ_ROLES, render: () => <SdsTab /> },
  { slug: "tehlike", label: hs.tabs.hazards, roles: [], render: () => <HazardsTab /> },
  { slug: "ifadeler", label: hs.tabs.statements, roles: [], render: () => <StatementsTab /> },
  {
    slug: "depolama",
    label: hs.tabs.storage,
    roles: STORAGE_READ_ROLES,
    render: () => <StorageTab />,
  },
  { slug: "atik", label: hs.tabs.waste, roles: HSE_ROLES, render: () => <WasteTab /> },
  { slug: "ozet", label: hs.tabs.summary, roles: HSE_ROLES, render: () => <SummaryTab /> },
  { slug: "ayarlar", label: hs.tabs.settings, roles: HSE_ROLES, render: () => <SettingsTab /> },
];

/** İSG: sekmeler (`/isg/<sekme>`). Olay bildirimi her rolde açıktır. */
export function HsePage() {
  const { tab } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const visible = TABS.filter((item) => hasAnyRole(user, item.roles));
  const current = tab ? visible.find((item) => item.slug === tab) : visible[0];
  if (!current) return <Navigate to={HSE_BASE} replace />;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{hs.title}</Title>
        <IncidentReportButton onSaved={(incident) => navigate(incidentPath(incident.id))} />
      </Group>
      <Tabs value={current.slug} onChange={(value) => value && navigate(`${HSE_BASE}/${value}`)}>
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
