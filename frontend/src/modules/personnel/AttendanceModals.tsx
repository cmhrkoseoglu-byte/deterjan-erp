// Puantaj pencereleri: tek gün, aralık girişi ve onaylı ayı yeniden açma.
import {
  Alert,
  Button,
  Group,
  Modal,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  OVERTIME_STATUSES,
  reopenAttendanceMonth,
  setAttendanceDay,
  setAttendanceRange,
  type AttendanceCell,
  type AttendanceColumn,
  type AttendanceEmployee,
  type AttendanceStatus,
} from "../../api/attendance";
import { getErrorMessage } from "../../api/client";
import {
  calendarStatus,
  dayLabel,
  formatHours,
  parseHours,
  STATUS_OPTIONS,
} from "./attendanceFormat";
import { at } from "./strings";

/** Kişinin bir gününü değiştirme penceresi: durum, fazla mesai ve not. */
export function DayModal({
  employee,
  cell,
  column,
  onClose,
  onSaved,
}: {
  employee: AttendanceEmployee;
  cell: AttendanceCell;
  column: AttendanceColumn;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [status, setStatus] = useState<AttendanceStatus>(cell.status || calendarStatus(column));
  const [hours, setHours] = useState(formatHours(cell.overtime_hours));
  const [note, setNote] = useState(cell.note);
  const [error, setError] = useState<string | undefined>();
  const overtimeAllowed = OVERTIME_STATUSES.includes(status);
  const mutation = useMutation({
    mutationFn: (overtime: string) =>
      setAttendanceDay({
        employee: employee.id,
        date: cell.date,
        status,
        overtime_hours: overtime,
        note: note.trim(),
      }),
    onSuccess: onSaved,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const overtime = overtimeAllowed ? parseHours(hours) : "0";
    setError(overtime === null ? at.overtimeInvalid : undefined);
    if (overtime !== null) mutation.mutate(overtime);
  }

  const holiday = column.holiday_name
    ? at.holidayOn(column.half_day ? `${column.holiday_name} (${at.halfDay})` : column.holiday_name)
    : at.calendarDefault(at.labels[calendarStatus(column)]);
  return (
    <Modal opened onClose={onClose} title={at.dayTitle(employee.full_name, dayLabel(cell.date))}>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Text size="sm" c="dimmed">
            {holiday}
          </Text>
          <Select
            label={at.dayStatus}
            data={STATUS_OPTIONS}
            value={status}
            onChange={(value) => value && setStatus(value as AttendanceStatus)}
            allowDeselect={false}
          />
          <TextInput
            label={at.overtime}
            description={at.overtimeHelp}
            value={overtimeAllowed ? hours : ""}
            onChange={(e) => setHours(e.currentTarget.value)}
            disabled={!overtimeAllowed}
            error={error}
            inputMode="decimal"
            autoComplete="off"
          />
          <TextInput
            label={at.note}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            maxLength={200}
            autoComplete="off"
          />
          {mutation.isError && (
            <Alert color="red" variant="light" role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {at.cancel}
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {at.save}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

type Scope = "person" | "department" | "all";
type RangeErrors = Partial<Record<"person" | "department" | "start" | "end" | "status", string>>;

/** Aralık girişi: kişi, birim ya da herkes için başlangıç–bitiş ve durum. */
export function RangeModal({
  employees,
  departments,
  onClose,
  onDone,
}: {
  employees: AttendanceEmployee[];
  departments: string[];
  onClose: () => void;
  onDone: (updated: number) => void;
}) {
  const [scope, setScope] = useState<Scope>("person");
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [department, setDepartment] = useState<string | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [status, setStatus] = useState<AttendanceStatus | null>(null);
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<RangeErrors>({});
  const mutation = useMutation({
    mutationFn: () =>
      setAttendanceRange({
        employee: scope === "person" ? Number(employeeId) : null,
        department: scope === "department" ? (department ?? "") : "",
        start,
        end,
        status: status!,
        note: note.trim(),
      }),
    onSuccess: onDone,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next: RangeErrors = {
      person: scope === "person" && !employeeId ? at.required : undefined,
      department: scope === "department" && !department ? at.required : undefined,
      start: start ? undefined : at.required,
      end: !end ? at.required : start && end < start ? at.endBeforeStart : undefined,
      status: status ? undefined : at.required,
    };
    setErrors(next);
    if (!Object.values(next).some(Boolean)) mutation.mutate();
  }

  return (
    <Modal opened onClose={onClose} title={at.rangeTitle} closeOnClickOutside={false}>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <SegmentedControl
            aria-label={at.scope}
            value={scope}
            onChange={(value) => setScope(value as Scope)}
            data={[
              { value: "person", label: at.scopePerson },
              { value: "department", label: at.scopeDepartment },
              { value: "all", label: at.scopeAll },
            ]}
          />
          {scope === "person" && (
            <Select
              label={at.person}
              data={employees.map((person) => ({
                value: String(person.id),
                label: person.employee_no
                  ? `${person.full_name} (${person.employee_no})`
                  : person.full_name,
              }))}
              value={employeeId}
              onChange={setEmployeeId}
              error={errors.person}
              searchable
              required
            />
          )}
          {scope === "department" && (
            <Select
              label={at.scopeDepartment}
              data={departments}
              value={department}
              onChange={setDepartment}
              error={errors.department}
              searchable
              required
            />
          )}
          <Group grow align="flex-start">
            <TextInput
              type="date"
              label={at.start}
              value={start}
              onChange={(e) => setStart(e.currentTarget.value)}
              error={errors.start}
              required
            />
            <TextInput
              type="date"
              label={at.end}
              value={end}
              onChange={(e) => setEnd(e.currentTarget.value)}
              error={errors.end}
              required
            />
          </Group>
          <Select
            label={at.dayStatus}
            data={STATUS_OPTIONS}
            value={status}
            onChange={(value) => setStatus(value as AttendanceStatus | null)}
            error={errors.status}
            required
          />
          <TextInput
            label={at.note}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            maxLength={200}
            autoComplete="off"
          />
          <Text size="xs" c="dimmed">
            {at.rangeRule}
          </Text>
          {mutation.isError && (
            <Alert color="red" variant="light" role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {at.cancel}
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {at.apply}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

/** Onaylı ayı gerekçeyle yeniden açma penceresi. */
export function ReopenModal({
  year,
  month,
  label,
  onClose,
  onDone,
}: {
  year: number;
  month: number;
  label: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | undefined>();
  const mutation = useMutation({
    mutationFn: () => reopenAttendanceMonth(year, month, reason.trim()),
    onSuccess: onDone,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const missing = !reason.trim();
    setError(missing ? at.required : undefined);
    if (!missing) mutation.mutate();
  }

  return (
    <Modal opened onClose={onClose} title={at.reopenTitle(label)}>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Text size="sm">{at.reopenIntro}</Text>
          <Textarea
            label={at.reason}
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
            error={error}
            required
            autosize
            minRows={2}
            maxLength={500}
            size="md"
            data-autofocus
          />
          {mutation.isError && (
            <Alert color="red" variant="light" role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {at.cancel}
            </Button>
            <Button type="submit" color="orange" loading={mutation.isPending}>
              {at.reopen}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
