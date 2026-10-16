import {
  Alert,
  Badge,
  Group,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type {
  LabDashboard,
  ManagementDashboard,
  ProductionDashboard,
  ProductionPeriod,
  QueueOrder,
  ShippingDashboard,
  StatusCount,
  WarehouseDashboard,
} from "../../api/reporting";
import { formatDate, formatDateTime, formatMoney, formatNumber } from "../../i18n/format";
import { formatMinutes } from "../maintenance/strings";
import { RECORD_ROUTES } from "../../workflow/recordLinks";
import { rt } from "./strings";

const link = (model: string, id: number, text: string) => (
  <Link to={RECORD_ROUTES[model](id)}>{text}</Link>
);

const hoursText = (value: string | null) =>
  value === null ? "—" : rt.hours(formatNumber(value, 1));
const pctText = (value: string | null) => (value === null ? "—" : `%${formatNumber(value, 2)}`);

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

function SimpleTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <Table.ScrollContainer minWidth={480}>
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

function StatusCounts({ title, counts }: { title: string; counts: StatusCount[] }) {
  const total = counts.reduce((sum, c) => sum + c.count, 0);
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text fw={600}>{title}</Text>
        <Badge variant="light">{total}</Badge>
      </Group>
      {counts
        .filter((c) => c.count > 0)
        .map((c) => (
          <Group key={c.status} justify="space-between">
            <Text size="sm">{c.label}</Text>
            <Text size="sm" fw={600}>
              {c.count}
            </Text>
          </Group>
        ))}
      {total === 0 && <Empty />}
    </Stack>
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

export function ManagementView({ data }: { data: ManagementDashboard }) {
  const { qc_pending: qc, scrap, critical_stock: critical, expiring_lots: expiring } = data;
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }}>
        <OutputStats output={data.production} />
        <Stat
          label={rt.qcPending}
          value={rt.lots(qc.lot_count)}
          detail={`${rt.avgWait}: ${hoursText(qc.avg_wait_hours)} · ${rt.maxWait}: ${hoursText(qc.max_wait_hours)}`}
          color={qc.lot_count ? "orange" : undefined}
        />
        <Stat
          label={rt.scrapRate(scrap.days)}
          value={pctText(scrap.rate)}
          detail={rt.scrapDetail(formatNumber(scrap.scrap_units), formatNumber(scrap.good_units))}
        />
        <Stat
          label={rt.criticalStock}
          value={critical.count}
          color={critical.count ? "red" : undefined}
        />
        <Stat
          label={rt.overdueTasks}
          value={data.tasks.overdue_total}
          color={data.tasks.overdue_total ? "red" : undefined}
        />
        <Stat
          label={rt.maintenance}
          value={rt.openWorkOrders(data.maintenance.open_work_orders)}
          detail={`${rt.maintenanceDetail(data.maintenance.overdue_plans, data.maintenance.open_downtimes)} · ${rt.downtimeHours(data.maintenance.days, formatMinutes(data.maintenance.downtime_minutes))}`}
          color={
            data.maintenance.overdue_plans || data.maintenance.open_downtimes ? "orange" : undefined
          }
        />
        <Stat
          label={rt.incidents(data.hse.days)}
          value={data.hse.incidents}
          detail={rt.incidentDetail(data.hse.injuries, data.hse.open_incidents)}
          color={data.hse.injuries ? "red" : undefined}
        />
        {data.stock_value && (
          <Stat
            label={rt.stockValue}
            value={`${formatMoney(data.stock_value.total)} TL`}
            detail={data.stock_value.has_uncosted ? rt.uncosted : undefined}
          />
        )}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Section title={rt.openOrders}>
          <Stack>
            <StatusCounts title={rt.productionOrders} counts={data.open_orders.production} />
            <StatusCounts title={rt.fillingOrders} counts={data.open_orders.filling} />
            <StatusCounts title={rt.salesOrders} counts={data.open_orders.sales} />
          </Stack>
        </Section>
        <Section title={rt.overdueTasks}>
          <SimpleTable
            head={[rt.unit, rt.openTasks, rt.overdue, rt.maxDelay]}
            rows={data.tasks.by_role.map((r) => [
              r.label,
              r.open,
              r.overdue ? (
                <Text c="red" fw={600} size="sm">
                  {r.overdue}
                </Text>
              ) : (
                0
              ),
              hoursText(r.max_delay_hours),
            ])}
          />
        </Section>
        <Section title={rt.criticalStock}>
          <SimpleTable
            head={[rt.material, rt.stock, rt.minStock]}
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
      </SimpleGrid>
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
