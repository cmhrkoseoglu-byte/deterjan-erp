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
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconFileSpreadsheet, IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createRate,
  getReport,
  listLotCosts,
  listRates,
  listStandardCosts,
  reportExcelUrl,
  saveStandardCost,
  setStandardCostActive,
  type BatchVarianceRow,
  type CostRate,
  type CostStage,
  type CostTrendRow,
  type RateKind,
  type ReportName,
  type ScrapCostRow,
  type StandardCost,
  type StockValue,
  type TopMaterialRow,
} from "../../api/costing";
import type { MaterialType } from "../../api/masterdata";
import { formatDate, formatMoney, formatNumber } from "../../i18n/format";
import { ActiveBadge } from "../common/ActiveBadge";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { today } from "../inventory/config";
import { Qty } from "../inventory/shared";
import { COSTING_BASE, lotCostPath } from "./config";
import { CostFlags } from "./CostFlags";
import { PersonnelCostPanel } from "./PersonnelCostPanel";
import { ErrorAlert, ReportTable } from "./ReportTable";
import { kt } from "./strings";
import { WagesPanel } from "./WagesPanel";

const TABS = {
  lots: "lotlar",
  reports: "raporlar",
  rates: "oranlar",
  standard: "standart",
  personnel: "personel",
  wages: "ucretler",
} as const;
type TabKey = keyof typeof TABS;
const PAGE_SIZE = 50;

function tabFromPath(value: string | undefined): TabKey {
  return (Object.keys(TABS) as TabKey[]).find((key) => TABS[key] === value) ?? "lots";
}

/** Maliyet (yalnızca yönetim ve admin): lot maliyetleri, raporlar, gider oranları, standart
 * maliyetler, personel maliyeti ve ücretleri. */
