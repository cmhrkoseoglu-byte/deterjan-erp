// Personel > Bordro: ay hazırlığı listesi (eksikler ve düzeltme bağlantıları), brütten nete bordro
// tablosu (ERP'de hesaplanan kişiler; satıra basınca döküm) ve ayın ek ödeme ve kesintileri.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  ThemeIcon,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconInfoCircle,
  IconLock,
  type Icon as TablerIcon,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  listPayrollItems,
  payrollKeys,
  type PayrollItemRecord,
  type PayrollMonth,
  type PayrollRow,
  type PayrollWarning,
} from "../../api/payroll";
import { formatDateTime, formatMoney } from "../../i18n/format";
import { monthLabel, shiftMonth } from "../costing/personnelCostFormat";
import { ErrorAlert } from "../costing/ReportTable";
import {
  CATEGORY_LABELS,
  categoryOptions,
  externalItems,
  isFutureMonth,
  itemLabel,
  missingOpenings,
  monthItems,
  staleOpenings,
  warningHelp,
  warningLabel,
} from "./payrollFormat";
import { CardChanges } from "./PayrollApproval";
import { ATTENDANCE_BASE, pa, pn, py, WAGES_BASE } from "./strings";

const NO_WRAP: CSSProperties = { whiteSpace: "nowrap" };
const STICKY: CSSProperties = {
  position: "sticky",
  left: 0,
  background: "var(--mantine-color-body)",
  zIndex: 1,
};

const money = (value: string | number | null) => formatMoney(value);
const sum = (...values: (string | null)[]) =>
  values.reduce((total, value) => total + Number(value ?? 0), 0);

type Tone = "ok" | "warn" | "error";

function CheckLine({
  tone,
  children,
  action,
}: {
  tone: Tone;
  children: ReactNode;
  action?: ReactNode;
}) {
  const color = tone === "ok" ? "green" : tone === "warn" ? "yellow" : "red";
  const Icon: TablerIcon = tone === "ok" ? IconCheck : IconAlertTriangle;
  return (
    <Group gap="xs" wrap="nowrap" justify="space-between">
      <Group gap="xs" wrap="nowrap">
        <ThemeIcon size="sm" radius="xl" variant="light" color={color}>
          <Icon size={14} />
        </ThemeIcon>
        <Text size="sm">{children}</Text>
      </Group>
      {action && <div style={{ flexShrink: 0, whiteSpace: "nowrap" }}>{action}</div>}
    </Group>
  );
}

/** Ay hazırlığı: ayın bordrosunu etkileyen her eksik bir satır ve düzeltme bağlantısıyla; onaya
 * hazır mı, bir önceki ay onaylı mı. Onaylı ayda yalnızca kilit satırı. */
