// Personel > Bordro: ayın ön bordrosu (canlı hesap): brütten nete bordro tablosu ve dökümü,
// işverene maliyet tablosu, ek ödeme ve kesintiler, devirler, parametreler, mali müşavirde
// hesaplanan kişilerin rakamları, PDF ve Excel (docs/DECISIONS.md "Personel bordrosu"). Ücret ve
// kesinti bilgisi kişisel veridir; yalnızca yönetim ve admin görür.
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconChevronLeft,
  IconChevronRight,
  IconFileSpreadsheet,
  IconFileTypePdf,
  IconInfoCircle,
  IconLock,
  IconSettings,
  IconTransferIn,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { personnelCostKeys } from "../../api/costing";
import {
  employerCostPdfUrl,
  getPayrollMonth,
  payrollExcelUrl,
  payrollKeys,
  registerPdfUrl,
  removeExternalFigure,
  removeOpening,
  removePayrollItem,
  setExternalFigure,
  type PayrollItemRecord,
  type PayrollMonth,
  type PayrollOpening,
  type PayrollRow,
} from "../../api/payroll";
import { formatMoney, formatNumber } from "../../i18n/format";
import { monthLabel, parseMoney, parseMonth, shiftMonth } from "../costing/personnelCostFormat";
import { ErrorAlert } from "../costing/ReportTable";
import { OpeningsModal } from "./OpeningsModal";
import { isFutureMonth, openingTarget } from "./payrollFormat";
import { PayrollDrawer } from "./PayrollDrawer";
import { BulkItemsModal, CopyItemsModal, PayrollItemModal } from "./PayrollItemModals";
import { PayrollChecklist, PayrollItemsView, PayrollNetView } from "./PayrollNetView";
import { PayrollParametersModal } from "./PayrollParametersModal";
import { PersonnelTabs } from "./PersonnelTabs";
import { ReasonModal } from "./ReasonModal";
import { PAYROLL_BASE, pe, pn, py } from "./strings";

const NO_WRAP: CSSProperties = { whiteSpace: "nowrap" };
// Ad sütunu yatay kaydırmada sabit kalır (dar ekranda tablo kayar).
const STICKY: CSSProperties = {
  position: "sticky",
  left: 0,
  background: "var(--mantine-color-body)",
  zIndex: 1,
};
const WARNING_COLORS: Record<string, string> = {
  missing_wage: "orange",
  below_minimum_wage: "red",
  external_missing: "orange",
  exit_in_month: "gray",
  pay_without_sgk_days: "red",
};
// Görünümler (`?gorunum=`): bordro (brütten nete), işveren maliyeti, ek ödeme ve kesintiler.
const VIEWS = ["bordro", "maliyet", "kalemler"] as const;
type View = (typeof VIEWS)[number];

const money = (value: string) => formatMoney(value);
const rate = (value: string) => formatNumber(value);

function share(cost: string, gross: string): string {
  const base = Number(gross);
  if (!base) return "";
  return `%${formatNumber((Number(cost) / base) * 100, 2)}`;
}

function Stat({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={strong ? 700 : 600}>{value}</Text>
    </Paper>
  );
}

function StatusBadges({ payroll }: { payroll: PayrollMonth }) {
  const { parameters } = payroll;
  const since = parameters.valid_from
    ? `${parameters.valid_from.slice(5, 7)}.${parameters.valid_from.slice(0, 4)}`
    : "";
  return (
    <>
      {payroll.attendance_approved ? (
        <Badge color="green" leftSection={<IconLock size={12} />}>
          {py.attendanceApproved(payroll.attendance_number)}
        </Badge>
      ) : (
        <Badge color="gray" variant="light">
          {py.attendanceOpen}
        </Badge>
      )}
      {parameters.origin === "saved" && (
        <Badge color="blue" variant="light">
          {py.parametersSaved(since)}
        </Badge>
      )}
      {parameters.origin === "legal_default" && (
        <Badge color="yellow" variant="light">
          {py.parametersDefault}
        </Badge>
      )}
      {parameters.origin === "fallback" && (
        <Badge color="red" variant="light">
          {py.parametersFallback}
        </Badge>
      )}
    </>
  );
}

