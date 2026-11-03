// Bordro dökümü (Personel > Bordro): kişinin ay bordrosu kalem kalem, mali müşavirin bordrosuyla
// karşılaştırmak için (günler, kazançlar, SGK, gelir ve damga vergisi, kesintiler, işveren payları,
// kümülatifin kuruluşu); ek ödeme ve kesinti ile devir sekmeleri. Önceki / sonraki kişi düğmeleri
// ve ← / → tuşları tablodaki sırayı izler.
import {
  Alert,
  Badge,
  Button,
  Drawer,
  Group,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useEffect, type ReactNode } from "react";
import type {
  PayrollItemRecord,
  PayrollMonth,
  PayrollOpening,
  PayrollRow,
} from "../../api/payroll";
import { formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { monthLabel } from "../costing/personnelCostFormat";
import {
  isFutureMonth,
  itemLabel,
  monthsEmployedBefore,
  warningHelp,
  warningLabel,
} from "./payrollFormat";
import { pn, py } from "./strings";

type Line = [label: ReactNode, value: string, strong?: boolean];

function Section({ title, lines }: { title: string; lines: Line[] }) {
  return (
    <Stack gap={4}>
      <Title order={6}>{title}</Title>
      <Table withTableBorder verticalSpacing={4}>
        <Table.Tbody>
          {lines.map(([label, value, strong], index) => (
            <Table.Tr key={index}>
              <Table.Td>
                <Text size="sm" fw={strong ? 700 : 400}>
                  {label}
                </Text>
              </Table.Td>
              <Table.Td ta="right" style={{ whiteSpace: "nowrap" }}>
                <Text size="sm" fw={strong ? 700 : 400}>
                  {value}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

const money = (value: string | number | null) => formatMoney(value);
const minus = (value: string | number | null) =>
  Number(value) ? `−${formatMoney(value)}` : money(0);
const positive = (value: string | number | null) => Number(value ?? 0) > 0;

function bracketIndex(base: number, brackets: string[]): number {
  return brackets.findIndex((limit) => base <= Number(limit));
}

function Breakdown({ payroll, row }: { payroll: PayrollMonth; row: PayrollRow }) {
  const line = row.line;
  const values = payroll.parameters.values;
  const daysInMonth = new Date(payroll.year, payroll.month, 0).getDate();
  const full = line.employed_days === daysInMonth && line.unpaid_days === 0;
  const extras = row.items.filter((item) => item.kind === "EXTRA");
  const deductions = row.items.filter((item) => item.kind === "DEDUCTION");
  const days: Line[] = [
    [pn.employedDays, String(line.employed_days)],
    [pn.paidDays, String(line.paid_days)],
    [
      full ? pn.sgkDaysFull : pn.sgkDaysPartial(line.employed_days, line.unpaid_days),
      String(line.sgk_days),
      true,
    ],
    [pn.workedDays, String(line.worked_days)],
    ...(line.sick_days ? ([[pn.sickDays, String(line.sick_days)]] as Line[]) : []),
    ...(line.unpaid_leave_days
      ? ([[pn.unpaidLeaveDays, String(line.unpaid_leave_days)]] as Line[])
      : []),
    ...(line.absent_days ? ([[pn.absentDays, String(line.absent_days)]] as Line[]) : []),
  ];
  const earnings: Line[] = [
    [pn.monthlyWage, money(line.monthly_wage)],
    [pn.normalSalary, money(line.salary)],
    ...(positive(line.overtime_worked_pay)
      ? ([
          [
            pn.overtimeWorked(formatNumber(line.overtime_worked_hours)),
            money(line.overtime_worked_pay),
          ],
        ] as Line[])
      : []),
    ...(positive(line.overtime_rest_pay)
      ? ([
          [pn.overtimeRest(formatNumber(line.overtime_rest_hours)), money(line.overtime_rest_pay)],
        ] as Line[])
      : []),
    ...(positive(line.holiday_pay)
      ? ([
          [
            pn.holidayPay(
              line.holiday_days,
              line.holiday_half_days,
              formatNumber(line.holiday_extra_hours),
            ),
            money(line.holiday_pay),
          ],
        ] as Line[])
      : []),
    ...extras.map((item): Line => [itemLabel(item), money(item.amount)]),
    [pn.grossTotal, money(line.gross_total), true],
  ];
  const note = line.floor_applied
    ? ` (${pn.floorApplied})`
    : line.ceiling_applied
      ? ` (${pn.ceilingApplied})`
      : "";
  // Nakit yemek kalemi varsa istisna satırı sınır 0 olsa da görünür (SGK matrahı neden brüte eşit).
  const meal = extras.some((item) => item.category === "MEAL");
  const noLimit = !Number(values.meal_exemption_daily);
  const sgk: Line[] = [
    ...(positive(line.meal_exemption) || meal
      ? ([
          [
            noLimit ? `${pn.mealExemption} (${pn.mealNoLimitShort})` : pn.mealExemption,
            minus(line.meal_exemption),
          ],
          [pn.sgkGross, money(line.sgk_gross)],
        ] as Line[])
      : []),
    [`${pn.sgkBase}${note}`, money(line.sgk_base), true],
    [pn.employeeSgk(formatNumber(values.employee_sgk_rate)), money(line.employee_sgk)],
    [
      pn.employeeUnemployment(formatNumber(values.employee_unemployment_rate)),
      money(line.employee_unemployment),
    ],
    ...(positive(line.floor_gap) ? ([[pn.floorGap, money(line.floor_gap)]] as Line[]) : []),
  ];
  const before = Number(line.cumulative_tax_base_before ?? 0);
  const after = Number(line.cumulative_tax_base_after ?? 0);
  const crossed =
    bracketIndex(before, values.tax_brackets) !== bracketIndex(after, values.tax_brackets);
  const incomeTax: Line[] = [
    [pn.taxBase, money(line.tax_base)],
    [pn.cumulativeBefore, money(line.cumulative_tax_base_before)],
    [pn.cumulativeAfter, money(line.cumulative_tax_base_after)],
    [pn.incomeTaxComputed, money(line.income_tax_computed)],
    [pn.exemptionBefore, money(line.exemption_base_before)],
    [pn.exemptionAdded, money(line.exemption_base_added)],
    [pn.incomeTaxExemption, minus(line.income_tax_exemption)],
    [pn.incomeTax, money(line.income_tax), true],
  ];
  const stamp: Line[] = [
    [pn.stampComputed(formatNumber(values.stamp_tax_per_mille)), money(line.stamp_tax_computed)],
    [pn.stampExemption, minus(line.stamp_tax_exemption)],
    [pn.stampTax, money(line.stamp_tax), true],
  ];
  const netLines: Line[] = [
    [pn.netPay, money(line.net_pay), true],
    ...(positive(line.bes_deduction)
      ? ([[pn.besDeduction(formatNumber(values.bes_rate)), minus(line.bes_deduction)]] as Line[])
      : []),
    ...deductions.map((item): Line => [itemLabel(item), minus(item.amount)]),
    [pn.payable, money(line.payable), true],
  ];
  const employer: Line[] = [
    [pn.employerSgk(formatNumber(values.employer_sgk_rate)), money(line.employer_sgk_gross)],
    [pn.incentive(formatNumber(values.incentive_points)), minus(line.incentive)],
    [
      pn.employerUnemployment(formatNumber(values.employer_unemployment_rate)),
      money(line.employer_unemployment),
    ],
    ...(positive(line.floor_gap) ? ([[pn.floorGap, money(line.floor_gap)]] as Line[]) : []),
    [pn.employerCost, money(line.employer_cost), true],
  ];
  return (
    <Stack>
      <Section title={pn.sectionDays} lines={days} />
      <Section title={pn.sectionEarnings} lines={earnings} />
      <Section title={pn.sectionSgk} lines={sgk} />
      {payroll.net && (
        <>
          <Section title={pn.sectionIncomeTax} lines={incomeTax} />
          {crossed && (
            <Text size="xs" c="dimmed">
              {pn.bracketCrossed}
            </Text>
          )}
          <Section title={pn.sectionStamp} lines={stamp} />
          <Section title={pn.sectionDeductions} lines={netLines} />
        </>
      )}
      <Section title={pn.sectionEmployer} lines={employer} />
      {payroll.net && <Chain payroll={payroll} row={row} />}
    </Stack>
  );
}

function Chain({ payroll, row }: { payroll: PayrollMonth; row: PayrollRow }) {
  const source = (kind: string, month: number) => {
    if (kind === "opening") return pn.chainOpening(monthLabel(payroll.year, month));
    if (kind === "external") return pn.chainExternal;
    return pn.chainErp;
  };
  return (
    <Stack gap={4}>
      <Title order={6}>{pn.sectionChain}</Title>
      {!row.carry_months.length ? (
        <Text size="sm" c="dimmed">
          {pn.chainEmpty}
        </Text>
      ) : (
        <Table withTableBorder verticalSpacing={4}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{pn.chainMonth}</Table.Th>
              <Table.Th>{pn.chainSource}</Table.Th>
              <Table.Th ta="right">{pn.chainTaxBase}</Table.Th>
              <Table.Th ta="right">{pn.chainExemption}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {row.carry_months.map((link, index) => (
              <Table.Tr key={index}>
                <Table.Td>{monthLabel(payroll.year, link.month)}</Table.Td>
                <Table.Td>
                  {source(link.kind, link.month)}
                  {link.flags.map((flag) => (
                    <Badge key={flag} color="orange" variant="light" size="xs" ml={6} tt="none">
                      {pn.chainFlags[flag] ?? flag}
                    </Badge>
                  ))}
                </Table.Td>
                <Table.Td ta="right">{money(link.tax_base)}</Table.Td>
                <Table.Td ta="right">{money(link.exemption_base)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function ItemsTab({
  row,
  future,
  onAdd,
  onEdit,
  onRemove,
}: {
  row: PayrollRow;
  /** Gelecek ay: kalem girilemez (birlikte ödendiği ücretin ayı gelince girilir). */
  future: boolean;
  onAdd: () => void;
  onEdit: (item: PayrollItemRecord) => void;
  onRemove: (item: PayrollItemRecord) => void;
}) {
  return (
    <Stack>
      <Group justify="flex-end" gap="xs">
        {future && (
          <Text size="xs" c="dimmed">
            {pn.futureItemsHint}
          </Text>
        )}
        <Button size="compact-sm" onClick={onAdd} disabled={future}>
          {pn.addItem}
        </Button>
      </Group>
      {!row.items.length ? (
        <Text size="sm" c="dimmed">
          {pn.itemsEmpty}
        </Text>
      ) : (
        <Table withTableBorder verticalSpacing={4}>
          <Table.Tbody>
            {row.items.map((item) => (
              <Table.Tr key={item.id}>
                <Table.Td>
                  <Text size="sm">{itemLabel(item)}</Text>
                  <Text size="xs" c="dimmed">
                    {pn.enteredAt(item.updated_by_name ?? "—", formatDateTime(item.updated_at))}
                  </Text>
                </Table.Td>
                <Table.Td ta="right">
                  {item.kind === "DEDUCTION" ? minus(item.amount) : money(item.amount)}
                </Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end" wrap="nowrap">
                    <Button
                      size="compact-xs"
                      variant="light"
                      aria-label={pn.itemAction(pn.editItem, itemLabel(item), money(item.amount))}
                      onClick={() => onEdit(item)}
                    >
                      {pn.editItem}
                    </Button>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      color="red"
                      aria-label={pn.itemAction(pn.removeItem, itemLabel(item), money(item.amount))}
                      onClick={() => onRemove(item)}
                    >
                      {pn.removeItem}
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

function OpeningTab({
  payroll,
  row,
  onOpening,
  onRemove,
}: {
  payroll: PayrollMonth;
  row: PayrollRow;
  onOpening: (month: number) => void;
  onRemove: (opening: PayrollOpening) => void;
}) {
  const opening = row.opening;
  // Gelecek aya devir girilmez (bir önceki ayın kümülatifi o ay bitince belli olur).
  const future = isFutureMonth(payroll.year, payroll.month);
  const entryFuture = row.entry_month !== null && isFutureMonth(payroll.year, row.entry_month);
  const canReanchor =
    !future &&
    payroll.month !== opening?.month &&
    payroll.month !== row.entry_month &&
    monthsEmployedBefore(row.employee, payroll.year, payroll.month) > 0;
  return (
    <Stack>
      {row.opening_needed && row.entry_month !== null && (
        <Alert color="red" variant="light" icon={<IconAlertTriangle size={18} />}>
          <Group justify="space-between" gap="xs">
            <Text size="sm">{pn.warningHelp.opening_missing}</Text>
            <Button
              size="compact-sm"
              disabled={entryFuture}
              onClick={() => onOpening(row.entry_month as number)}
            >
              {pn.openingEnter}
            </Button>
          </Group>
        </Alert>
      )}
      {opening ? (
        <Section
          title={pn.openingUsed(monthLabel(opening.year, opening.month))}
          lines={[
            [
              pn.openingTaxBase(monthLabel(opening.year, opening.month - 1)),
              money(opening.tax_base),
            ],
            [pn.openingMonths, String(opening.exemption_months)],
            [pn.exemptionBefore, money(opening.exemption_base)],
            [
              pn.itemEnteredBy,
              pn.enteredAt(opening.updated_by_name ?? "—", formatDateTime(opening.updated_at)),
            ],
            ...(opening.note ? ([[pn.openingNote, opening.note]] as Line[]) : []),
          ]}
        />
      ) : (
        <Text size="sm" c="dimmed">
          {pn.openingNone}
        </Text>
      )}
      {(future || entryFuture) && (
        <Text size="xs" c="dimmed">
          {pn.futureOpeningsHint}
        </Text>
      )}
      <Group gap="xs">
        {opening && (
          <>
            <Button size="compact-sm" variant="light" onClick={() => onOpening(opening.month)}>
              {pn.openingEdit}
            </Button>
            <Button
              size="compact-sm"
              variant="subtle"
              color="red"
              onClick={() => onRemove(opening)}
            >
              {pn.removeOpening}
            </Button>
          </>
        )}
        {canReanchor && (
          <Button size="compact-sm" variant="default" onClick={() => onOpening(payroll.month)}>
            {pn.openingReanchor}
          </Button>
        )}
      </Group>
    </Stack>
  );
}

export function PayrollDrawer({
  payroll,
  row,
  order,
  onNavigate,
  onClose,
  onAddItem,
  onEditItem,
  onRemoveItem,
  onOpening,
  onRemoveOpening,
  onFigure,
  covered = false,
}: {
  payroll: PayrollMonth;
  row: PayrollRow;
  /** Tablodaki sıra (önceki / sonraki kişi). */
  order: PayrollRow[];
  onNavigate: (row: PayrollRow) => void;
  onClose: () => void;
  onAddItem: (row: PayrollRow) => void;
  onEditItem: (item: PayrollItemRecord) => void;
  onRemoveItem: (item: PayrollItemRecord) => void;
  onOpening: (month: number, row: PayrollRow) => void;
  onRemoveOpening: (opening: PayrollOpening) => void;
  onFigure: (row: PayrollRow) => void;
  /** Dökümün üstünde bir pencere açık: Esc ve ok tuşları o pencereye aittir. */
  covered?: boolean;
}) {
  const index = order.findIndex((item) => item.employee.id === row.employee.id);
  const previous = index > 0 ? order[index - 1] : null;
  const next = index >= 0 && index < order.length - 1 ? order[index + 1] : null;
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (covered || event.defaultPrevented) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      // Sekme başlıkları ok tuşlarıyla sekme değiştirir.
      if (target?.closest?.('[role="tablist"]')) return;
      if (event.key === "ArrowLeft" && previous) onNavigate(previous);
      if (event.key === "ArrowRight" && next) onNavigate(next);
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [covered, previous, next, onNavigate]);
  return (
    <Drawer
      opened
      onClose={onClose}
      position="right"
      size="xl"
      closeOnEscape={!covered}
      title={pn.drawerTitle(row.employee.full_name, payroll.period_label)}
    >
      <Stack>
        <Group justify="space-between" wrap="nowrap">
          <Button
            variant="default"
            size="compact-sm"
            disabled={!previous}
            onClick={() => previous && onNavigate(previous)}
          >
            {pn.previous}
          </Button>
          <Group gap={4} wrap="wrap" justify="center">
            {row.warnings.map((code) => (
              <Tooltip
                key={code}
                label={warningHelp(code) ?? warningLabel(code)}
                multiline
                w={280}
                events={{ hover: true, focus: true, touch: true }}
              >
                <Badge color="orange" variant="light" tt="none" tabIndex={0}>
                  {warningLabel(code)}
                </Badge>
              </Tooltip>
            ))}
          </Group>
          <Button
            variant="default"
            size="compact-sm"
            disabled={!next}
            onClick={() => next && onNavigate(next)}
          >
            {pn.next}
          </Button>
        </Group>
        {row.external ? (
          <Stack>
            <Alert color="violet" variant="light">
              <Text size="sm">{pn.externalDrawer}</Text>
            </Alert>
            {row.figure && (
              <Section
                title={py.external}
                lines={[
                  [py.figureGross, money(row.figure.gross_total)],
                  [py.figureCost, money(row.figure.employer_cost), true],
                ]}
              />
            )}
            <Group>
              <Button onClick={() => onFigure(row)}>
                {row.figure ? py.editFigures : py.enterFigures}
              </Button>
            </Group>
          </Stack>
        ) : (
          <Tabs defaultValue="calc" keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="calc">{pn.tabCalc}</Tabs.Tab>
              {payroll.net && (
                <Tabs.Tab value="items">
                  {pn.tabItems}
                  {row.items.length ? ` (${row.items.length})` : ""}
                </Tabs.Tab>
              )}
              {payroll.net && <Tabs.Tab value="opening">{pn.tabOpening}</Tabs.Tab>}
            </Tabs.List>
            <Tabs.Panel value="calc" pt="md">
              <Breakdown payroll={payroll} row={row} />
            </Tabs.Panel>
            <Tabs.Panel value="items" pt="md">
              <ItemsTab
                row={row}
                future={isFutureMonth(payroll.year, payroll.month)}
                onAdd={() => onAddItem(row)}
                onEdit={onEditItem}
                onRemove={onRemoveItem}
              />
            </Tabs.Panel>
            <Tabs.Panel value="opening" pt="md">
              <OpeningTab
                payroll={payroll}
                row={row}
                onOpening={(month) => onOpening(month, row)}
                onRemove={onRemoveOpening}
              />
            </Tabs.Panel>
          </Tabs>
        )}
      </Stack>
    </Drawer>
  );
}
