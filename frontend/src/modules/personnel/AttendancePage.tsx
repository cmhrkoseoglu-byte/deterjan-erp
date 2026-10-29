// Aylık puantaj (admin ve yönetim): takvimden dolu açılan tablo, gün ve aralık girişi, onay.
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconCalendarPlus,
  IconChevronLeft,
  IconChevronRight,
  IconFileSpreadsheet,
  IconInfoCircle,
  IconLock,
  IconLockOpen,
} from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties } from "react";
import { useSearchParams } from "react-router-dom";
import {
  approveAttendanceMonth,
  attendanceExportUrl,
  attendanceKeys,
  getAttendanceGrid,
  type AttendanceCell,
  type AttendanceColumn,
  type AttendanceGrid,
  type AttendanceRow,
  type AttendanceStatus,
} from "../../api/attendance";
import { getErrorMessage } from "../../api/client";
import { listDepartments } from "../../api/personnel";
import { formatDate, formatDateTime } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { DayModal, RangeModal, ReopenModal } from "./AttendanceModals";
import { formatHours } from "./attendanceFormat";
import { PersonnelTabs } from "./PersonnelTabs";
import { at, ATTENDANCE_BASE, pe, PERSONNEL_KEY } from "./strings";

// Hücre renkleri (Mantine "light" tonları; koyu temada da okunur). Çalıştı renksizdir.
const STATUS_COLORS: Partial<Record<AttendanceStatus, string>> = {
  WEEKLY_REST: "gray",
  PUBLIC_HOLIDAY: "pink",
  ANNUAL_LEAVE: "blue",
  PAID_LEAVE: "cyan",
  UNPAID_LEAVE: "yellow",
  SICK_LEAVE: "orange",
  ABSENT: "red",
};
const STATUSES = Object.keys(at.labels) as AttendanceStatus[];
const DAY_WIDTH = 34;
const NAME_WIDTH = 190;
// Ekranda özet toplamlar; ayrıntı (HT, RT, fazla mesai türleri) Excel'de.
const TOTALS: { key: AttendanceStatus | "missing" | "overtime"; label: string; help: string }[] = [
  { key: "WORKED", label: at.codes.WORKED, help: at.labels.WORKED },
  { key: "ANNUAL_LEAVE", label: at.codes.ANNUAL_LEAVE, help: at.labels.ANNUAL_LEAVE },
  { key: "PAID_LEAVE", label: at.codes.PAID_LEAVE, help: at.labels.PAID_LEAVE },
  { key: "UNPAID_LEAVE", label: at.codes.UNPAID_LEAVE, help: at.labels.UNPAID_LEAVE },
  { key: "SICK_LEAVE", label: at.codes.SICK_LEAVE, help: at.labels.SICK_LEAVE },
  { key: "ABSENT", label: at.codes.ABSENT, help: at.labels.ABSENT },
  { key: "missing", label: at.missing, help: at.missingHelp },
  { key: "overtime", label: at.overtimeShort, help: at.overtimeTotalHelp },
];
// Kişi sütunu yatay kaydırmada yerinde kalır.
const STICKY: CSSProperties = {
  position: "sticky",
  left: 0,
  zIndex: 1,
  minWidth: NAME_WIDTH,
  maxWidth: NAME_WIDTH,
  background: "var(--mantine-color-body)",
};

function tone(color: string | undefined): CSSProperties {
  return color
    ? {
        background: `var(--mantine-color-${color}-light)`,
        color: `var(--mantine-color-${color}-light-color)`,
      }
    : {};
}

function columnTone(column: AttendanceColumn): CSSProperties {
  if (column.holiday_name && !column.half_day) return tone("pink");
  return column.rest ? tone("gray") : {};
}