export function CostingPage() {
  const tab = tabFromPath(useParams().tab);
  const navigate = useNavigate();
  return (
    <Stack>
      <Title order={2}>{kt.title}</Title>
      <Tabs
        value={tab}
        onChange={(value) => value && navigate(`${COSTING_BASE}/${TABS[value as TabKey]}`)}
      >
        <Tabs.List>
          {(Object.keys(TABS) as TabKey[]).map((key) => (
            <Tabs.Tab key={key} value={key}>
              {kt.tabs[key]}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      {tab === "lots" && <LotCostsPanel />}
      {tab === "reports" && <ReportsPanel />}
      {tab === "rates" && <RatesPanel />}
      {tab === "standard" && <StandardCostsPanel />}
      {tab === "personnel" && <PersonnelCostPanel />}
      {tab === "wages" && <WagesPanel />}
    </Stack>
  );
}

// --- lot maliyetleri ------------------------------------------------------------------------

const METHOD_OPTIONS = (["PURCHASE", "PRODUCTION", "FILLING", "ESTIMATE"] as const).map(
  (value) => ({ value, label: kt.method_[value] }),
);

function LotCostsPanel() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [method, setMethod] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);
  const [page, setPage] = useState(1);
  const [debounced] = useDebouncedValue(search, 300);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    method: method ?? undefined,
    is_estimated: estimated ? "true" : undefined,
  };
  const query = useQuery({
    queryKey: ["costing", "lot-costs", params],
    queryFn: () => listLotCosts(params),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  return (
    <Stack>
      <Group>
        <TextInput
          placeholder={kt.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Select
          placeholder={kt.allMethods}
          clearable
          data={METHOD_OPTIONS}
          value={method}
          onChange={(value) => {
            setMethod(value);
            setPage(1);
          }}
        />
        <Checkbox
          label={kt.estimatedOnly}
          checked={estimated}
          onChange={(event) => {
            setEstimated(event.currentTarget.checked);
            setPage(1);
          }}
        />
      </Group>
      {query.isError && <ErrorAlert error={query.error} />}
      <Table.ScrollContainer minWidth={760}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{kt.lotNo}</Table.Th>
              <Table.Th>{kt.material}</Table.Th>
              <Table.Th>{kt.method}</Table.Th>
              <Table.Th>{kt.date}</Table.Th>
              <Table.Th ta="right">{kt.quantity}</Table.Th>
              <Table.Th ta="right">{kt.totalCost}</Table.Th>
              <Table.Th ta="right">{kt.unitCost}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(lotCostPath(row.lot))}
              >
                <Table.Td fw={600}>{row.lot_no}</Table.Td>
                <Table.Td>
                  {row.material_code} — {row.material_name}
                </Table.Td>
                <Table.Td>{kt.method_[row.method]}</Table.Td>
                <Table.Td>{formatDate(row.cost_date)}</Table.Td>
                <Table.Td ta="right">
                  <Qty value={row.quantity} unit={row.unit} />
                </Table.Td>
                <Table.Td ta="right">{formatMoney(row.total_cost)}</Table.Td>
                <Table.Td ta="right">{formatNumber(row.unit_cost)}</Table.Td>
                <Table.Td>
                  <CostFlags estimated={row.is_estimated} missing={row.has_missing} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {ct.empty}
        </Text>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

// --- raporlar ------------------------------------------------------------------------------

const REPORTS: ReportName[] = [
  "stock-value",
  "cost-trend",
  "batch-variance",
  "scrap-cost",
  "top-materials",
];
const TYPE_OPTIONS = (["RAW", "PACKAGING", "BULK", "FINISHED"] as const).map((value) => ({
  value,
  label: kt.materialType_[value],
}));

const money = (value: string | null) => formatMoney(value);
const lotLink = (lotId: number, lotNo: string) => <Link to={lotCostPath(lotId)}>{lotNo}</Link>;

function ReportsPanel() {
  const [report, setReport] = useState<ReportName>("stock-value");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [materialType, setMaterialType] = useState<string | null>(null);
  const dated = report !== "stock-value";
  const params = {
    date_from: dated ? dateFrom || undefined : undefined,
    date_to: dated ? dateTo || undefined : undefined,
    material_type:
      report === "stock-value" || report === "top-materials"
        ? (materialType ?? undefined)
        : undefined,
  };
  const query = useQuery({
    queryKey: ["costing", "report", report, params],
    queryFn: () => getReport<unknown>(report, params),
  });
  const typeOptions =
    report === "top-materials"
      ? TYPE_OPTIONS.filter((o) => o.value === "RAW" || o.value === "PACKAGING")
      : TYPE_OPTIONS;
  return (
    <Stack>
      <Group align="flex-end">
        <Select
          label={kt.report}
          data={REPORTS.map((value) => ({ value, label: kt.report_[value] }))}
          value={report}
          allowDeselect={false}
          onChange={(value) => {
            setReport(value as ReportName);
            setMaterialType(null);
          }}
          w={260}
        />
        {dated && (
          <>
            <TextInput
              label={kt.dateFrom}
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.currentTarget.value)}
            />
            <TextInput
              label={kt.dateTo}
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.currentTarget.value)}
            />
          </>
        )}
        {(report === "stock-value" || report === "top-materials") && (
          <Select
            label={kt.materialType}
            clearable
            data={typeOptions}
            value={materialType}
            onChange={setMaterialType}
          />
        )}
        <Button
          component="a"
          href={reportExcelUrl(report, params)}
          variant="default"
          leftSection={<IconFileSpreadsheet size={16} />}
        >
          {kt.excel}
        </Button>
      </Group>
      {query.isError && <ErrorAlert error={query.error} />}
      {query.data !== undefined && <ReportBody report={report} data={query.data} />}
    </Stack>
  );
}

