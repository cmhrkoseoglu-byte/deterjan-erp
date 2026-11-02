// Personel > Bordro: ayın ön bordrosu (canlı hesap) ve işverene maliyet tablosu; parametreler, mali
// müşavirde hesaplanan kişilerin rakamları, PDF ve Excel (docs/DECISIONS.md "Personel bordrosu").
// Ücret ve kesinti bilgisi kişisel veridir; yalnızca yönetim ve admin görür.
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
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
  IconAlertTriangle,
  IconChevronLeft,
  IconChevronRight,
  IconFileSpreadsheet,
  IconFileTypePdf,
  IconInfoCircle,
  IconLock,
  IconSettings,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { personnelCostKeys } from "../../api/costing";
import {
  employerCostPdfUrl,
  getPayrollMonth,
  payrollExcelUrl,
  payrollKeys,
  setExternalFigure,
  type PayrollMonth,
  type PayrollRow,
} from "../../api/payroll";
import { formatMoney, formatNumber } from "../../i18n/format";
import { monthLabel, parseMoney, parseMonth, shiftMonth } from "../costing/personnelCostFormat";
import { ErrorAlert } from "../costing/ReportTable";
import { PayrollParametersModal } from "./PayrollParametersModal";
import { PersonnelTabs } from "./PersonnelTabs";
import { ATTENDANCE_BASE, PAYROLL_BASE, pe, py, WAGES_BASE } from "./strings";

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
  // Ayın tamamı raporlu ya da ücretsiz izinli kişide mali müşavirin rakamları 0 / 0 olabilir.
  const grossValue = parseMoney(gross, { allowZero: true });
  const costValue = parseMoney(cost, { allowZero: true });
  const costBelow =
    grossValue !== null && costValue !== null && Number(costValue) < Number(grossValue);
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
      void queryClient.invalidateQueries({ queryKey: payrollKeys.all });
      void queryClient.invalidateQueries({ queryKey: personnelCostKeys.all });
    },
  });
  // İstek sürerken pencere kapanmaz; kapatma istek başına (geç gelen yanıt başka bir pencereyi
  // kapatmasın).
  const close = () => {
    if (!save.isPending) onClose();
  };
  const invalid = (text: string, value: string | null) =>
    text.trim() && value === null ? py.invalidAmount : undefined;
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
        <Group justify="flex-end">
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
      </Stack>
    </Modal>
  );
}

function PayrollView({
  payroll,
  onParameters,
  onFigure,
}: {
  payroll: PayrollMonth;
  onParameters: () => void;
  onFigure: (row: PayrollRow) => void;
}) {
  const { parameters, totals } = payroll;
  const missingWages = payroll.rows.filter((row) => row.warnings.includes("missing_wage"));
  const formerMissing = missingWages.some((row) => !row.employee.is_active);
  const externalMissing = payroll.rows.filter((row) => row.warnings.includes("external_missing"));
  const ay = `${payroll.year}-${String(payroll.month).padStart(2, "0")}`;
  return (
    <Stack>
      {!payroll.attendance_approved && (
        <Alert color="yellow" variant="light" icon={<IconInfoCircle size={18} />}>
          <Group gap="xs" justify="space-between">
            <Text size="sm">{py.attendanceOpenHint}</Text>
            <Anchor component={Link} to={`${ATTENDANCE_BASE}?ay=${ay}`} size="sm">
              {py.openAttendance}
            </Anchor>
          </Group>
        </Alert>
      )}
      {parameters.origin !== "saved" && (
        <Alert
          color={parameters.origin === "fallback" ? "red" : "yellow"}
          variant="light"
          icon={<IconAlertTriangle size={18} />}
        >
          <Group gap="xs" justify="space-between">
            <Text size="sm">
              {parameters.origin === "fallback"
                ? py.parametersFallbackHint(payroll.year, parameters.year)
                : py.parametersDefaultHint(payroll.year)}
            </Text>
            <Anchor component="button" type="button" size="sm" onClick={onParameters}>
              {py.openParameters}
            </Anchor>
          </Group>
        </Alert>
      )}
      {missingWages.length > 0 && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Group gap="xs" justify="space-between">
            <Text size="sm">{py.missingWages(missingWages.length)}</Text>
            <Anchor
              component={Link}
              to={`${WAGES_BASE}${formerMissing ? "?ayrilanlar=1" : ""}`}
              size="sm"
            >
              {py.goToWages}
            </Anchor>
          </Group>
        </Alert>
      )}
      {externalMissing.length > 0 && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Text size="sm">{py.externalMissing(externalMissing.length)}</Text>
        </Alert>
      )}
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

/** Ay seçici (varsayılan geçen ay), durum rozetleri, uyarılar, işveren maliyeti tablosu, PDF ve
 * Excel, parametreler ve mali müşavir rakamları. */
export function PayrollPage() {
  const [params, setParams] = useSearchParams();
  const { year, month } = parseMonth(params.get("ay"));
  const [parametersOpen, setParametersOpen] = useState(false);
  const [figure, setFigure] = useState<{ key: string; employee: number } | null>(null);
  const query = useQuery({
    queryKey: payrollKeys.month(year, month),
    queryFn: () => getPayrollMonth(year, month),
  });
  const payroll = query.data;
  const key = `${year}-${month}`;
  // Ay değişince (geri tuşu dahil) açık rakam penceresi kapanır.
  if (figure && figure.key !== key) setFigure(null);
  const figureRow =
    figure && payroll?.year === year && payroll.month === month
      ? payroll.rows.find((row) => row.employee.id === figure.employee && row.external)
      : undefined;
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
            onClick={() => setParams({ ay: shiftMonth(year, month, -1) })}
          >
            <IconChevronLeft size={16} />
          </ActionIcon>
          <Text fw={600} miw={120} ta="center">
            {monthLabel(year, month)}
          </Text>
          <ActionIcon
            variant="default"
            aria-label={py.nextMonth}
            onClick={() => setParams({ ay: shiftMonth(year, month, 1) })}
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
        <PayrollView
          payroll={payroll}
          onParameters={() => setParametersOpen(true)}
          onFigure={(row) => setFigure({ key, employee: row.employee.id })}
        />
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
    </Stack>
  );
}