function RowBadges({ row }: { row: PayrollRow }) {
  const badges: ReactNode[] = [];
  if (row.external)
    badges.push(
      <Badge key="external" color="violet" variant="light" size="sm" tt="none">
        {py.external}
      </Badge>,
    );
  for (const warning of row.warnings) {
    if (!(warning in py.warning)) continue; // brütten nete uyarıları bordro görünümünde
    const badge = (
      <Badge key={warning} color={WARNING_COLORS[warning]} variant="light" size="sm" tt="none">
        {py.warning[warning]}
      </Badge>
    );
    const help = py.warningHelp[warning];
    badges.push(
      help ? (
        <Tooltip
          key={warning}
          label={help}
          multiline
          w={260}
          events={{ hover: true, focus: true, touch: true }}
        >
          <span tabIndex={0}>{badge}</span>
        </Tooltip>
      ) : (
        badge
      ),
    );
  }
  if (!row.external && row.line.floor_applied)
    badges.push(
      <Badge key="floor" color="blue" variant="light" size="sm" tt="none">
        {py.floorApplied}
      </Badge>,
    );
  if (!row.external && row.line.ceiling_applied)
    badges.push(
      <Badge key="ceiling" color="blue" variant="light" size="sm" tt="none">
        {py.ceilingApplied}
      </Badge>,
    );
  return <>{badges}</>;
}

