// Tatil takvimi (admin ve yönetim): resmi tatiller ve varsayılan hafta tatili günleri.
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Chip,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconCalendarPlus,
  IconChevronLeft,
  IconChevronRight,
  IconEdit,
  IconInfoCircle,
  IconTrash,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  addFixedHolidays,
  attendanceKeys,
  getAttendanceSettings,
  listHolidays,
  removeHoliday,
  saveAttendanceSettings,
  saveHoliday,
  type AttendanceSettings,
  type PublicHoliday,
} from "../../api/attendance";
import { getErrorMessage } from "../../api/client";
import { formatDate } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { dayLabel } from "./attendanceFormat";
import { PersonnelTabs } from "./PersonnelTabs";
import { at, HOLIDAYS_BASE, pe } from "./strings";

/** `?yil=2027`; yoksa bu yıl. */
function parseYear(text: string | null): number {
  const year = Number(text);
  return Number.isInteger(year) && year >= 2000 && year <= 2100 ? year : new Date().getFullYear();
}

function showError(error: unknown) {
  notifications.show({ color: "red", message: getErrorMessage(error) });
}

/** Tatil ekleme ya da düzenleme penceresi. */
function HolidayFormModal({
  holiday,
  year,
  onClose,
  onSaved,
}: {
  holiday: PublicHoliday | null;
  year: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [date, setDate] = useState(holiday?.date ?? "");
  const [name, setName] = useState(holiday?.name ?? "");
  const [halfDay, setHalfDay] = useState(holiday?.half_day ?? false);
  const [errors, setErrors] = useState<Partial<Record<"date" | "name", string>>>({});
  const mutation = useMutation({
    mutationFn: () =>
      saveHoliday(holiday?.id ?? null, { date, name: name.trim(), half_day: halfDay }),
    onSuccess: onSaved,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next = {
      date: date ? undefined : at.required,
      name: name.trim() ? undefined : at.required,
    };
    setErrors(next);
    if (!next.date && !next.name) mutation.mutate();
  }

  return (
    <Modal
      opened
      onClose={onClose}
      title={holiday ? at.editHolidayTitle : at.newHolidayTitle}
      closeOnClickOutside={false}
    >
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <TextInput
            type="date"
            label={at.holidayDate}
            value={date}
            onChange={(e) => setDate(e.currentTarget.value)}
            min={`${year}-01-01`}
            max={`${year}-12-31`}
            error={errors.date}
            required
          />
          <TextInput
            label={at.holidayName}
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            error={errors.name}
            maxLength={100}
            required
            autoComplete="off"
            data-autofocus
          />
          <Checkbox
            label={at.halfDayLabel}
            checked={halfDay}
            onChange={(e) => setHalfDay(e.currentTarget.checked)}
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

/** Varsayılan hafta tatili günleri (en az bir, en çok altı gün). */
function RestDaysCard({ settings }: { settings: AttendanceSettings }) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState(settings.rest_weekdays.map(String));
  const [error, setError] = useState<string | undefined>();
  useEffect(() => setDays(settings.rest_weekdays.map(String)), [settings.rest_weekdays]);
  const mutation = useMutation({
    mutationFn: () => saveAttendanceSettings(days.map(Number)),
    onSuccess: () => {
      notifications.show({ color: "green", message: at.settingsSaved });
      void queryClient.invalidateQueries({ queryKey: attendanceKeys.all });
    },
    onError: showError,
  });

  function save() {
    const invalid = days.length === 0 || days.length > 6;
    setError(invalid ? at.restDaysInvalid : undefined);
    if (!invalid) mutation.mutate();
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Text fw={600}>{at.restDays}</Text>
        <Text size="sm" c="dimmed">
          {at.restDaysHelp}
        </Text>
        <Chip.Group multiple value={days} onChange={setDays}>
          <Group gap="xs">
            {at.weekdayNames.map((name, index) => (
              <Chip key={name} value={String(index)}>
                {name}
              </Chip>
            ))}
          </Group>
        </Chip.Group>
        {error && (
          <Text size="sm" c="red" role="alert">
            {error}
          </Text>
        )}
        <Group>
          <Button onClick={save} loading={mutation.isPending}>
            {at.save}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

/** Personel > Tatil takvimi: yılın resmi tatilleri ve hafta tatili günleri. */
export function HolidaysPage() {
  const [params, setParams] = useSearchParams();
  const year = parseYear(params.get("yil"));
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<PublicHoliday | "new" | null>(null);
  const [removing, setRemoving] = useState<PublicHoliday | null>(null);
  const list = useQuery({
    queryKey: attendanceKeys.holidays(year),
    queryFn: () => listHolidays(year),
  });
  const settings = useQuery({
    queryKey: attendanceKeys.settings,
    queryFn: getAttendanceSettings,
  });

  function refresh(message: string) {
    setEditing(null);
    setRemoving(null);
    notifications.show({ color: "green", message });
    void queryClient.invalidateQueries({ queryKey: attendanceKeys.all });
  }

  const fixed = useMutation({
    mutationFn: () => addFixedHolidays(year),
    onSuccess: (created) => refresh(at.fixedAdded(created.length)),
    onError: showError,
  });
  const remove = useMutation({
    mutationFn: (holiday: PublicHoliday) => removeHoliday(holiday.id),
    onSuccess: () => refresh(at.holidayRemoved),
    onError: showError,
  });

  const rows = list.data ?? [];
  return (
    <Stack>
      <Title order={2}>{pe.title}</Title>
      <PersonnelTabs active={HOLIDAYS_BASE} />
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{at.holidaysIntro}</Text>
      </Alert>
      <Group justify="space-between" wrap="wrap">
        <Group gap="xs">
          <ActionIcon
            variant="default"
            aria-label={at.previousYear}
            onClick={() => setParams({ yil: String(year - 1) })}
          >
            <IconChevronLeft size={16} />
          </ActionIcon>
          <Text fw={600} miw={50} ta="center">
            {year}
          </Text>
          <ActionIcon
            variant="default"
            aria-label={at.nextYear}
            onClick={() => setParams({ yil: String(year + 1) })}
          >
            <IconChevronRight size={16} />
          </ActionIcon>
        </Group>
        <Group gap="xs" wrap="wrap">
          <Button variant="light" onClick={() => fixed.mutate()} loading={fixed.isPending}>
            {at.addFixed}
          </Button>
          <Button leftSection={<IconCalendarPlus size={16} />} onClick={() => setEditing("new")}>
            {at.addHoliday}
          </Button>
        </Group>
      </Group>
      {list.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(list.error)}
        </Alert>
      )}
      {list.isLoading && <Loader />}
      {list.isSuccess && rows.length === 0 && <Text c="dimmed">{at.noHolidays}</Text>}
      {rows.length > 0 && (
        <Table.ScrollContainer minWidth={480}>
          <Table striped data-testid="holidays">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{at.holidayDate}</Table.Th>
                <Table.Th>{at.holidayName}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((holiday) => (
                <Table.Tr key={holiday.id}>
                  <Table.Td style={{ whiteSpace: "nowrap" }}>{dayLabel(holiday.date)}</Table.Td>
                  <Table.Td>
                    <Group gap={6}>
                      <Text size="sm">{holiday.name}</Text>
                      {holiday.half_day && (
                        <Badge size="xs" variant="light" color="gray" tt="none">
                          {at.halfDay}
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Tooltip label={at.editHoliday}>
                        <ActionIcon
                          variant="subtle"
                          aria-label={`${at.editHoliday}: ${holiday.name}`}
                          onClick={() => setEditing(holiday)}
                        >
                          <IconEdit size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label={at.removeHoliday}>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={`${at.removeHoliday}: ${holiday.name}`}
                          onClick={() => setRemoving(holiday)}
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {settings.data && <RestDaysCard settings={settings.data} />}
      {editing && (
        <HolidayFormModal
          holiday={editing === "new" ? null : editing}
          year={year}
          onClose={() => setEditing(null)}
          onSaved={() => refresh(at.holidaySaved)}
        />
      )}
      <ConfirmModal
        opened={removing !== null}
        message={removing ? at.confirmRemoveHoliday(removing.name, formatDate(removing.date)) : ""}
        confirmLabel={at.removeHoliday}
        danger
        loading={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
        onClose={() => setRemoving(null)}
      />
    </Stack>
  );
}