function ReportBody({ report, data }: { report: ReportName; data: unknown }) {
  switch (report) {
    case "stock-value": {
      const value = data as StockValue;
      return (
        <Stack>
          <SimpleGrid cols={{ base: 2, sm: 5 }}>
            <Paper withBorder p="sm" radius="md">
              <Text size="xs" c="dimmed">
                {kt.totalValue}
              </Text>
              <Text fw={700}>{formatMoney(value.total_value, "TL")}</Text>
            </Paper>
            {value.by_type.map((row) => (
              <Paper key={row.material_type} withBorder p="sm" radius="md">
                <Text size="xs" c="dimmed">
                  {kt.materialType_[row.material_type]}
                </Text>
                <Text fw={600}>{formatMoney(row.value, "TL")}</Text>
              </Paper>
            ))}
          </SimpleGrid>
          <ReportTable
            rows={value.rows}
            rowKey={(row) => String(row.material_id)}
            cells={[
              { label: kt.material, render: (r) => `${r.material_code} — ${r.material_name}` },
              {
                label: kt.materialType,
                render: (r) => kt.materialType_[r.material_type as MaterialType],
              },
              {
                label: kt.quantity,
                right: true,
                render: (r) => <Qty value={r.quantity} unit={r.unit} />,
              },
              { label: kt.value, right: true, render: (r) => money(r.value) },
              {
                label: kt.avgUnitCost,
                right: true,
                render: (r) => formatNumber(r.average_unit_cost),
              },
              {
                label: kt.uncosted,
                right: true,
                render: (r) =>
                  Number(r.uncosted_quantity) > 0 ? (
                    <Qty value={r.uncosted_quantity} unit={r.unit} />
                  ) : (
                    ""
                  ),
              },
            ]}
          />
        </Stack>
      );
    }
    case "cost-trend":
      return (
        <ReportTable
          rows={data as CostTrendRow[]}
          rowKey={(r) => `${r.material_id}-${r.month}`}
          cells={[
            { label: kt.material, render: (r) => `${r.material_code} — ${r.material_name}` },
            { label: kt.month, render: (r) => formatDate(r.month).slice(3) },
            { label: kt.lotCount, right: true, render: (r) => r.lot_count },
            {
              label: kt.quantity,
              right: true,
              render: (r) => <Qty value={r.quantity} unit={r.unit} />,
            },
            { label: kt.totalCost, right: true, render: (r) => money(r.total_cost) },
            { label: kt.unitCost, right: true, render: (r) => formatNumber(r.unit_cost) },
            { label: "", render: (r) => <CostFlags estimated={r.has_estimated} /> },
          ]}
        />
      );
    case "batch-variance":
      return (
        <ReportTable
          rows={data as BatchVarianceRow[]}
          rowKey={(r) => String(r.lot_cost_id)}
          cells={[
            { label: kt.lotNo, render: (r) => lotLink(r.lot_id, r.lot_no) },
            { label: kt.material, render: (r) => r.product_code },
            { label: kt.date, render: (r) => formatDate(r.cost_date) },
            {
              label: kt.actual,
              right: true,
              render: (r) => <Qty value={r.actual_quantity} unit={r.unit} />,
            },
            {
              label: kt.theoretical,
              right: true,
              render: (r) => money(r.theoretical_material_cost),
            },
            { label: kt.actualMaterial, right: true, render: (r) => money(r.actual_material_cost) },
            { label: kt.overhead, right: true, render: (r) => money(r.overhead_cost) },
            {
              label: kt.theoreticalUnit,
              right: true,
              render: (r) => formatNumber(r.theoretical_unit_cost),
            },
            {
              label: kt.actualUnit,
              right: true,
              render: (r) => formatNumber(r.actual_material_unit_cost),
            },
            {
              label: kt.variance,
              right: true,
              render: (r) =>
                r.variance_pct === null ? (
                  ""
                ) : (
                  <Text span size="sm" c={Number(r.variance_pct) > 0 ? "red" : "green"}>
                    {formatNumber(r.variance_pct, 2)}
                  </Text>
                ),
            },
            { label: "", render: (r) => <CostFlags estimated={r.is_estimated} /> },
          ]}
        />
      );
    case "scrap-cost":
      return (
        <ReportTable
          rows={data as ScrapCostRow[]}
          rowKey={(r) => String(r.lot_cost_id)}
          cells={[
            { label: kt.lotNo, render: (r) => lotLink(r.lot_id, r.lot_no) },
            { label: kt.material, render: (r) => r.product_code },
            { label: kt.date, render: (r) => formatDate(r.cost_date) },
            { label: kt.goodUnits, right: true, render: (r) => formatNumber(r.good_units) },
            { label: kt.materialScrap, right: true, render: (r) => money(r.material_scrap_cost) },
            {
              label: kt.finishedScrapShort,
              right: true,
              render: (r) => money(r.finished_scrap_cost),
            },
            { label: kt.totalScrap, right: true, render: (r) => money(r.total_scrap_cost) },
            { label: kt.scrapPct, right: true, render: (r) => formatNumber(r.scrap_pct, 2) },
          ]}
        />
      );
    case "top-materials":
      return (
        <ReportTable
          rows={data as TopMaterialRow[]}
          rowKey={(r) => String(r.material_id)}
          cells={[
            { label: kt.material, render: (r) => `${r.material_code} — ${r.material_name}` },
            { label: kt.materialType, render: (r) => kt.materialType_[r.material_type] },
            {
              label: kt.consumption,
              right: true,
              render: (r) => <Qty value={r.quantity} unit={r.unit} />,
            },
            { label: kt.amount, right: true, render: (r) => money(r.amount) },
            {
              label: kt.avgUnitCost,
              right: true,
              render: (r) => formatNumber(r.average_unit_cost),
            },
            { label: kt.share, right: true, render: (r) => formatNumber(r.share_pct, 2) },
            { label: "", render: (r) => <CostFlags estimated={false} missing={r.has_missing} /> },
          ]}
        />
      );
  }
}

