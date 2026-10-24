import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  NavLink,
  Paper,
  Progress,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import {
  IconAlertOctagon,
  IconAlertTriangle,
  IconArrowRight,
  IconChartBar,
  IconChevronRight,
  IconCircleCheck,
  IconClockExclamation,
  IconFirstAidKit,
  IconFlask,
  IconInfoCircle,
  IconShoppingCart,
  IconTable,
  type Icon,
} from "@tabler/icons-react";
import { Fragment, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type {
  DailyOutput,
  LabDashboard,
  ManagementDashboard,
  ProductionDashboard,
  ProductionPeriod,
  QueueOrder,
  ShippingDashboard,
  StatusCount,
  WarehouseDashboard,
} from "../../api/reporting";
import type { Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatNumber,
  TIME_ZONE,
} from "../../i18n/format";
import { menuRoles } from "../../layout/menu";
import { formatMinutes } from "../maintenance/strings";
import { ORDER_READ_ROLES } from "../purchasing/config";
import { APPROVAL_ROLES } from "../quality/config";
import { RECORD_ROUTES } from "../../workflow/recordLinks";
import { BarChart } from "./BarChart";
import { rt } from "./strings";

const link = (model: string, id: number, text: string) => (
  <Link to={RECORD_ROUTES[model](id)}>{text}</Link>
);

const hoursText = (value: string | null) =>
  value === null ? "—" : rt.hours(formatNumber(value, 1));
const pctText = (value: string | null) => (value === null ? "—" : `%${formatNumber(value, 2)}`);

/** Bekleme / gecikme: iki günden kısası saat (10 saatin altında bir ondalık), uzunu gün. */
function waitText(value: string | null): string {
  if (value === null) return "—";
  const hours = Number(value);
  if (hours >= 48) return rt.days(formatNumber(Math.round(hours / 24)));
  return rt.hours(formatNumber(hours < 10 ? Math.round(hours * 10) / 10 : Math.round(hours)));
}

/** Bağlantı yalnızca hedef sayfayı açabilen role gösterilir; asıl yetki backend'dedir. */
interface Target {
  to: string;
  roles: readonly Role[];
}

export function Stat({
  label,
  value,
  detail,
  color,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  color?: string;
}) {
  return (
    <Paper withBorder p="md" radius="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text fz={26} fw={700} c={color}>
        {value}
      </Text>
      {detail && (
        <Text size="sm" c="dimmed">
          {detail}
        </Text>
      )}
    </Paper>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Title order={4} mb="sm">
        {title}
      </Title>
      {children}
    </Paper>
  );
}

function Empty() {
  return (
    <Text size="sm" c="dimmed">
      {rt.none}
    </Text>
  );
}

function SimpleTable({
  head,
  rows,
  minWidth = 480,
}: {
  head: string[];
  rows: ReactNode[][];
  minWidth?: number;
}) {
  if (rows.length === 0) return <Empty />;
  return (
    <Table.ScrollContainer minWidth={minWidth}>
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            {head.map((h) => (
              <Table.Th key={h}>{h}</Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((cells, index) => (
            <Table.Tr key={index}>
              {cells.map((cell, i) => (
                <Table.Td key={i}>{cell}</Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function periodText(period: ProductionPeriod) {
  if (period.bulk.length === 0) return "0";
  return period.bulk.map((b) => `${formatNumber(b.quantity, 0)} ${b.unit}`).join(" + ");
}

function batchCount(period: ProductionPeriod) {
  return period.bulk.reduce((sum, b) => sum + b.batches, 0);
}

function OutputStats({ output }: { output: ManagementDashboard["production"] }) {
  return (
    <>
      <Stat
        label={`${rt.bulkOutput} — ${rt.today}`}
        value={periodText(output.today)}
        detail={rt.batches(batchCount(output.today))}
      />
      <Stat
        label={`${rt.bulkOutput} — ${rt.thisWeek}`}
        value={periodText(output.week)}
        detail={rt.batches(batchCount(output.week))}
      />
      <Stat
        label={`${rt.units} — ${rt.today}`}
        value={formatNumber(output.today.units)}
        detail={rt.runs(output.today.runs ?? 0)}
      />
      <Stat
        label={`${rt.units} — ${rt.thisWeek}`}
        value={formatNumber(output.week.units)}
        detail={rt.runs(output.week.runs ?? 0)}
      />
    </>
  );
}

// --- yönetim ----------------------------------------------------------------------------------

/** QC'de bu kadar saatten uzun bekleyen numune "dikkat gerektirenler"e düşer. */
const QC_WAIT_WARNING_HOURS = 24;

function ApprovalCard({
  icon: CardIcon,
  title,
  value,
  detail,
  waiting,
  target,
  action,
}: {
  icon: Icon;
  title: string;
  value: string;
  detail?: string;
  waiting: boolean;
  target: Target;
  action: string;
}) {
  const { user } = useAuth();
  return (
    <Paper
      withBorder
      p="md"
      radius="md"
      // Bekleyen varsa kart vurgulanır (durum rengi değil, "sırada iş var" işareti).
      style={waiting ? { borderColor: "var(--mantine-primary-color-filled)" } : undefined}
    >
      <Group gap={6} wrap="nowrap">
        <CardIcon size={16} color="var(--mantine-color-dimmed)" />
        <Text size="sm" c="dimmed">
          {title}
        </Text>
      </Group>
      <Text fz={24} fw={700}>
        {value}
      </Text>
      {detail && (
        <Text size="sm" c="dimmed">
          {detail}
        </Text>
      )}
      {waiting && hasAnyRole(user, target.roles) && (
        <Anchor component={Link} to={target.to} size="sm" mt="xs" display="inline-block">
          <Group gap={4} wrap="nowrap">
            {action}
            <IconArrowRight size={14} />
          </Group>
        </Anchor>
      )}
    </Paper>
  );
}

function Approvals({ data }: { data: ManagementDashboard }) {
  const { conditional_acceptance: decisions, purchase_orders: orders } = data.approvals;
  const { hse } = data;
  // TL toplamı yalnızca tutar görebilene döner (D-15); diğer rollerde yalnızca sayı.
  const orderDetail = !orders.count
    ? rt.nothingWaiting
    : orders.total_try === null
      ? undefined
      : `${formatMoney(orders.total_try)} TL`;
  return (
    <SimpleGrid cols={{ base: 1, sm: 3 }}>
      <ApprovalCard
        icon={IconFlask}
        title={rt.conditionalAcceptance}
        value={rt.decisions(decisions.count)}
        detail={
          decisions.count
            ? rt.oldestWaiting(waitText(decisions.oldest_wait_hours))
            : rt.nothingWaiting
        }
        waiting={decisions.count > 0}
        target={{ to: "/kalite/onay", roles: APPROVAL_ROLES }}
        action={rt.openDecisions}
      />
      <ApprovalCard
        icon={IconShoppingCart}
        title={rt.purchaseApproval}
        value={rt.orders(orders.count)}
        detail={orderDetail}
        waiting={orders.count > 0}
        target={{ to: "/satin-alma/siparisler", roles: ORDER_READ_ROLES }}
        action={rt.openPurchaseOrders}
      />
      <ApprovalCard
        icon={IconFirstAidKit}
        title={rt.openIncidents}
        value={rt.incidentCount(hse.open_incidents)}
        detail={rt.incidentSummary(hse.days, hse.incidents, hse.injuries)}
        waiting={hse.open_incidents > 0}
        target={{ to: "/isg/olaylar", roles: menuRoles("hse") }}
        action={rt.openIncidentList}
      />
    </SimpleGrid>
  );
}

type Severity = "critical" | "warning";

const SEVERITY: Record<Severity, { color: string; icon: Icon }> = {
  critical: { color: "red", icon: IconAlertOctagon },
  warning: { color: "orange", icon: IconAlertTriangle },
};

interface AttentionItem {
  key: string;
  severity: Severity;
  text: string;
  target?: Target;
}

/** Dikkat gerektirenler: önce kritikler, sonra uyarılar; her satır ilgili listeye götürür. */
function attentionItems(data: ManagementDashboard): AttentionItem[] {
  const { critical_stock: stock, expiring_lots: lots, hse, tasks, maintenance } = data;
  const items: AttentionItem[] = [];
  const add = (condition: unknown, item: AttentionItem) => {
    if (condition) items.push(item);
  };
  const inventory = menuRoles("inventory");
  add(stock.count, {
    key: "stock",
    severity: "critical",
    text: rt.attn.criticalStock(stock.count),
    target: { to: "/depo/stok", roles: inventory },
  });
  add(lots.expired_count, {
    key: "expired",
    severity: "critical",
    text: rt.attn.expiredLots(lots.expired_count),
    target: { to: "/depo/lotlar", roles: inventory },
  });
  add(hse.injuries, {
    key: "injuries",
    severity: "critical",
    text: rt.attn.injuries(hse.injuries, hse.days),
    target: { to: "/isg/olaylar", roles: menuRoles("hse") },
  });
  const longest = tasks.by_role
    .filter((r) => r.max_delay_hours !== null)
    .sort((a, b) => Number(b.max_delay_hours) - Number(a.max_delay_hours))[0];
  add(tasks.overdue_total, {
    key: "tasks",
    severity: "warning",
    text: rt.attn.overdueTasks(
      tasks.overdue_total,
      longest ? `${waitText(longest.max_delay_hours)} (${longest.label})` : "",
    ),
  });
  add(data.shipping.late_orders, {
    key: "late-orders",
    severity: "warning",
    text: rt.attn.lateOrders(data.shipping.late_orders),
    target: { to: "/sevkiyat/siparisler", roles: menuRoles("sales") },
  });
  add(maintenance.open_downtimes, {
    key: "downtimes",
    severity: "warning",
    text: rt.attn.downtimes(maintenance.open_downtimes),
    target: { to: "/bakim/duruslar", roles: menuRoles("maintenance") },
  });
  add(maintenance.overdue_plans, {
    key: "plans",
    severity: "warning",
    text: rt.attn.overduePlans(maintenance.overdue_plans),
    target: { to: "/bakim/planlar", roles: menuRoles("maintenance") },
  });
  const qcWait = data.qc_pending.max_wait_hours;
  add(qcWait !== null && Number(qcWait) >= QC_WAIT_WARNING_HOURS, {
    key: "qc",
    severity: "warning",
    text: rt.attn.qcWait(waitText(qcWait)),
    target: { to: "/kalite/numuneler", roles: menuRoles("quality") },
  });
  return items;
}

function AttentionList({ items }: { items: AttentionItem[] }) {
  const { user } = useAuth();
  if (items.length === 0) {
    return (
      <Paper withBorder p="md" radius="md">
        <Group gap="xs" wrap="nowrap">
          <IconCircleCheck size={20} color="var(--mantine-color-teal-7)" />
          <Text size="sm" fw={700} c="teal.8">
            {rt.severity.ok}
          </Text>
          <Text size="sm">{rt.allClear}</Text>
        </Group>
      </Paper>
    );
  }
  return (
    <Paper withBorder p={4} radius="md">
      {items.map((item) => {
        const { color, icon: SeverityIcon } = SEVERITY[item.severity];
        // Durum rengi her zaman simge ve etiketle birlikte (yalnız renge dayanmaz).
        const badge = (
          <Group gap={6} wrap="nowrap" w={76}>
            <SeverityIcon size={18} color={`var(--mantine-color-${color}-7)`} />
            <Text size="xs" fw={700} c={`${color}.8`}>
              {rt.severity[item.severity]}
            </Text>
          </Group>
        );
        if (item.target && hasAnyRole(user, item.target.roles)) {
          return (
            <NavLink
              key={item.key}
              component={Link}
              to={item.target.to}
              label={item.text}
              leftSection={badge}
              rightSection={<IconChevronRight size={16} />}
              style={{ borderRadius: 6 }}
            />
          );
        }
        return (
          <Group key={item.key} gap="sm" px={12} py={8} wrap="nowrap">
            {badge}
            <Text size="sm">{item.text}</Text>
          </Group>
        );
      })}
    </Paper>
  );
}

function TodayStats({ data }: { data: ManagementDashboard }) {
  const { production: output, qc_pending: qc, shipping } = data;
  const pieces = (units: number) => rt.pieces(formatNumber(units));
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
      <Stat
        label={rt.bulkProduction}
        value={periodText(output.today)}
        detail={rt.weekTotal(periodText(output.week))}
      />
      <Stat
        label={rt.finished}
        value={pieces(output.today.units)}
        detail={rt.weekTotal(pieces(output.week.units))}
      />
      <Stat
        label={rt.dispatched}
        value={rt.shipments(shipping.dispatched_today)}
        detail={rt.lateOrderCount(shipping.late_orders)}
      />
      <Stat
        label={rt.qcPending}
        value={rt.lots(qc.lot_count)}
        detail={
          qc.lot_count
            ? rt.waitSummary(waitText(qc.avg_wait_hours), waitText(qc.max_wait_hours))
            : rt.noSamples
        }
      />
    </SimpleGrid>
  );
}

const UNITS_SERIES = "units";
const WEEKDAY = new Intl.DateTimeFormat("tr-TR", { weekday: "long", timeZone: TIME_ZONE });

/** Seçilebilir seriler: her dökme birimi (en çok üretilen önce) ve mamul adedi; birimler karışmaz. */
function seriesOptions(daily: DailyOutput[]) {
  const totals = new Map<string, number>();
  for (const day of daily) {
    for (const b of day.bulk) totals.set(b.unit, (totals.get(b.unit) ?? 0) + Number(b.quantity));
  }
  const units = [...totals.keys()].sort((a, b) => totals.get(b)! - totals.get(a)!);
  return [
    ...(units.length ? units : [""]).map((unit) => ({
      value: `bulk:${unit}`,
      label: rt.bulkSeries(unit),
      unit,
    })),
    { value: UNITS_SERIES, label: rt.unitsSeries, unit: rt.pieceUnit },
  ];
}

function DailyOutputChart({ daily }: { daily: DailyOutput[] }) {
  const options = seriesOptions(daily);
  const [selected, setSelected] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);
  const series = options.find((o) => o.value === selected) ?? options[0];
  const points = daily.map((day) => ({
    label: `${day.date.slice(8, 10)}.${day.date.slice(5, 7)}`,
    title: `${formatDate(day.date)} ${WEEKDAY.format(new Date(`${day.date}T12:00:00Z`))}`,
    value:
      series.value === UNITS_SERIES
        ? day.units
        : Number(day.bulk.find((b) => b.unit === series.unit)?.quantity ?? 0),
  }));
  const amount = (value: number) =>
    series.unit ? `${formatNumber(value, 0)} ${series.unit}` : formatNumber(value, 0);
  const total = points.reduce((sum, p) => sum + p.value, 0);
  const peak = points.reduce((best, p) => (p.value > best.value ? p : best), points[0]);
  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" align="flex-start" mb="sm" gap="xs">
        <div>
          <Title order={4}>{rt.daily(daily.length)}</Title>
          <Text size="sm" c="dimmed">
            {rt.periodTotal(amount(total))}
          </Text>
        </div>
        <Group gap="xs">
          <SegmentedControl
            size="xs"
            value={series.value}
            onChange={setSelected}
            data={options.map((o) => ({ value: o.value, label: o.label }))}
          />
          <Button
            variant="subtle"
            size="xs"
            leftSection={asTable ? <IconChartBar size={14} /> : <IconTable size={14} />}
            onClick={() => setAsTable((value) => !value)}
          >
            {asTable ? rt.showChart : rt.showTable}
          </Button>
        </Group>
      </Group>
      {total === 0 ? (
        <Text size="sm" c="dimmed">
          {rt.noOutput}
        </Text>
      ) : asTable ? (
        <SimpleTable
          head={[rt.day, series.label]}
          rows={points.map((p) => [p.title, amount(p.value)])}
          minWidth={280}
        />
      ) : (
        <BarChart
          points={points}
          unit={series.unit}
          summary={rt.chartSummary(
            series.label,
            points.length,
            amount(total),
            `${peak.title}, ${amount(peak.value)}`,
          )}
        />
      )}
    </Paper>
  );
}

const TRACK = "var(--mantine-color-default-hover)";

function StockValueCard({ value }: { value: NonNullable<ManagementDashboard["stock_value"]> }) {
  const types = [...value.by_type].sort((a, b) => Number(b.value) - Number(a.value));
  const max = Math.max(0, ...types.map((t) => Number(t.value)));
  return (
    <Section title={rt.stockValue}>
      <Text fz={26} fw={700}>
        {formatMoney(value.total)} TL
      </Text>
      <Stack gap={6} mt="sm">
        {types.map((t) => (
          <Group key={t.material_type} gap="sm" wrap="nowrap">
            <Text size="sm" c="dimmed" w={84}>
              {rt.materialType_[t.material_type] ?? t.material_type}
            </Text>
            <div style={{ flex: 1, height: 8, borderRadius: 4, background: TRACK }}>
              <div
                style={{
                  width: `${max ? (Number(t.value) / max) * 100 : 0}%`,
                  height: 8,
                  borderRadius: 4,
                  background: "var(--mantine-primary-color-filled)",
                }}
              />
            </div>
            <Text size="sm" w={130} ta="right" style={{ fontVariantNumeric: "tabular-nums" }}>
              {formatMoney(t.value)} TL
            </Text>
          </Group>
        ))}
      </Stack>
      {value.has_uncosted && (
        <Group gap={4} mt="sm" wrap="nowrap">
          <IconInfoCircle size={14} color="var(--mantine-color-dimmed)" />
          <Text size="xs" c="dimmed">
            {rt.uncosted}
          </Text>
        </Group>
      )}
    </Section>
  );
}

function LossCard({ scrap, maintenance }: Pick<ManagementDashboard, "scrap" | "maintenance">) {
  return (
    <Section title={rt.lossTitle(scrap.days)}>
      <SimpleGrid cols={2}>
        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            {rt.scrap}
          </Text>
          <Text fz={24} fw={700}>
            {pctText(scrap.rate)}
          </Text>
          <Text size="sm" c="dimmed">
            {rt.scrapDetail(formatNumber(scrap.scrap_units), formatNumber(scrap.good_units))}
          </Text>
        </div>
        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            {rt.downtime}
          </Text>
          <Text fz={24} fw={700}>
            {formatMinutes(maintenance.downtime_minutes)}
          </Text>
          <Text size="sm" c="dimmed">
            {rt.openWorkOrders(maintenance.open_work_orders)} ·{" "}
            {rt.overduePlans(maintenance.overdue_plans)}
          </Text>
        </div>
      </SimpleGrid>
    </Section>
  );
}

function WorkloadCard({ tasks }: { tasks: ManagementDashboard["tasks"] }) {
  return (
    <Section title={rt.workload}>
      <SimpleTable
        head={[rt.unit, rt.openTasks, rt.overdue, rt.maxDelay]}
        minWidth={320}
        rows={tasks.by_role.map((r) => [
          r.label,
          r.open,
          r.overdue ? (
            <Group gap={4} wrap="nowrap">
              <IconClockExclamation size={14} color="var(--mantine-color-red-7)" />
              <Text c="red.8" fw={700} size="sm">
                {r.overdue}
              </Text>
            </Group>
          ) : (
            0
          ),
          waitText(r.max_delay_hours),
        ])}
      />
    </Section>
  );
}

function Pipeline({
  label,
  counts,
  target,
}: {
  label: string;
  counts: StatusCount[];
  target: Target;
}) {
  const { user } = useAuth();
  const open = counts.filter((c) => c.count > 0);
  return (
    <Group gap={6}>
      <Text size="sm" w={130}>
        {hasAnyRole(user, target.roles) ? (
          <Anchor component={Link} to={target.to} size="sm">
            {label}
          </Anchor>
        ) : (
          label
        )}
      </Text>
      {open.length === 0 ? (
        <Text size="sm" c="dimmed">
          {rt.noOpenOrders}
        </Text>
      ) : (
        open.map((c, i) => (
          <Fragment key={c.status}>
            {i > 0 && <IconChevronRight size={14} color="var(--mantine-color-dimmed)" />}
            <Badge variant="light" color="gray" size="lg" tt="none" fw={500}>
              {c.label} {c.count}
            </Badge>
          </Fragment>
        ))
      )}
    </Group>
  );
}

export function ManagementView({ data }: { data: ManagementDashboard }) {
  const { user } = useAuth();
  const { critical_stock: critical, expiring_lots: expiring, open_orders: orders } = data;
  return (
    <Stack gap="lg">
      <Stack gap="xs">
        <Title order={4}>
          {hasAnyRole(user, APPROVAL_ROLES) ? rt.approvalsMine : rt.approvalsOthers}
        </Title>
        <Approvals data={data} />
      </Stack>
      <Stack gap="xs">
        <Title order={4}>{rt.attention}</Title>
        <AttentionList items={attentionItems(data)} />
      </Stack>
      <Stack gap="xs">
        <Title order={4}>{rt.today}</Title>
        <TodayStats data={data} />
      </Stack>
      <DailyOutputChart daily={data.daily} />
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Stack>
          {data.stock_value && <StockValueCard value={data.stock_value} />}
          <LossCard scrap={data.scrap} maintenance={data.maintenance} />
        </Stack>
        <WorkloadCard tasks={data.tasks} />
      </SimpleGrid>
      <Section title={rt.openOrders}>
        <Stack gap="sm">
          <Pipeline
            label={rt.productionOrders}
            counts={orders.production}
            target={{ to: "/uretim/emirler", roles: menuRoles("production") }}
          />
          <Pipeline
            label={rt.fillingOrders}
            counts={orders.filling}
            target={{ to: "/dolum/emirler", roles: menuRoles("filling") }}
          />
          <Pipeline
            label={rt.salesOrders}
            counts={orders.sales}
            target={{ to: "/sevkiyat/siparisler", roles: menuRoles("sales") }}
          />
        </Stack>
      </Section>
      <Section title={rt.criticalStock}>
        <SimpleTable
          head={[rt.material, rt.stock, rt.minStock]}
          minWidth={360}
          rows={critical.items.map((m) => [
            m.material,
            `${formatNumber(m.stock)} ${m.unit}`,
            `${formatNumber(m.min_stock)} ${m.unit}`,
          ])}
        />
        {critical.count > critical.items.length && (
          <Text size="sm" c="dimmed">
            {rt.more(critical.count - critical.items.length)}
          </Text>
        )}
      </Section>
      <Section title={rt.expiringLots(expiring.days)}>
        {expiring.expired_count > 0 && (
          <Alert color="red" variant="light" mb="sm">
            {rt.expiredCount(expiring.expired_count)}
          </Alert>
        )}
        <SimpleTable
          head={[rt.lotNo, rt.material, rt.expiry, rt.daysLeft, rt.quantity, rt.status]}
          rows={expiring.items.map((lot) => [
            link("inventory.lot", lot.lot_id, lot.lot_no),
            lot.material,
            formatDate(lot.expiry_date),
            lot.days_left !== null && lot.days_left < 0 ? (
              <Text c="red" size="sm" fw={600}>
                {lot.days_left}
              </Text>
            ) : (
              lot.days_left
            ),
            `${formatNumber(lot.quantity)} ${lot.unit}`,
            lot.status,
          ])}
        />
        {expiring.count > expiring.items.length && (
          <Text size="sm" c="dimmed">
            {rt.more(expiring.count - expiring.items.length)}
          </Text>
        )}
      </Section>
    </Stack>
  );
}

// --- depo -------------------------------------------------------------------------------------

function queueRows(orders: QueueOrder[], model: string) {
  return orders.map((o) => [
    link(model, o.id, o.number),
    o.product ?? o.customer ?? "",
    <Group gap={4} key="date">
      {formatDate(o.planned_date)}
      {o.late && (
        <Badge color="red" size="xs">
          {rt.late}
        </Badge>
      )}
    </Group>,
    o.status_display,
  ]);
}

export function WarehouseView({ data }: { data: WarehouseDashboard }) {
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        <Stat
          label={rt.depoTasks}
          value={data.tasks.open}
          detail={`${rt.overdue}: ${data.tasks.overdue}`}
          color={data.tasks.overdue ? "red" : undefined}
        />
        <Stat label={rt.draftReceipts} value={data.draft_receipts} />
        <Stat label={rt.expiringLots(30)} value={data.expiring_lot_count} />
        <Stat label={rt.criticalStock} value={data.critical_stock_count} />
      </SimpleGrid>
      <Section title={rt.productionPrep}>
        <SimpleTable
          head={[rt.number, rt.product, rt.plannedDate, rt.status]}
          rows={queueRows(data.production_prep, "production.productionorder")}
        />
      </Section>
      <Section title={rt.fillingPrep}>
        <SimpleTable
          head={[rt.number, rt.product, rt.plannedDate, rt.status]}
          rows={queueRows(data.filling_prep, "filling.fillingorder")}
        />
      </Section>
      <Section title={rt.shipmentPicking}>
        <SimpleTable
          head={[rt.number, rt.customer, rt.plannedDate, rt.status]}
          rows={queueRows(data.shipment_picking, "sales.shipment")}
        />
      </Section>
    </Stack>
  );
}

// --- laboratuvar ------------------------------------------------------------------------------

export function LabView({ data }: { data: LabDashboard }) {
  const month = data.last_30_days;
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        <Stat
          label={rt.qcPending}
          value={rt.samples(data.summary.sample_count)}
          detail={rt.lots(data.summary.lot_count)}
        />
        <Stat
          label={rt.avgWait}
          value={hoursText(data.summary.avg_wait_hours)}
          detail={`${rt.maxWait}: ${hoursText(data.summary.max_wait_hours)}`}
        />
        <Stat label={rt.decidedToday} value={data.decided_today} />
        <Stat
          label={rt.rejection30}
          value={pctText(month.rejection_rate)}
          detail={rt.rejectionDetail(month.rejected, month.decided)}
        />
      </SimpleGrid>
      {data.by_stage.length > 0 && (
        <Group>
          <Text size="sm" fw={600}>
            {rt.byStage}:
          </Text>
          {data.by_stage.map((s) => (
            <Badge key={s.stage} variant="light">
              {s.label}: {s.count}
            </Badge>
          ))}
        </Group>
      )}
      <Section title={rt.sampleQueue}>
        <SimpleTable
          head={[rt.number, rt.stage, rt.lotNo, rt.material, rt.status, rt.wait]}
          rows={data.queue.map((s) => [
            link("quality.sample", s.id, s.number),
            s.stage,
            s.lot_no,
            s.material,
            s.status_display,
            hoursText(s.wait_hours),
          ])}
        />
        {data.queue_truncated && (
          <Text size="sm" c="dimmed" mt="xs">
            {rt.queueTruncated}
          </Text>
        )}
      </Section>
    </Stack>
  );
}

// --- üretim -----------------------------------------------------------------------------------

const TANK_COLORS = { IN_BATCH: "blue", FILLED: "teal", EMPTY: "gray" } as const;

export function ProductionView({ data }: { data: ProductionDashboard }) {
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        <OutputStats output={data.output} />
      </SimpleGrid>
      <Title order={4}>{rt.tanks}</Title>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        {data.tanks.map((tank) => {
          const fill = tank.fill_pct === null ? null : Math.min(Number(tank.fill_pct), 100);
          return (
            <Paper key={tank.id} withBorder p="md" radius="md">
              <Group justify="space-between">
                <Text fw={700}>{tank.code}</Text>
                <Badge color={TANK_COLORS[tank.state]}>{tank.state_display}</Badge>
              </Group>
              <Text size="sm" c="dimmed">
                {tank.name}
              </Text>
              {fill !== null && (
                <Stack gap={2} mt="xs">
                  <Group justify="space-between">
                    <Text size="xs">{rt.fill}</Text>
                    <Text size="xs">
                      %{formatNumber(tank.fill_pct, 0)} · {formatNumber(tank.capacity)}{" "}
                      {tank.capacity_unit}
                    </Text>
                  </Group>
                  <Progress value={fill} />
                </Stack>
              )}
              {tank.downtime && (
                <Text size="sm" mt="xs" c="red">
                  {rt.tankDown(
                    tank.downtime.reason_display,
                    formatDateTime(tank.downtime.started_at),
                  )}
                </Text>
              )}
              {tank.batch && (
                <Text size="sm" mt="xs">
                  {link("production.productionbatch", tank.batch.id, tank.batch.batch_no)} ·{" "}
                  {tank.batch.product} · {rt.running(formatNumber(tank.batch.running_hours, 1))}
                </Text>
              )}
              {tank.contents.map((c) => (
                <Text size="sm" key={c.lot_no} mt={4}>
                  {c.lot_no}: {formatNumber(c.quantity)} {c.unit} ({c.lot_status})
                </Text>
              ))}
            </Paper>
          );
        })}
      </SimpleGrid>
      <Section title={rt.activeOrders}>
        <SimpleTable
          head={[rt.number, rt.product, rt.equipment, rt.plannedDate, rt.status]}
          rows={data.orders.map((o) => [
            link("production.productionorder", o.id, o.number),
            o.product,
            o.equipment,
            formatDate(o.planned_date),
            o.status_display,
          ])}
        />
      </Section>
    </Stack>
  );
}

// --- sevkiyat ---------------------------------------------------------------------------------

export function ShippingView({ data }: { data: ShippingDashboard }) {
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        {data.status_counts.map((c) => (
          <Stat key={c.status} label={c.label} value={c.count} />
        ))}
        <Stat label={rt.dispatchedToday} value={data.dispatched_today} />
        <Stat label={rt.waitingOrders} value={data.waiting_orders} />
        <Stat
          label={rt.shortageOrders}
          value={data.shortage_orders}
          color={data.shortage_orders ? "orange" : undefined}
        />
        <Stat
          label={rt.lateOrders}
          value={data.late_orders.length}
          color={data.late_orders.length ? "red" : undefined}
        />
      </SimpleGrid>
      <Section title={rt.todaysShipments}>
        <SimpleTable
          head={[rt.number, rt.customer, rt.orderNumber, rt.plate, rt.status]}
          rows={data.today.map((s) => [
            link("sales.shipment", s.id, s.number),
            s.customer,
            s.order_number,
            s.vehicle_plate,
            s.status_display,
          ])}
        />
      </Section>
      <Section title={rt.lateOrders}>
        <SimpleTable
          head={[rt.number, rt.customer, rt.requested, rt.daysLate, rt.status]}
          rows={data.late_orders.map((o) => [
            link("sales.salesorder", o.id, o.number),
            o.customer,
            formatDate(o.requested_delivery_date),
            o.days_late,
            o.status_display,
          ])}
        />
      </Section>
    </Stack>
  );
}