/** `?ay=2026-10`; yoksa ya da geçersizse bu ay. */
function parseMonth(text: string | null): { year: number; month: number } {
  const match = text?.match(/^(\d{4})-(\d{2})$/);
  const month = match ? Number(match[2]) : 0;
  if (match && month >= 1 && month <= 12) return { year: Number(match[1]), month };
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

function monthParam(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function totalValue(row: AttendanceRow, key: (typeof TOTALS)[number]["key"]): string | number {
  if (key === "missing") return row.totals.missing_days;
  if (key === "overtime") return formatHours(row.totals.overtime_total);
  return row.totals.days[key];
}

function Legend() {
  return (
    <Group gap={6}>
      {STATUSES.map((status) => (
        <Badge
          key={status}
          variant="light"
          color={STATUS_COLORS[status] ?? "dark"}
          radius="sm"
          tt="none"
        >
          {`${at.codes[status]} ${at.labels[status]}`}
        </Badge>
      ))}
      <Badge variant="outline" color="gray" radius="sm" tt="none">
        {at.halfDayLegend}
      </Badge>
    </Group>
  );
}

function MonthStatus({ grid }: { grid: AttendanceGrid | undefined }) {
  if (!grid) return null;
  const record = grid.month_record;
  if (grid.status === "APPROVED" && record) {
    return (
      <Group gap={6}>
        <Badge color="green" leftSection={<IconLock size={12} />}>
          {`${at.statusApproved} · ${record.number}`}
        </Badge>
        {record.approved_by_name && record.approved_at && (
          <Text size="xs" c="dimmed">
            {at.approvedBy(record.approved_by_name, formatDateTime(record.approved_at))}
          </Text>
        )}
      </Group>
    );
  }
  return (
    <Badge color="gray" variant="light">
      {record ? `${at.statusOpen} · ${record.number}` : at.statusOpen}
    </Badge>
  );
}

function DayCell({
  name,
  cell,
  onEdit,
}: {
  name: string;
  cell: AttendanceCell;
  onEdit: () => void;
}) {
  const hours = formatHours(cell.overtime_hours);
  const label = cell.status ? at.labels[cell.status] : "";
  const title = [label, hours && `${at.overtime}: ${hours}`, cell.note].filter(Boolean).join(" · ");
  const style: CSSProperties = {
    ...tone(cell.status ? STATUS_COLORS[cell.status] : undefined),
    padding: 0,
    minWidth: DAY_WIDTH,
    textAlign: "center",
  };
  const content = cell.status ? (
    <>
      <Text span size="xs" fw={cell.explicit ? 700 : 400} c="inherit">
        {cell.code}
      </Text>
      {hours && (
        <Text span size="10px" lh={1} c="inherit" display="block">
          {`+${hours}`}
        </Text>
      )}
    </>
  ) : (
    <Text span size="xs" c="dimmed">
      ·
    </Text>
  );
  if (!cell.editable) {
    return (
      <Table.Td style={style} title={title || undefined}>
        {content}
      </Table.Td>
    );
  }
  return (
    <Table.Td style={style}>
      <UnstyledButton
        onClick={onEdit}
        title={title || undefined}
        aria-label={`${name} ${formatDate(cell.date)}: ${label}`}
        style={{ display: "block", width: "100%", minHeight: 34, color: "inherit" }}
      >
        {content}
      </UnstyledButton>
    </Table.Td>
  );
}

function AttendanceTable({
  grid,
  onEdit,
}: {
  grid: AttendanceGrid;
  onEdit: (row: AttendanceRow, cell: AttendanceCell, column: AttendanceColumn) => void;
}) {
  const width = NAME_WIDTH + grid.days.length * DAY_WIDTH + TOTALS.length * 44;
  return (
    <Table.ScrollContainer minWidth={width}>
      <Table
        withTableBorder
        withColumnBorders
        verticalSpacing={2}
        horizontalSpacing={4}
        data-testid="attendance"
      >
        <Table.Thead>
          <Table.Tr>
            <Table.Th style={STICKY}>{at.person}</Table.Th>
            {grid.days.map((column) => (
              <Table.Th
                key={column.date}
                style={{ ...columnTone(column), textAlign: "center", minWidth: DAY_WIDTH }}
                title={column.holiday_name || undefined}
              >
                <Text size="xs" fw={600} c="inherit">
                  {Number(column.date.slice(8))}
                </Text>
                <Text size="10px" c="inherit">
                  {`${at.weekdays[column.weekday]}${column.half_day ? " ½" : ""}`}
                </Text>
              </Table.Th>
            ))}
            {TOTALS.map((total) => (
              <Table.Th key={total.key} style={{ textAlign: "center" }}>
                <Tooltip label={total.help}>
                  <Text size="xs" fw={600}>
                    {total.label}
                  </Text>
                </Tooltip>
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {grid.rows.map((row) => (
            <Table.Tr key={row.employee.id}>
              <Table.Td style={STICKY}>
                <Text size="sm" fw={500} lineClamp={1}>
                  {row.employee.full_name}
                </Text>
                <Text size="xs" c="dimmed" lineClamp={1}>
                  {[row.employee.employee_no, row.employee.department].filter(Boolean).join(" · ")}
                </Text>
              </Table.Td>
              {row.cells.map((cell, index) => (
                <DayCell
                  key={cell.date}
                  name={row.employee.full_name}
                  cell={cell}
                  onEdit={() => onEdit(row, cell, grid.days[index])}
                />
              ))}
              {TOTALS.map((total) => (
                <Table.Td key={total.key} style={{ textAlign: "center" }}>
                  <Text size="xs">{totalValue(row, total.key)}</Text>
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

interface Editing {
  row: AttendanceRow;
  cell: AttendanceCell;
  column: AttendanceColumn;
}

/** Personel > Puantaj: ay seçici, birim süzgeci, renkli tablo, aralık girişi, Excel ve onay. */
export function AttendancePage() {
  const [params, setParams] = useSearchParams();
  const { year, month } = parseMonth(params.get("ay"));
  const queryClient = useQueryClient();
  const [department, setDepartment] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [ranging, setRanging] = useState(false);
  const [approving, setApproving] = useState(false);
  const [reopening, setReopening] = useState(false);
  const grid = useQuery({
    queryKey: attendanceKeys.grid(year, month, department ?? ""),
    queryFn: () => getAttendanceGrid(year, month, department ?? ""),
    placeholderData: keepPreviousData,
  });
  const departments = useQuery({
    queryKey: [...PERSONNEL_KEY, "departments"],
    queryFn: listDepartments,
  });
  const data = grid.data;
  const label = data?.period_label ?? `${at.months[month - 1]} ${year}`;
  const approved = data?.status === "APPROVED";

  function done(message: string) {
    setEditing(null);
    setRanging(false);
    setApproving(false);
    setReopening(false);
    notifications.show({ color: "green", message });
    void queryClient.invalidateQueries({ queryKey: attendanceKeys.all });
  }

  const approve = useMutation({
    mutationFn: () => approveAttendanceMonth(year, month),
    onSuccess: () => done(at.approved(label)),
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });

  function go(offset: number) {
    const target = new Date(year, month - 1 + offset, 1);
    setParams({ ay: monthParam(target.getFullYear(), target.getMonth() + 1) });
  }

  return (
    <Stack>
      <Title order={2}>{pe.title}</Title>
      <PersonnelTabs active={ATTENDANCE_BASE} />
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{at.intro}</Text>
      </Alert>
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="xs" wrap="wrap">
          <ActionIcon variant="default" aria-label={at.previousMonth} onClick={() => go(-1)}>
            <IconChevronLeft size={16} />
          </ActionIcon>
          <Text fw={600} miw={120} ta="center">
            {label}
          </Text>
          <ActionIcon variant="default" aria-label={at.nextMonth} onClick={() => go(1)}>
            <IconChevronRight size={16} />
          </ActionIcon>
          <MonthStatus grid={data} />
        </Group>
        <Group gap="xs" wrap="wrap">
          <Select
            aria-label={pe.department}
            placeholder={pe.allDepartments}
            data={departments.data ?? []}
            value={department}
            onChange={setDepartment}
            clearable
            searchable
            w={190}
          />
          <Button
            variant="light"
            leftSection={<IconCalendarPlus size={16} />}
            onClick={() => setRanging(true)}
            disabled={approved || !data}
          >
            {at.rangeEntry}
          </Button>
          <Button
            component="a"
            href={attendanceExportUrl(year, month, department ?? "")}
            variant="default"
            leftSection={<IconFileSpreadsheet size={16} />}
          >
            {at.excel}
          </Button>
          {approved ? (
            <Button
              variant="light"
              color="orange"
              leftSection={<IconLockOpen size={16} />}
              onClick={() => setReopening(true)}
            >
              {at.reopen}
            </Button>
          ) : (
            <Tooltip label={at.notFinished} disabled={!data || data.finished}>
              <span>
                <Button
                  leftSection={<IconLock size={16} />}
                  onClick={() => setApproving(true)}
                  disabled={!data?.finished}
                >
                  {at.approve}
                </Button>
              </span>
            </Tooltip>
          )}
        </Group>
      </Group>
      <Legend />
      {grid.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(grid.error)}
        </Alert>
      )}
      {grid.isLoading && <Loader />}
      {data && data.rows.length === 0 && <Text c="dimmed">{at.empty}</Text>}
      {data && data.rows.length > 0 && (
        <AttendanceTable
          grid={data}
          onEdit={(row, cell, column) => setEditing({ row, cell, column })}
        />
      )}
      {editing && (
        <DayModal
          employee={editing.row.employee}
          cell={editing.cell}
          column={editing.column}
          onClose={() => setEditing(null)}
          onSaved={() => done(at.daySaved)}
        />
      )}
      {ranging && data && (
        <RangeModal
          employees={data.rows.map((row) => row.employee)}
          departments={departments.data ?? []}
          onClose={() => setRanging(false)}
          onDone={(updated) => done(at.rangeApplied(updated))}
        />
      )}
      {reopening && (
        <ReopenModal
          year={year}
          month={month}
          label={label}
          onClose={() => setReopening(false)}
          onDone={() => done(at.reopened(label))}
        />
      )}
      <ConfirmModal
        opened={approving}
        message={at.confirmApprove(label)}
        confirmLabel={at.approve}
        loading={approve.isPending}
        onConfirm={() => approve.mutate()}
        onClose={() => setApproving(false)}
      />
    </Stack>
  );
}
