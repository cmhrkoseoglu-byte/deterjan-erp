import {
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
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconEdit,
  IconUserCheck,
  IconUserOff,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  fetchEmployeeHistory,
  getEmployee,
  reinstateEmployee,
  terminateEmployee,
  type EducationLevel,
  type Employee,
} from "../../api/personnel";
import type { AuditEntry } from "../../api/workflow";
import { formatDate, formatDateTime } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { Info } from "../inventory/shared";
import { EmployeeDocuments } from "./EmployeeDocuments";
import { EmployeeFormModal } from "./EmployeeFormModal";
import { EmployeeStatus } from "./PersonnelPage";
import { PERSONNEL_BASE, pe, PERSONNEL_KEY } from "./strings";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function today(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

/** Geçmişteki değer: tarih gün.ay.yıl, evet/hayır, bağlı kullanıcı adı, öğrenim durumu adı.
 * TC kimlik no günlükte maskelidir (`*******0146`). */
function formatValue(field: string, value: unknown, employee: Employee): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? pe.yes : pe.no;
  if (field === "user") {
    return value === employee.user_info?.id ? employee.user_info.username : `#${String(value)}`;
  }
  if (field === "education_level") {
    return pe.educationLevels[value as EducationLevel] ?? String(value);
  }
  if (typeof value === "string" && ISO_DATE.test(value)) return formatDate(value);
  return String(value);
}

function HistoryItem({ entry, employee }: { entry: AuditEntry; employee: Employee }) {
  const changes = Object.entries(entry.changes ?? {});
  return (
    <Stack gap={2}>
      <Group gap={6}>
        <Text size="sm" fw={600}>
          {entry.note || entry.action_label}
        </Text>
        <Text size="xs" c="dimmed">
          {entry.actor_name || pe.system} · {formatDateTime(entry.timestamp)}
        </Text>
      </Group>
      {changes.map(([field, [before, after]]) => (
        <Text key={field} size="xs" c="dimmed" style={{ wordBreak: "break-word" }}>
          {pe.fields[field] ?? field}: {formatValue(field, before, employee)} →{" "}
          {formatValue(field, after, employee)}
        </Text>
      ))}
    </Stack>
  );
}