export function PayrollChecklist({
  payroll,
  onParameters,
  onOpenings,
  onEmployerCost,
  onItems,
  onPrevious,
}: {
  payroll: PayrollMonth;
  onParameters: () => void;
  /** Devir penceresi: devri eksik kişilerin giriş ayı (verilmezse en erken eksik ay). */
  onOpenings: (target?: number) => void;
  onEmployerCost: () => void;
  onItems: () => void;
  /** Bir önceki aya git (aylar sırayla onaylanır). */
  onPrevious?: () => void;
}) {
  const state = payroll.payroll;
  if (state.approved)
    return (
      <Paper withBorder p="sm" radius="md">
        <Group gap="xs" wrap="nowrap">
          <ThemeIcon size="sm" radius="xl" variant="light" color="teal">
            <IconLock size={14} />
          </ThemeIcon>
          <Text size="sm">{pa.lockedLine(state.number)}</Text>
        </Group>
      </Paper>
    );
  const ay = `${payroll.year}-${String(payroll.month).padStart(2, "0")}`;
  const blocking = (state.gates ?? []).filter((gate) => gate.level === "block").length;
  const [previousYear, previousMonth] = shiftMonth(payroll.year, payroll.month, -1)
    .split("-")
    .map(Number);
  const rows = payroll.rows;
  const has = (code: PayrollWarning) => rows.filter((row) => row.warnings.includes(code));
  const missingWages = has("missing_wage");
  const formerMissing = missingWages.some((row) => !row.employee.is_active);
  const figures = has("external_missing");
  const openings = missingOpenings(payroll);
  const stale = staleOpenings(payroll);
  const notComputed = externalItems(rows);
  const negative = has("negative_payable");
  const carry = has("carry_incomplete");
  const origin = payroll.parameters.origin;
  return (
    <Paper withBorder p="sm" radius="md">
      <Stack gap={6}>
        <Text fw={600} size="sm">
          {pn.checklistTitle}
        </Text>
        <CheckLine
          tone={payroll.attendance_approved ? "ok" : "warn"}
          action={
            !payroll.attendance_approved && (
              <Anchor component={Link} to={`${ATTENDANCE_BASE}?ay=${ay}`} size="sm">
                {py.openAttendance}
              </Anchor>
            )
          }
        >
          {payroll.attendance_approved
            ? pn.checkAttendanceOk(payroll.attendance_number)
            : py.attendanceOpenHint}
        </CheckLine>
        <CheckLine
          tone={origin === "saved" ? "ok" : origin === "fallback" ? "error" : "warn"}
          action={
            origin !== "saved" && (
              <Anchor component="button" type="button" size="sm" onClick={onParameters}>
                {py.openParameters}
              </Anchor>
            )
          }
        >
          {origin === "saved"
            ? pn.checkParametersOk
            : origin === "fallback"
              ? py.parametersFallbackHint(payroll.year, payroll.parameters.year)
              : py.parametersDefaultHint(payroll.year)}
        </CheckLine>
        {payroll.net && !openings.length && !stale.length && (
          <CheckLine tone="ok">{pn.checkOpeningsOk}</CheckLine>
        )}
        {payroll.net &&
          openings.map(([entry, count]) => (
            <CheckLine
              key={entry}
              tone="error"
              action={
                isFutureMonth(payroll.year, entry) ? (
                  <Text size="sm" c="dimmed">
                    {pn.futureOpeningLater}
                  </Text>
                ) : (
                  <Anchor
                    component="button"
                    type="button"
                    size="sm"
                    aria-label={`${pn.openingEnter}: ${monthLabel(payroll.year, entry)}`}
                    onClick={() => onOpenings(entry)}
                  >
                    {pn.openingEnter}
                  </Anchor>
                )
              }
            >
              {pn.checkOpeningsMissing(count, monthLabel(payroll.year, entry))}
            </CheckLine>
          ))}
        {payroll.net &&
          stale.map(([month, count]) => (
            <CheckLine
              key={`stale-${month}`}
              tone="warn"
              action={
                <Anchor
                  component="button"
                  type="button"
                  size="sm"
                  aria-label={`${pn.staleOpeningAction}: ${monthLabel(payroll.year, month)}`}
                  onClick={() => onOpenings(month)}
                >
                  {pn.staleOpeningAction}
                </Anchor>
              }
            >
              {pn.checkStaleOpenings(count, monthLabel(payroll.year, month))}
            </CheckLine>
          ))}
        {missingWages.length > 0 && (
          <CheckLine
            tone="warn"
            action={
              <Anchor
                component={Link}
                to={`${WAGES_BASE}${formerMissing ? "?ayrilanlar=1" : ""}`}
                size="sm"
              >
                {py.goToWages}
              </Anchor>
            }
          >
            {py.missingWages(missingWages.length)}
          </CheckLine>
        )}
        {figures.length > 0 && (
          <CheckLine
            tone="warn"
            action={
              <Anchor component="button" type="button" size="sm" onClick={onEmployerCost}>
                {py.enterFigures}
              </Anchor>
            }
          >
            {py.externalMissing(figures.length)}
          </CheckLine>
        )}
        {payroll.net && negative.length > 0 && (
          <CheckLine tone="error">{pn.checkNegative(negative.length)}</CheckLine>
        )}
        {payroll.net && carry.length > 0 && (
          <CheckLine tone="warn">{pn.checkCarry(carry.length)}</CheckLine>
        )}
        {payroll.orphan_items.length > 0 && (
          <CheckLine
            tone="warn"
            action={
              <Anchor component="button" type="button" size="sm" onClick={onItems}>
                {pn.viewItems}
              </Anchor>
            }
          >
            {pn.checkOrphans(payroll.orphan_items.length)}
          </CheckLine>
        )}
        {notComputed.length > 0 && (
          <CheckLine
            tone="warn"
            action={
              <Anchor component="button" type="button" size="sm" onClick={onItems}>
                {pn.viewItems}
              </Anchor>
            }
          >
            {pn.checkExternalItems(notComputed.length)}
          </CheckLine>
        )}
        {payroll.net && state.previous_open && (
          <CheckLine
            tone="error"
            action={
              onPrevious && (
                <Anchor component="button" type="button" size="sm" onClick={onPrevious}>
                  {pa.openPrevious}
                </Anchor>
              )
            }
          >
            {pa.previousOpenLine(monthLabel(previousYear, previousMonth))}
          </CheckLine>
        )}
        {payroll.net && state.gates !== null && (
          <CheckLine tone={blocking ? "warn" : "ok"}>
            {blocking ? pa.notReadyLine(blocking) : pa.readyLine}
          </CheckLine>
        )}
        <CardChanges payroll={payroll} />
      </Stack>
    </Paper>
  );
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

function WarningBadge({ row }: { row: PayrollRow }) {
  const codes = row.warnings;
  if (!codes.length) return null;
  const serious = codes.some((code) =>
    ["opening_missing", "negative_payable", "below_minimum_wage", "pay_without_sgk_days"].includes(
      code,
    ),
  );
  return (
    <Tooltip
      label={codes.map((code) => warningHelp(code) ?? warningLabel(code)).join(" · ")}
      multiline
      w={300}
      events={{ hover: true, focus: true, touch: true }}
    >
      <Badge color={serious ? "red" : "orange"} variant="light" size="sm" tt="none" tabIndex={0}>
        {codes.length === 1 ? warningLabel(codes[0]) : pn.warningCount(codes.length)}
      </Badge>
    </Tooltip>
  );
}

/** Brütten nete bordro tablosu (ERP'de hesaplananlar; mali müşavirdekiler alt satırda). */
export function PayrollNetView({
  payroll,
  rows,
  onlyWarnings,
  onOnlyWarningsChange,
  onOpen,
}: {
  payroll: PayrollMonth;
  /** Tablodaki kişiler (süzgeç uygulanmış; döküm aynı sırayı izler). */
  rows: PayrollRow[];
  onlyWarnings: boolean;
  onOnlyWarningsChange: (value: boolean) => void;
  onOpen: (row: PayrollRow) => void;
}) {
  const computed = payroll.rows.filter((row) => !row.external);
  const external = payroll.rows.filter((row) => row.external);
  const { totals } = payroll;
  const externalGross = external.reduce((total, row) => total + Number(row.gross_total), 0);
  const externalCost = external.reduce((total, row) => total + Number(row.employer_cost), 0);
  const headers = [
    pn.col.employeeNo,
    pn.col.fullName,
    pn.col.department,
    pn.col.sgkDays,
    pn.col.salary,
    pn.col.overtime,
    pn.col.extras,
    pn.col.gross,
    pn.col.employeeSgk,
    pn.col.employeeUnemployment,
    pn.col.incomeTax,
    pn.col.stampTax,
    pn.col.net,
    pn.col.bes,
    pn.col.deductions,
    pn.col.payable,
  ];
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, sm: 3, lg: 6 }}>
        <Stat label={pn.statPeople} value={`${computed.length} / ${external.length}`} />
        <Stat label={pn.statGross} value={formatMoney(totals.computed_gross_total, "TL")} />
        <Stat label={pn.statIncomeTax} value={formatMoney(totals.income_tax, "TL")} />
        <Stat label={pn.statStampTax} value={formatMoney(totals.stamp_tax, "TL")} />
        <Stat label={pn.statNet} value={formatMoney(totals.net_pay, "TL")} />
        <Stat label={pn.statPayable} value={formatMoney(totals.payable, "TL")} strong />
      </SimpleGrid>
      <Group justify="flex-end">
        <Switch
          label={pn.onlyWarnings}
          checked={onlyWarnings}
          onChange={(event) => onOnlyWarningsChange(event.currentTarget.checked)}
        />
      </Group>
      {!computed.length ? (
        <Text c="dimmed">{pn.emptyComputed}</Text>
      ) : (
        <Table.ScrollContainer minWidth={1500}>
          <Table
            striped
            highlightOnHover
            withTableBorder
            verticalSpacing={6}
            data-testid="payroll-net"
          >
            <Table.Thead>
              <Table.Tr>
                {headers.map((header, index) => (
                  <Table.Th
                    key={header}
                    ta={index >= 3 ? "right" : undefined}
                    style={index === 1 ? { ...STICKY, ...NO_WRAP } : NO_WRAP}
                  >
                    {header}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => {
                const line = row.line;
                const overtime = sum(
                  line.overtime_worked_pay,
                  line.overtime_rest_pay,
                  line.holiday_pay,
                );
                return (
                  <Table.Tr
                    key={row.employee.id}
                    onClick={() => onOpen(row)}
                    style={{ cursor: "pointer" }}
                  >
                    <Table.Td style={NO_WRAP}>{row.employee.employee_no}</Table.Td>
                    <Table.Td style={STICKY}>
                      <Group gap={6} wrap="nowrap">
                        <UnstyledButton
                          aria-label={pn.openBreakdown(row.employee.full_name)}
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpen(row);
                          }}
                        >
                          <Text size="sm" fw={500} td="underline" style={NO_WRAP}>
                            {row.employee.full_name}
                          </Text>
                        </UnstyledButton>
                        <WarningBadge row={row} />
                      </Group>
                    </Table.Td>
                    <Table.Td>{row.employee.department}</Table.Td>
                    <Table.Td ta="right">{line.sgk_days}</Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.salary)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(overtime)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.extras_total)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.gross_total)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.employee_sgk)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.employee_unemployment)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.income_tax)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.stamp_tax)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.net_pay)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.bes_deduction)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      {money(line.deductions_total)}
                    </Table.Td>
                    <Table.Td ta="right" style={NO_WRAP}>
                      <Text
                        span
                        size="sm"
                        fw={600}
                        c={Number(line.payable) < 0 ? "red" : undefined}
                      >
                        {money(line.payable)}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
            <Table.Tfoot>
              <Table.Tr fw={700}>
                <Table.Td />
                <Table.Td style={STICKY}>{pn.totals}</Table.Td>
                <Table.Td />
                <Table.Td />
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.salary)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(
                    sum(totals.overtime_worked_pay, totals.overtime_rest_pay, totals.holiday_pay),
                  )}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.extras_total)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.computed_gross_total)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.employee_sgk)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.employee_unemployment)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.income_tax)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.stamp_tax)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.net_pay)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.bes_deduction)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.deductions_total)}
                </Table.Td>
                <Table.Td ta="right" style={NO_WRAP}>
                  {money(totals.payable)}
                </Table.Td>
              </Table.Tr>
            </Table.Tfoot>
          </Table>
        </Table.ScrollContainer>
      )}
      {external.length > 0 && (
        <Text size="sm" c="dimmed">
          {pn.externalLine(
            external.length,
            formatMoney(externalGross, "TL"),
            formatMoney(externalCost, "TL"),
          )}
        </Text>
      )}
    </Stack>
  );
}