// --- gider oranları -------------------------------------------------------------------------

const STAGES: CostStage[] = ["PRODUCTION", "FILLING"];
const KINDS: RateKind[] = ["ENERGY", "LABOR", "DEPRECIATION"];

/** Bugün geçerli oranlar: her aşama ve türde başlangıcı bugünü geçmeyen en yeni oran. */
function activeRateIds(rates: CostRate[]): Set<number> {
  const now = today();
  const ids = new Set<number>();
  for (const stage of STAGES)
    for (const kind of KINDS) {
      const current = rates
        .filter((r) => r.stage === stage && r.kind === kind && r.valid_from <= now)
        .sort((a, b) => b.valid_from.localeCompare(a.valid_from))[0];
      if (current) ids.add(current.id);
    }
  return ids;
}

function RatesPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["costing", "rates"], queryFn: listRates });
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({
    stage: "PRODUCTION" as CostStage,
    kind: "ENERGY" as RateKind,
    rate_per_kg: "",
    valid_from: today(),
    note: "",
  });
  const save = useMutation({
    mutationFn: () => createRate({ ...draft, rate_per_kg: normalizeDecimal(draft.rate_per_kg) }),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.rateSaved });
      setOpen(false);
      setDraft((d) => ({ ...d, rate_per_kg: "", note: "" }));
      void queryClient.invalidateQueries({ queryKey: ["costing", "rates"] });
    },
  });
  const rates = query.data?.results ?? [];
  const active = activeRateIds(rates);
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={720}>
          {kt.ratesHint}
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setOpen(true)}>
          {kt.addRate}
        </Button>
      </Group>
      {query.isError && <ErrorAlert error={query.error} />}
      <ReportTable
        rows={rates}
        rowKey={(r) => String(r.id)}
        cells={[
          { label: kt.stage, render: (r) => kt.stage_[r.stage] },
          { label: kt.kind, render: (r) => kt.kind_[r.kind] },
          { label: kt.ratePerKg, right: true, render: (r) => formatNumber(r.rate_per_kg) },
          { label: kt.validFrom, render: (r) => formatDate(r.valid_from) },
          { label: kt.note, render: (r) => r.note },
          {
            label: "",
            render: (r) =>
              active.has(r.id) ? (
                <Badge color="green" variant="light" size="sm">
                  {kt.activeNow}
                </Badge>
              ) : null,
          },
        ]}
      />
      <Modal opened={open} onClose={() => setOpen(false)} title={kt.addRate}>
        <Stack>
          <Select
            label={kt.stage}
            data={STAGES.map((value) => ({ value, label: kt.stage_[value] }))}
            value={draft.stage}
            allowDeselect={false}
            onChange={(value) => setDraft((d) => ({ ...d, stage: value as CostStage }))}
          />
          <Select
            label={kt.kind}
            data={KINDS.map((value) => ({ value, label: kt.kind_[value] }))}
            value={draft.kind}
            allowDeselect={false}
            onChange={(value) => setDraft((d) => ({ ...d, kind: value as RateKind }))}
          />
          <TextInput
            label={kt.ratePerKg}
            withAsterisk
            inputMode="decimal"
            value={draft.rate_per_kg}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setDraft((d) => ({ ...d, rate_per_kg: value }));
            }}
          />
          <TextInput
            label={kt.validFrom}
            type="date"
            withAsterisk
            value={draft.valid_from}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setDraft((d) => ({ ...d, valid_from: value }));
            }}
          />
          <TextInput
            label={kt.note}
            value={draft.note}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setDraft((d) => ({ ...d, note: value }));
            }}
          />
          {save.isError && <ErrorAlert error={save.error} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpen(false)}>
              {kt.cancel}
            </Button>
            <Button
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={!draft.rate_per_kg.trim() || !draft.valid_from}
            >
              {kt.save}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

