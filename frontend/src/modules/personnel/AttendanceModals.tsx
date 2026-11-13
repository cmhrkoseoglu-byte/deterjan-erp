// Puantaj pencereleri: tek gün, aralık girişi ve onaylı ayı yeniden açma.
import {
  Alert,
  Button,
  Checkbox,
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
  formatWorkedHours,
  parseHours,
  parseWorkedHours,
  STATUS_OPTIONS,
} from "./attendanceFormat";
import { at } from "./strings";

type DayErrors = Partial<Record<"hours" | "overtime", string>>;

/** Kişinin bir gününü değiştirme penceresi: durum, çalışılan saat, yarım gün, fazla mesai, not. */
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
  const [hoursText, setHoursText] = useState(formatWorkedHours(cell.worked_hours));
  // Kullanıcının bu pencerede "Yarım gün çalıştı" kutusuna dokunuşu (dokunmadıysa null). Saat ya da
  // durum değişikliği buna dokunmaz: kullanıcının seçimi pencere kapanana kadar geçerlidir.
  const [shortChoice, setShortChoice] = useState<boolean | null>(null);
  const [overtimeText, setOvertimeText] = useState(formatHours(cell.overtime_hours));
  const [note, setNote] = useState(cell.note);
  const [halfWorked, setHalfWorked] = useState(cell.holiday_half_worked);
  const [errors, setErrors] = useState<DayErrors>({});
  const overtimeAllowed = OVERTIME_STATUSES.includes(status);
  // Yarım gün tatilde öğleden sonra çalışma yalnızca çalışılan güne (Ç) girilir.
  const halfAllowed = column.half_day && status === "WORKED";
  // Günün çalışma saati (yarım gün tatilde yarısı); günlük çalışma saati belirlenmediyse yok.
  const expected = column.expected_hours === null ? null : Number(column.expected_hours);
  const expectedText = formatWorkedHours(column.expected_hours);
  // Çalışılan saat yalnızca çalışılan güne (Ç) ve günün çalışma saati biliniyorsa girilir.
  const hoursAllowed = status === "WORKED" && expected !== null;
  const parsed = parseWorkedHours(hoursText);
  const entered = hoursAllowed && parsed.kind === "value" ? parsed : null;
  // Saat günün çalışma saatinin altında: gün yarım gün sayılabilir.
  const short = entered !== null && expected !== null && entered.number < expected;
  // Kutunun değeri (sistem önerir, kullanıcı onaylar): kullanıcı kutuya dokunduysa onun seçimi;
  // saat pencere açılırkenki (kayıtlı) saatle sayıca aynıysa kayıtlı karar; değilse öneri.
  const storedHours = cell.worked_hours === null ? null : Number(cell.worked_hours);
  const shortDay = !short
    ? false
    : shortChoice !== null
      ? shortChoice
      : entered.number === storedHours
        ? cell.short_day
        : true;
  const mutation = useMutation({
    mutationFn: (overtime: string) =>
      setAttendanceDay({
        employee: employee.id,
        date: cell.date,
        status,
        worked_hours: entered ? entered.value : null,
        short_day: shortDay,
        overtime_hours: overtime,
        holiday_half_worked: halfAllowed && halfWorked,
        note: note.trim(),
      }),
    onSuccess: onSaved,
  });

  /** Çalışılan saat alanının hatası; kapalı alan denetlenmez. */
  function hoursError(): string | undefined {
    if (!hoursAllowed) return undefined;
    if (parsed.kind === "invalid") return at.workedHoursInvalid;
    if (entered !== null && expected !== null && entered.number > expected) {
      return column.half_day
        ? at.workedHoursTooManyHalfHoliday(expectedText)
        : at.workedHoursTooMany(expectedText);
    }
    return short && halfAllowed && halfWorked ? at.workedHoursWithHalfHoliday : undefined;
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const overtime = overtimeAllowed ? parseHours(overtimeText) : "0";
    // Saati eksik güne fazla mesai ve "Öğleden sonra da çalıştı" girilmez; var olan fazla mesai ya
    // da işaret sessizce silinmez, hangisinin doğru olduğuna kullanıcı karar verir.
    const next: DayErrors = {
      hours: hoursError(),
      overtime:
        overtime === null
          ? at.overtimeInvalid
          : short && Number(overtime) > 0
            ? at.overtimeWithShortHours
            : undefined,
    };
    setErrors(next);
    if (overtime !== null && !next.hours && !next.overtime) mutation.mutate(overtime);
  }

  // Çalışılmayan günde (izin, tatil) alan kapalıdır; açıklama nedenini söyler.
  const hoursHelp =
    status !== "WORKED"
      ? at.workedHoursOnlyWorked
      : expected === null
        ? at.workedHoursNotSet
        : column.half_day
          ? at.workedHoursHalfHolidayHelp(expectedText)
          : at.workedHoursHelp(expectedText);
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
          <Stack gap={4}>
            <TextInput
              label={at.workedHours}
              description={hoursHelp}
              value={hoursAllowed ? hoursText : ""}
              onChange={(e) => setHoursText(e.currentTarget.value)}
              disabled={!hoursAllowed}
              error={errors.hours}
              inputMode="decimal"
              autoComplete="off"
            />
            <Text size="sm" aria-live="polite">
              {short && (shortDay ? at.shortDayOn : at.shortDayOff)}
            </Text>
          </Stack>
          {status === "WORKED" && (
            <Checkbox
              label={at.shortDay}
              description={at.shortDayHelp}
              checked={shortDay}
              disabled={!short}
              onChange={(e) => setShortChoice(e.currentTarget.checked)}
            />
          )}
          <TextInput
            label={at.overtime}
            description={at.overtimeHelp}
            value={overtimeAllowed ? overtimeText : ""}
            onChange={(e) => setOvertimeText(e.currentTarget.value)}
            disabled={!overtimeAllowed}
            error={errors.overtime}
            inputMode="decimal"
            autoComplete="off"
          />
          {column.half_day && (
            <Checkbox
              label={at.halfHolidayWorked}
              description={at.halfHolidayWorkedHelp}
              checked={halfAllowed && halfWorked}
              disabled={!halfAllowed}
              onChange={(e) => setHalfWorked(e.currentTarget.checked)}
            />
          )}
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