/** Ayın ek ödeme ve kesintileri: süzgeç, kalem toplamları, düzelt / kaldır, kaldırılanlar.
 * Onaylı ayda (`locked`) yalnızca okunur. */
export function PayrollItemsView({
  payroll,
  onAdd,
  onEdit,
  onRemove,
  onBulk,
  onCopy,
  locked = false,
}: {
  payroll: PayrollMonth;
  locked?: boolean;
  onAdd: () => void;
  onEdit: (item: PayrollItemRecord) => void;
  onRemove: (item: PayrollItemRecord) => void;
  onBulk: () => void;
  onCopy: () => void;
}) {
  const [category, setCategory] = useState<string | null>(null);
  const [showRemoved, setShowRemoved] = useState(false);
  const removed = useQuery({
    queryKey: payrollKeys.items({ year: payroll.year, month: payroll.month, removed: true }),
    queryFn: () =>
      listPayrollItems({
        year: payroll.year,
        month: payroll.month,
        is_active: false,
        page_size: 500,
      }),
    enabled: showRemoved,
  });
  const active = monthItems(payroll.rows, payroll.orphan_items);
  const orphans = new Set(payroll.orphan_items.map((item) => item.id));
  const external = new Set(externalItems(payroll.rows).map((item) => item.id));
  const future = isFutureMonth(payroll.year, payroll.month);
  const items = [...active, ...(showRemoved ? (removed.data?.results ?? []) : [])].filter(
    (item) => !category || item.category === category,
  );
  // Kalem toplamları bordroya girenlerden: işte olmayanlara ve bordrosu mali müşavirde olanlara
  // girilenler hesaba girmez.
  const totals = new Map<string, number>();
  for (const item of active)
    if (!orphans.has(item.id) && !external.has(item.id))
      totals.set(item.category, (totals.get(item.category) ?? 0) + Number(item.amount));
  const closed = future || locked;
  return (
    <Stack>
      {locked && (
        <Alert color="teal" variant="light" icon={<IconLock size={18} />}>
          <Text size="sm">{pa.locked}</Text>
        </Alert>
      )}
      {future && (
        <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
          <Text size="sm">{pn.futureItemsHint}</Text>
        </Alert>
      )}
      {payroll.orphan_items.length > 0 && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Text size="sm">{pn.orphanAlert(payroll.orphan_items.length)}</Text>
        </Alert>
      )}
      {external.size > 0 && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Text size="sm">{pn.externalItemsAlert(external.size)}</Text>
        </Alert>
      )}
      <Group justify="space-between" wrap="wrap">
        <Group gap="xs" wrap="wrap">
          <Select
            aria-label={pn.itemCategory}
            placeholder={pn.itemCategory}
            data={categoryOptions()}
            value={category}
            onChange={setCategory}
            clearable
            w={220}
          />
          <Switch
            label={pn.showRemoved}
            checked={showRemoved}
            onChange={(event) => setShowRemoved(event.currentTarget.checked)}
          />
        </Group>
        <Group gap="xs" wrap="wrap">
          <Button variant="default" onClick={onCopy} disabled={closed}>
            {pn.copyPrevious}
          </Button>
          <Button variant="default" onClick={onBulk} disabled={closed}>
            {pn.bulkAdd}
          </Button>
          <Button onClick={onAdd} disabled={closed}>
            {pn.addItem}
          </Button>
        </Group>
      </Group>
      {totals.size > 0 && (
        <Group gap="xs" wrap="wrap">
          <Text size="sm" c="dimmed">
            {pn.categoryTotals}:
          </Text>
          {[...totals.entries()].map(([code, total]) => (
            <Badge key={code} variant="light" tt="none">
              {`${CATEGORY_LABELS[code as keyof typeof CATEGORY_LABELS]} ${formatMoney(total)}`}
            </Badge>
          ))}
        </Group>
      )}
      {removed.isError && <ErrorAlert error={removed.error} />}
      {!items.length ? (
        <Group gap="xs">
          <IconInfoCircle size={16} />
          <Text c="dimmed">{pn.itemsEmpty}</Text>
        </Group>
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table striped withTableBorder verticalSpacing={6} data-testid="payroll-items">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{pn.itemPerson}</Table.Th>
                <Table.Th>{pn.itemCategory}</Table.Th>
                <Table.Th>{pn.itemDescription}</Table.Th>
                <Table.Th ta="right">{pn.itemAmount}</Table.Th>
                <Table.Th>{pn.itemEnteredBy}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item) => (
                <Table.Tr key={item.id} style={item.is_active ? undefined : { opacity: 0.6 }}>
                  <Table.Td>
                    {item.employee_name}
                    {orphans.has(item.id) && (
                      <Badge color="orange" variant="light" size="xs" ml={6} tt="none">
                        {pn.itemNotEmployed}
                      </Badge>
                    )}
                    {external.has(item.id) && (
                      <Badge color="violet" variant="light" size="xs" ml={6} tt="none">
                        {pn.itemExternal}
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>{CATEGORY_LABELS[item.category]}</Table.Td>
                  <Table.Td>{item.description}</Table.Td>
                  <Table.Td
                    ta="right"
                    style={
                      item.is_active ? NO_WRAP : { ...NO_WRAP, textDecoration: "line-through" }
                    }
                  >
                    {item.kind === "DEDUCTION"
                      ? `−${formatMoney(item.amount)}`
                      : formatMoney(item.amount)}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">
                      {item.is_active
                        ? pn.enteredAt(item.updated_by_name ?? "—", formatDateTime(item.updated_at))
                        : pn.itemRemovedReason(
                            item.removed_by_name ?? "—",
                            formatDateTime(item.removed_at),
                            item.removal_reason,
                          )}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {item.is_active && !locked && (
                      <Group gap={4} justify="flex-end" wrap="nowrap">
                        <Button
                          size="compact-xs"
                          variant="light"
                          aria-label={pn.itemAction(
                            pn.editItem,
                            `${item.employee_name} ${itemLabel(item)}`,
                            formatMoney(item.amount),
                          )}
                          onClick={() => onEdit(item)}
                        >
                          {pn.editItem}
                        </Button>
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          color="red"
                          aria-label={pn.itemAction(
                            pn.removeItem,
                            `${item.employee_name} ${itemLabel(item)}`,
                            formatMoney(item.amount),
                          )}
                          onClick={() => onRemove(item)}
                        >
                          {pn.removeItem}
                        </Button>
                      </Group>
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