/** İşten ayrılış penceresi: çıkış tarihi (bugün önerilir) ve not. */
function TerminateModal({
  employee,
  onClose,
  onDone,
}: {
  employee: Employee;
  onClose: () => void;
  onDone: (saved: Employee) => void;
}) {
  const [date, setDate] = useState(today);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | undefined>();
  const mutation = useMutation({
    mutationFn: () => terminateEmployee(employee.id, date, note.trim()),
    onSuccess: onDone,
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(date ? undefined : pe.required);
    if (date) mutation.mutate();
  }

  const account = employee.user_info;
  return (
    <Modal opened onClose={onClose} title={pe.terminateTitle(employee.full_name)}>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Text size="sm">{pe.terminateIntro}</Text>
          {mutation.isError && (
            <Alert color="red" variant="light" role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <TextInput
            type="date"
            label={pe.terminationDate}
            value={date}
            onChange={(e) => setDate(e.currentTarget.value)}
            error={error}
            required
          />
          <Textarea
            label={pe.note}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
            autosize
            minRows={2}
            maxLength={500}
          />
          {account?.is_active && (
            <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
              {pe.accountStillActive(account.username)}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {pe.cancel}
            </Button>
            <Button type="submit" color="red" loading={mutation.isPending}>
              {pe.terminate}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

/** Personel kartı: bilgiler, düzenleme, işten ayrılış / yeniden başlama ve geçmiş. */
export function EmployeePage() {
  const employeeId = Number(useParams().employeeId);
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [terminating, setTerminating] = useState(false);
  const [reinstating, setReinstating] = useState(false);
  const query = useQuery({
    queryKey: [...PERSONNEL_KEY, "employee", employeeId],
    queryFn: () => getEmployee(employeeId),
  });
  const history = useQuery({
    queryKey: [...PERSONNEL_KEY, "employee", employeeId, "history"],
    queryFn: () => fetchEmployeeHistory(employeeId),
  });
  const reinstate = useMutation({
    mutationFn: () => reinstateEmployee(employeeId),
    onSuccess: (saved) => done(pe.reinstated(saved.full_name)),
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });

  function done(message: string) {
    setEditing(false);
    setTerminating(false);
    setReinstating(false);
    notifications.show({ color: "green", message });
    queryClient.invalidateQueries({ queryKey: PERSONNEL_KEY });
  }

  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const employee = query.data;
  const account = employee.user_info;

  return (
    <Stack>
      <Anchor component={Link} to={PERSONNEL_BASE} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {pe.back}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group gap="sm">
          <Title order={2}>{employee.full_name}</Title>
          <EmployeeStatus employee={employee} />
        </Group>
        <Group gap="xs">
          <Button
            variant="default"
            leftSection={<IconEdit size={16} />}
            onClick={() => setEditing(true)}
          >
            {pe.edit}
          </Button>
          {employee.is_active ? (
            <Button
              variant="light"
              color="red"
              leftSection={<IconUserOff size={16} />}
              onClick={() => setTerminating(true)}
            >
              {pe.terminate}
            </Button>
          ) : (
            <Button
              variant="light"
              leftSection={<IconUserCheck size={16} />}
              onClick={() => setReinstating(true)}
            >
              {pe.reinstate}
            </Button>
          )}
        </Group>
      </Group>
      {!employee.is_active && account?.is_active && (
        <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
          {pe.accountStillActive(account.username)}
        </Alert>
      )}
      <Paper withBorder p="md" radius="md">
        <Stack gap="md">
          <Text fw={600}>{pe.sectionWork}</Text>
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            <Info label={pe.employeeNo}>
              <Text size="sm">{employee.employee_no}</Text>
            </Info>
            <Info label={pe.department}>
              <Text size="sm">{employee.department}</Text>
            </Info>
            <Info label={pe.titleField}>
              <Text size="sm">{employee.title}</Text>
            </Info>
            <Info label={pe.hireDate}>
              <Text size="sm">{formatDate(employee.hire_date)}</Text>
            </Info>
            {employee.termination_date && (
              <Info label={pe.terminationDate}>
                <Text size="sm">{formatDate(employee.termination_date)}</Text>
              </Info>
            )}
            <Info label={pe.user}>
              {account ? (
                <Group gap={6}>
                  <Text size="sm">{account.full_name || account.username}</Text>
                  <Text size="xs" c="dimmed">
                    {account.username}
                  </Text>
                  {!account.is_active && (
                    <Badge size="xs" color="gray">
                      {pe.accountInactive}
                    </Badge>
                  )}
                </Group>
              ) : (
                <Text size="sm" c="dimmed">
                  {pe.noUser}
                </Text>
              )}
            </Info>
          </SimpleGrid>
          <Text fw={600}>{pe.sectionIdentity}</Text>
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            <Info label={pe.nationalId}>
              <Text size="sm">{employee.national_id}</Text>
            </Info>
            <Info label={pe.birthDate}>
              <Text size="sm">{formatDate(employee.birth_date)}</Text>
            </Info>
            <Info label={pe.birthPlace}>
              <Text size="sm">{employee.birth_place}</Text>
            </Info>
          </SimpleGrid>
          <Text fw={600}>{pe.sectionContact}</Text>
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            <Info label={pe.phone}>
              <Text size="sm">{employee.phone}</Text>
            </Info>
            <Info label={pe.emergencyName}>
              <Text size="sm">{employee.emergency_contact_name}</Text>
            </Info>
            <Info label={pe.emergencyPhone}>
              <Text size="sm">{employee.emergency_contact_phone}</Text>
            </Info>
          </SimpleGrid>
          <Text fw={600}>{pe.sectionEducation}</Text>
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            <Info label={pe.educationLevel}>
              <Text size="sm">{employee.education_level_display}</Text>
            </Info>
            <Info label={pe.school}>
              <Text size="sm">{employee.school}</Text>
            </Info>
            <Info label={pe.fieldOfStudy}>
              <Text size="sm">{employee.field_of_study}</Text>
            </Info>
            <Info label={pe.graduationYear}>
              <Text size="sm">{employee.graduation_year ?? ""}</Text>
            </Info>
          </SimpleGrid>
        </Stack>
      </Paper>
      <EmployeeDocuments employee={employee} />
      <Paper withBorder p="md" radius="md">
        <Stack gap="md">
          <Text fw={600}>{pe.history}</Text>
          {history.isPending && <Loader size="sm" />}
          {history.isError && (
            <Alert color="red" variant="light">
              {getErrorMessage(history.error)}
            </Alert>
          )}
          {history.data?.length === 0 && (
            <Text size="sm" c="dimmed">
              {pe.noHistory}
            </Text>
          )}
          {history.data?.map((entry) => (
            <HistoryItem key={entry.id} entry={entry} employee={employee} />
          ))}
        </Stack>
      </Paper>
      {editing && (
        <EmployeeFormModal
          employee={employee}
          onClose={() => setEditing(false)}
          onSaved={(saved) => done(pe.saved(saved.full_name))}
        />
      )}
      {terminating && (
        <TerminateModal
          employee={employee}
          onClose={() => setTerminating(false)}
          onDone={(saved) => done(pe.terminated(saved.full_name))}
        />
      )}
      <ConfirmModal
        opened={reinstating}
        message={pe.confirmReinstate(employee.full_name)}
        confirmLabel={pe.reinstate}
        loading={reinstate.isPending}
        onConfirm={() => reinstate.mutate()}
        onClose={() => setReinstating(false)}
      />
    </Stack>
  );
}