function EmployerCostTable({
  payroll,
  onFigure,
}: {
  payroll: PayrollMonth;
  onFigure: (row: PayrollRow) => void;
}) {
  const values = payroll.parameters.values;
  const { totals } = payroll;
  const headers = [
    py.col.employeeNo,
    py.col.fullName,
    py.col.department,
    py.col.sgkDays,
    py.col.grossTotal,
    py.col.sgkBase,
    py.col.employerSgk(rate(values.employer_sgk_rate)),
    py.col.incentive(rate(values.incentive_points)),
    py.col.employerUnemployment(rate(values.employer_unemployment_rate)),
    py.col.floorGap,
    py.col.employerCost,
    py.col.share,
  ];
  const right = (index: number) => index >= 3;
  return (
    <Table.ScrollContainer minWidth={1180}>
      <Table striped withTableBorder verticalSpacing={6}>
        <Table.Thead>
          <Table.Tr>
            {headers.map((header, index) => (
              <Table.Th
                key={header}
                ta={right(index) ? "right" : undefined}
                style={index === 1 ? { ...STICKY, ...NO_WRAP } : NO_WRAP}
              >
                {header}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {payroll.rows.map((row) => {
            const line = row.line;
            const external = row.external;
            const dash = external ? "—" : null;
            return (
              <Table.Tr key={row.employee.id}>
                <Table.Td style={NO_WRAP}>{row.employee.employee_no}</Table.Td>
                <Table.Td style={STICKY}>
                  <Group gap={6} wrap="wrap">
                    <span>{row.employee.full_name}</span>
                    <RowBadges row={row} />
                    {external && (
                      <Button
                        size="compact-xs"
                        variant="light"
                        aria-label={`${row.figure ? py.editFigures : py.enterFigures}: ${row.employee.full_name}`}
                        onClick={() => onFigure(row)}
                      >
                        {row.figure ? py.editFigures : py.enterFigures}
                      </Button>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>{row.employee.department}</Table.Td>
                <Table.Td ta="right">{dash ?? line.sgk_days}</Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {external ? (row.figure ? money(row.gross_total) : "") : money(line.gross_total)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {dash ?? money(line.sgk_base)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {dash ?? money(line.employer_sgk_gross)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {dash ?? (Number(line.incentive) ? `−${money(line.incentive)}` : money("0"))}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {dash ?? money(line.employer_unemployment)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {dash ?? money(line.floor_gap)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  <Text span size="sm" fw={600}>
                    {external && !row.figure ? "" : money(row.employer_cost)}
                  </Text>
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {external && !row.figure ? "" : share(row.employer_cost, row.gross_total)}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
        <Table.Tfoot>
          <Table.Tr fw={700}>
            <Table.Td />
            <Table.Td style={STICKY}>{py.totals}</Table.Td>
            <Table.Td />
            <Table.Td />
            <Table.Td ta="right" style={NO_WRAP}>
              {money(totals.gross_total)}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {money(totals.sgk_base)}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {money(totals.employer_sgk_gross)}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {Number(totals.incentive) ? `−${money(totals.incentive)}` : money("0")}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {money(totals.employer_unemployment)}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {money(totals.floor_gap)}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {money(totals.employer_cost)}
            </Table.Td>
            <Table.Td ta="right" style={NO_WRAP}>
              {share(totals.employer_cost, totals.gross_total)}
            </Table.Td>
          </Table.Tr>
        </Table.Tfoot>
      </Table>
    </Table.ScrollContainer>
  );
}

function ExternalFigureModal({
  payroll,
  row,
  onClose,
}: {
  payroll: PayrollMonth;
  row: PayrollRow;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [gross, setGross] = useState(row.figure ? formatMoney(row.figure.gross_total) : "");
  const [cost, setCost] = useState(row.figure ? formatMoney(row.figure.employer_cost) : "");
  const [note, setNote] = useState(row.figure?.note ?? "");
  const [removing, setRemoving] = useState(false);
  // Ayın tamamı raporlu ya da ücretsiz izinli kişide mali müşavirin rakamları 0 / 0 olabilir.
  const grossValue = parseMoney(gross, { allowZero: true });
  const costValue = parseMoney(cost, { allowZero: true });
  const costBelow =
    grossValue !== null && costValue !== null && Number(costValue) < Number(grossValue);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
    void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
  };
  const save = useMutation({
    mutationFn: () =>
      setExternalFigure(payroll.year, payroll.month, {
        employee: row.employee.id,
        gross_total: grossValue ?? "",
        employer_cost: costValue ?? "",
        note: note.trim(),
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: py.figuresSaved });
      refresh();
    },
  });
  // İstek sürerken pencere kapanmaz; kapatma istek başına (geç gelen yanıt başka bir pencereyi
  // kapatmasın).
  const close = () => {
    if (!save.isPending) onClose();
  };
  const invalid = (text: string, value: string | null) =>
    text.trim() && value === null ? py.invalidAmount : undefined;
  if (removing && row.figure) {
    const figure = row.figure;
    return (
      <ReasonModal
        title={pn.removeFigures}
        intro={pn.removeFiguresIntro}
        confirmLabel={pn.removeFigures}
        onConfirm={(reason) => removeExternalFigure(figure.id, reason)}
        onDone={() => {
          notifications.show({ color: "green", message: pn.figuresRemoved });
          refresh();
          onClose();
        }}
        onClose={() => setRemoving(false)}
      />
    );
  }
  return (
    <Modal
      opened
      onClose={close}
      title={py.figuresTitle(row.employee.full_name)}
      closeOnClickOutside={false}
      closeOnEscape={!save.isPending}
      withCloseButton={!save.isPending}
    >
      <Stack>
        <Text size="sm" c="dimmed">
          {py.figuresIntro(payroll.period_label)}
        </Text>
        <TextInput
          label={py.figureGross}
          withAsterisk
          inputMode="decimal"
          value={gross}
          error={invalid(gross, grossValue)}
          onChange={(event) => setGross(event.currentTarget.value)}
        />
        <TextInput
          label={py.figureCost}
          withAsterisk
          inputMode="decimal"
          value={cost}
          error={invalid(cost, costValue) ?? (costBelow ? py.figureCostBelowGross : undefined)}
          onChange={(event) => setCost(event.currentTarget.value)}
        />
        <TextInput
          label={py.figureNote}
          description={py.figureNoteHelp}
          maxLength={200}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        {save.isError && <ErrorAlert error={save.error} />}
        <Group justify="space-between">
          {row.figure ? (
            <Button
              variant="subtle"
              color="red"
              onClick={() => setRemoving(true)}
              disabled={save.isPending}
            >
              {pn.removeFigures}
            </Button>
          ) : (
            <span />
          )}
          <Group>
            <Button variant="default" onClick={close} disabled={save.isPending}>
              {py.cancel}
            </Button>
            <Button
              onClick={() => save.mutate(undefined, { onSuccess: onClose })}
              loading={save.isPending}
              disabled={grossValue === null || costValue === null || costBelow}
            >
              {py.save}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}

function EmployerCostView({
  payroll,
  onFigure,
}: {
  payroll: PayrollMonth;
  onFigure: (row: PayrollRow) => void;
}) {
  const { parameters, totals } = payroll;
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, sm: 5 }}>
        <Stat label={py.totalCost} value={formatMoney(totals.employer_cost, "TL")} strong />
        <Stat label={py.grossTotal} value={formatMoney(totals.gross_total, "TL")} />
        <Stat label={py.employerSgk} value={formatMoney(totals.employer_sgk, "TL")} />
        <Stat
          label={py.employerUnemployment}
          value={formatMoney(totals.employer_unemployment, "TL")}
        />
        <Stat label={py.employerRate} value={`%${rate(parameters.values.employer_rate)}`} />
      </SimpleGrid>
      <Stack gap={4}>
        <Title order={4}>{py.employerCostTitle}</Title>
        <Text size="sm" c="dimmed" maw={900}>
          {py.employerCostHint}
        </Text>
      </Stack>
      {payroll.rows.length === 0 ? (
        <Text c="dimmed">{py.empty}</Text>
      ) : (
        <EmployerCostTable payroll={payroll} onFigure={onFigure} />
      )}
    </Stack>
  );
}

// Açık pencereler ay değişince (geri tuşu dahil) kapanır ve o aya dönünce kendiliğinden açılmaz: her
// durum hangi ay için açıldığını taşır, ay değişince hepsi sıfırlanır.
type Opened<T> = { key: string } & T;

/** Ay seçici (varsayılan geçen ay), görünümler, ay hazırlığı, bordro tablosu ve dökümü, işveren
 * maliyeti, ek ödeme ve kesintiler, devirler, PDF ve Excel, parametreler ve mali müşavir
 * rakamları. */
export function PayrollPage() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { year, month } = parseMonth(params.get("ay"));
  const requested = params.get("gorunum");
  const view: View = VIEWS.includes(requested as View) ? (requested as View) : "bordro";
  // "Yalnızca uyarılı kişiler" adreste (`?uyarili=1`): tablo ve dökümün sırası aynı.
  const onlyWarnings = params.get("uyarili") === "1";
  const key = `${year}-${month}`;
  const [parametersOpen, setParametersOpen] = useState(false);
  const [figure, setFigure] = useState<Opened<{ employee: number }> | null>(null);
  const [drawer, setDrawer] = useState<Opened<{ employee: number }> | null>(null);
  const [itemModal, setItemModal] = useState<Opened<{
    item?: PayrollItemRecord;
    employee?: number;
  }> | null>(null);
  const [bulk, setBulk] = useState<Opened<object> | null>(null);
  const [copy, setCopy] = useState<Opened<object> | null>(null);
  const [openings, setOpenings] = useState<Opened<{ target?: number; employee?: number }> | null>(
    null,
  );
  const [removingItem, setRemovingItem] = useState<Opened<{ item: PayrollItemRecord }> | null>(
    null,
  );
  const [removingOpening, setRemovingOpening] = useState<Opened<{
    opening: PayrollOpening;
  }> | null>(null);
  const [openedFor, setOpenedFor] = useState(key);
  if (openedFor !== key) {
    setOpenedFor(key);
    setFigure(null);
    setDrawer(null);
    setItemModal(null);
    setBulk(null);
    setCopy(null);
    setOpenings(null);
    setRemovingItem(null);
    setRemovingOpening(null);
  }
  const query = useQuery({
    queryKey: payrollKeys.month(year, month),
    queryFn: () => getPayrollMonth(year, month),
  });
  const payroll = query.data?.year === year && query.data.month === month ? query.data : undefined;
  const current = <T,>(state: Opened<T> | null): Opened<T> | null =>
    state && state.key === key && payroll ? state : null;
  const go = (values: { ay?: string; gorunum?: View }) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (values.ay) next.set("ay", values.ay);
      if (values.gorunum) next.set("gorunum", values.gorunum);
      return next;
    });
  const setOnlyWarnings = (on: boolean) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (on) next.set("uyarili", "1");
      else next.delete("uyarili");
      return next;
    });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
    void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
  };
  const net = Boolean(payroll?.net);
  const shownView: View = net ? view : "maliyet";
  const computed = payroll?.rows.filter((row) => !row.external) ?? [];
  const warned = (row: PayrollRow) => row.warnings.length > 0;
  const tableRows = onlyWarnings ? computed.filter(warned) : computed;
  const drawerState = current(drawer);
  const drawerRow = drawerState
    ? payroll?.rows.find((row) => row.employee.id === drawerState.employee)
    : undefined;
  // Döküm tablodaki sırayı izler; uyarısı giderilen açık kişi listeden düşmez.
  const order = onlyWarnings
    ? computed.filter((row) => warned(row) || row.employee.id === drawerState?.employee)
    : computed;
  const figureState = current(figure);
  const figureRow = figureState
    ? payroll?.rows.find((row) => row.employee.id === figureState.employee && row.external)
    : undefined;
  const itemState = current(itemModal);
  const openingState = current(openings);
  const removingItemState = current(removingItem);
  const removingOpeningState = current(removingOpening);
  // Dökümün üstünde bir pencere açık: Esc ve ok tuşları o pencereye aittir.
  const covered = Boolean(
    parametersOpen ||
    figureRow ||
    itemState ||
    current(bulk) ||
    current(copy) ||
    openingState ||
    removingItemState ||
    removingOpeningState,
  );
  const [startYear, startMonth] = (payroll?.start ?? "2026-10").split("-").map(Number);
  return (
    <Stack>
      <Title order={2}>{pe.title}</Title>
      <PersonnelTabs active={PAYROLL_BASE} />
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{py.intro}</Text>
      </Alert>
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="xs" wrap="wrap">
          <ActionIcon
            variant="default"
            aria-label={py.previousMonth}
            onClick={() => go({ ay: shiftMonth(year, month, -1) })}
          >
            <IconChevronLeft size={16} />
          </ActionIcon>
          <Text fw={600} miw={120} ta="center">
            {monthLabel(year, month)}
          </Text>
          <ActionIcon
            variant="default"
            aria-label={py.nextMonth}
            onClick={() => go({ ay: shiftMonth(year, month, 1) })}
          >
            <IconChevronRight size={16} />
          </ActionIcon>
          {payroll && <StatusBadges payroll={payroll} />}
        </Group>
        <Group gap="xs" wrap="wrap">
          <Button
            variant="default"
            leftSection={<IconSettings size={16} />}
            onClick={() => setParametersOpen(true)}
          >
            {py.parameters}
          </Button>
          {net && payroll && (
            <Button
              variant="default"
              leftSection={<IconTransferIn size={16} />}
              disabled={isFutureMonth(year, openingTarget(payroll))}
              onClick={() => setOpenings({ key })}
            >
              {pn.openings}
            </Button>
          )}
          {net && (
            <Button
              component="a"
              href={registerPdfUrl(year, month)}
              target="_blank"
              rel="noopener"
              variant="default"
              leftSection={<IconFileTypePdf size={16} />}
            >
              {pn.registerPdf}
            </Button>
          )}
          <Button
            component="a"
            href={employerCostPdfUrl(year, month)}
            target="_blank"
            rel="noopener"
            variant="default"
            leftSection={<IconFileTypePdf size={16} />}
          >
            {py.employerCostPdf}
          </Button>
          <Button
            component="a"
            href={payrollExcelUrl(year, month)}
            variant="default"
            leftSection={<IconFileSpreadsheet size={16} />}
          >
            {py.excel}
          </Button>
        </Group>
      </Group>
      {query.isError && <ErrorAlert error={query.error} />}
      {query.isLoading && <Loader />}
      {payroll && (
        <Stack>
          {!payroll.net && (
            <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
              <Text size="sm">{pn.beforeStart(monthLabel(startYear, startMonth))}</Text>
            </Alert>
          )}
          <PayrollChecklist
            payroll={payroll}
            onParameters={() => setParametersOpen(true)}
            onOpenings={(target) => setOpenings({ key, target })}
            onEmployerCost={() => go({ gorunum: "maliyet" })}
            onItems={() => go({ gorunum: "kalemler" })}
          />
          {net && (
            <SegmentedControl
              value={shownView}
              onChange={(value) => go({ gorunum: value as View })}
              data={[
                { value: "bordro", label: pn.viewPayroll },
                { value: "maliyet", label: pn.viewEmployerCost },
                { value: "kalemler", label: pn.viewItems },
              ]}
              w="fit-content"
            />
          )}
          {shownView === "bordro" && (
            <PayrollNetView
              payroll={payroll}
              rows={tableRows}
              onlyWarnings={onlyWarnings}
              onOnlyWarningsChange={setOnlyWarnings}
              onOpen={(row) => setDrawer({ key, employee: row.employee.id })}
            />
          )}
          {shownView === "maliyet" && (
            <EmployerCostView
              payroll={payroll}
              onFigure={(row) => setFigure({ key, employee: row.employee.id })}
            />
          )}
          {shownView === "kalemler" && (
            <PayrollItemsView
              payroll={payroll}
              onAdd={() => setItemModal({ key })}
              onEdit={(item) => setItemModal({ key, item })}
              onRemove={(item) => setRemovingItem({ key, item })}
              onBulk={() => setBulk({ key })}
              onCopy={() => setCopy({ key })}
            />
          )}
        </Stack>
      )}
      {parametersOpen && (
        <PayrollParametersModal
          year={year}
          currentRecord={payroll?.parameters.record ?? null}
          onClose={() => setParametersOpen(false)}
        />
      )}
      {figureRow && payroll && (
        <ExternalFigureModal
          key={`${key}-${figureRow.employee.id}`}
          payroll={payroll}
          row={figureRow}
          onClose={() => setFigure(null)}
        />
      )}
      {drawerRow && payroll && (
        <PayrollDrawer
          payroll={payroll}
          row={drawerRow}
          order={order}
          covered={covered}
          onNavigate={(row) => setDrawer({ key, employee: row.employee.id })}
          onClose={() => setDrawer(null)}
          onAddItem={(row) => setItemModal({ key, employee: row.employee.id })}
          onEditItem={(item) => setItemModal({ key, item })}
          onRemoveItem={(item) => setRemovingItem({ key, item })}
          onOpening={(target, row) => setOpenings({ key, target, employee: row.employee.id })}
          onRemoveOpening={(opening) => setRemovingOpening({ key, opening })}
          onFigure={(row) => setFigure({ key, employee: row.employee.id })}
        />
      )}
      {itemState && payroll && (
        <PayrollItemModal
          key={`${key}-${itemState.item?.id ?? "new"}`}
          payroll={payroll}
          people={computed}
          item={itemState.item}
          employeeId={itemState.employee}
          onClose={() => setItemModal(null)}
        />
      )}
      {current(bulk) && payroll && (
        <BulkItemsModal payroll={payroll} people={computed} onClose={() => setBulk(null)} />
      )}
      {current(copy) && payroll && (
        <CopyItemsModal payroll={payroll} people={computed} onClose={() => setCopy(null)} />
      )}
      {openingState && payroll && (
        <OpeningsModal
          key={`${key}-${openingState.target ?? "auto"}-${openingState.employee ?? "all"}`}
          payroll={payroll}
          target={openingState.target}
          employeeId={openingState.employee}
          onClose={() => setOpenings(null)}
        />
      )}
      {removingItemState && (
        <ReasonModal
          title={pn.removeItemTitle}
          intro={pn.removeItemIntro}
          confirmLabel={pn.removeItem}
          onConfirm={(reason) => removePayrollItem(removingItemState.item.id, reason)}
          onDone={() => {
            notifications.show({ color: "green", message: pn.itemRemoved });
            refresh();
          }}
          onClose={() => setRemovingItem(null)}
        />
      )}
      {removingOpeningState && (
        <ReasonModal
          title={pn.removeOpening}
          intro={pn.removeOpeningIntro}
          confirmLabel={pn.removeOpening}
          onConfirm={(reason) => removeOpening(removingOpeningState.opening.id, reason)}
          onDone={() => {
            notifications.show({ color: "green", message: pn.openingRemoved });
            refresh();
          }}
          onClose={() => setRemovingOpening(null)}
        />
      )}
    </Stack>
  );
}