// --- standart maliyetler --------------------------------------------------------------------

function StandardCostsPanel() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["costing", "standard-costs", page],
    queryFn: () => listStandardCosts({ page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const materials = useOptions({ endpoint: "materials" });
  const [editing, setEditing] = useState<StandardCost | "new" | null>(null);
  const [draft, setDraft] = useState({ material: null as string | null, unit_cost: "", note: "" });
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: ["costing", "standard-costs"] });
  const save = useMutation({
    mutationFn: () =>
      saveStandardCost(
        {
          material: Number(draft.material),
          unit_cost: normalizeDecimal(draft.unit_cost),
          note: draft.note.trim(),
        },
        editing && editing !== "new" ? editing.id : undefined,
      ),
    onSuccess: () => {
      notifications.show({ color: "green", message: kt.standardSaved });
      setEditing(null);
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (row: StandardCost) => setStandardCostActive(row.id, !row.is_active),
    onSuccess: refresh,
  });
  const openForm = (row: StandardCost | "new") => {
    setEditing(row);
    setDraft(
      row === "new"
        ? { material: null, unit_cost: "", note: "" }
        : { material: String(row.material), unit_cost: trimDecimal(row.unit_cost), note: row.note },
    );
    save.reset();
  };
  const rows = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Text size="sm" c="dimmed" maw={720}>
          {kt.standardHint}
        </Text>
        <Button leftSection={<IconPlus size={16} />} onClick={() => openForm("new")}>
          {kt.addStandard}
        </Button>
      </Group>
      {query.isError && <ErrorAlert error={query.error} />}
      {toggle.isError && <ErrorAlert error={toggle.error} />}
      <ReportTable
        rows={rows}
        rowKey={(r) => String(r.id)}
        cells={[
          { label: kt.material, render: (r) => `${r.material_code} — ${r.material_name}` },
          {
            label: kt.unitCost,
            right: true,
            render: (r) => `${formatNumber(r.unit_cost)} / ${r.unit}`,
          },
          { label: kt.note, render: (r) => r.note },
          { label: "", render: (r) => <ActiveBadge active={r.is_active} /> },
          {
            label: " ",
            render: (r) => (
              <Group gap="xs" justify="flex-end" wrap="nowrap">
                <Button size="xs" variant="subtle" onClick={() => openForm(r)}>
                  {kt.edit}
                </Button>
                <Button size="xs" variant="subtle" onClick={() => toggle.mutate(r)}>
                  {r.is_active ? kt.deactivate : kt.activate}
                </Button>
              </Group>
            ),
          },
        ]}
      />
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      <Modal
        opened={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? kt.addStandard : kt.edit}
      >
        <Stack>
          <Select
            label={kt.material}
            withAsterisk
            searchable
            disabled={editing !== "new"}
            data={materials.data ?? []}
            value={draft.material}
            onChange={(value) => setDraft((d) => ({ ...d, material: value }))}
          />
          <TextInput
            label={kt.unitCost}
            withAsterisk
            inputMode="decimal"
            value={draft.unit_cost}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setDraft((d) => ({ ...d, unit_cost: value }));
            }}
          />
          <TextInput
            label={kt.note}
            value={draft.note}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setDraft((d) => ({ ...d, note: value }));
            }}
          />
          {save.isError && <ErrorAlert error={save.error} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setEditing(null)}>
              {kt.cancel}
            </Button>
            <Button
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={!draft.material || !draft.unit_cost.trim()}
            >
              {kt.save}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
