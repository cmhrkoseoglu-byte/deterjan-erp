import {
  Alert,
  Autocomplete,
  Button,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { getErrorMessage } from "../../api/client";
import {
  createEmployee,
  listDepartments,
  listLinkableUsers,
  updateEmployee,
  type Employee,
  type EmployeeInput,
  type LinkedUser,
} from "../../api/personnel";
import { pe, PERSONNEL_KEY } from "./strings";

interface Props {
  /** Düzenlenecek kart; `null` ise yeni kart açılır. */
  employee: Employee | null;
  onClose: () => void;
  onSaved: (employee: Employee, created: boolean) => void;
}

type Errors = Partial<Record<"fullName" | "department", string>>;

function userLabel(user: LinkedUser): string {
  return user.full_name ? `${user.full_name} (${user.username})` : user.username;
}

/** Yeni personel kartı ya da kart düzenleme penceresi (admin ve yönetim). */
export function EmployeeFormModal({ employee, onClose, onSaved }: Props) {
  const isNew = employee === null;
  const [fullName, setFullName] = useState(employee?.full_name ?? "");
  const [employeeNo, setEmployeeNo] = useState(employee?.employee_no ?? "");
  const [department, setDepartment] = useState(employee?.department ?? "");
  const [title, setTitle] = useState(employee?.title ?? "");
  const [hireDate, setHireDate] = useState(employee?.hire_date ?? "");
  const [phone, setPhone] = useState(employee?.phone ?? "");
  const [emergencyName, setEmergencyName] = useState(employee?.emergency_contact_name ?? "");
  const [emergencyPhone, setEmergencyPhone] = useState(employee?.emergency_contact_phone ?? "");
  const [userId, setUserId] = useState<string | null>(
    employee?.user != null ? String(employee.user) : null,
  );
  const [errors, setErrors] = useState<Errors>({});

  const departments = useQuery({
    queryKey: [...PERSONNEL_KEY, "departments"],
    queryFn: listDepartments,
  });
  const users = useQuery({
    queryKey: [...PERSONNEL_KEY, "linkable-users", employee?.id ?? null],
    queryFn: () => listLinkableUsers(employee?.id),
  });
  const userOptions = users.data ?? (employee?.user_info ? [employee.user_info] : []);

  const mutation = useMutation({
    mutationFn: async (): Promise<Employee> => {
      const input: EmployeeInput = {
        full_name: fullName.trim(),
        employee_no: employeeNo.trim(),
        department: department.trim(),
        title: title.trim(),
        hire_date: hireDate || null,
        phone: phone.trim(),
        emergency_contact_name: emergencyName.trim(),
        emergency_contact_phone: emergencyPhone.trim(),
        user: userId ? Number(userId) : null,
      };
      return employee === null ? createEmployee(input) : updateEmployee(employee.id, input);
    },
    onSuccess: (saved) => onSaved(saved, isNew),
  });

  function chooseUser(value: string | null) {
    setUserId(value);
    // Yeni kartta ad boşsa kullanıcının adı yazılır.
    const user = userOptions.find((option) => String(option.id) === value);
    if (user && !fullName.trim()) setFullName(user.full_name);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next: Errors = {
      fullName: fullName.trim() ? undefined : pe.required,
      department: department.trim() ? undefined : pe.required,
    };
    setErrors(next);
    if (next.fullName || next.department) return;
    mutation.mutate();
  }

  return (
    <Modal
      opened
      onClose={onClose}
      title={isNew ? pe.formNewTitle : pe.formEditTitle(employee.full_name)}
      size="lg"
      closeOnClickOutside={false}
    >
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          {mutation.isError && (
            <Alert color="red" variant="light" icon={<IconAlertCircle size={18} />} role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={pe.fullName}
              value={fullName}
              onChange={(e) => setFullName(e.currentTarget.value)}
              error={errors.fullName}
              required
              autoComplete="off"
              data-autofocus
            />
            <TextInput
              label={pe.employeeNo}
              value={employeeNo}
              onChange={(e) => setEmployeeNo(e.currentTarget.value)}
              autoComplete="off"
            />
            <Autocomplete
              label={pe.department}
              placeholder={pe.departmentHelp}
              data={departments.data ?? []}
              value={department}
              onChange={setDepartment}
              error={errors.department}
              required
              autoComplete="off"
            />
            <TextInput
              label={pe.titleField}
              value={title}
              onChange={(e) => setTitle(e.currentTarget.value)}
              autoComplete="off"
            />
            <TextInput
              type="date"
              label={pe.hireDate}
              value={hireDate}
              onChange={(e) => setHireDate(e.currentTarget.value)}
            />
            <TextInput
              label={pe.phone}
              value={phone}
              onChange={(e) => setPhone(e.currentTarget.value)}
              inputMode="tel"
              autoComplete="off"
            />
            <TextInput
              label={pe.emergencyName}
              value={emergencyName}
              onChange={(e) => setEmergencyName(e.currentTarget.value)}
              autoComplete="off"
            />
            <TextInput
              label={pe.emergencyPhone}
              value={emergencyPhone}
              onChange={(e) => setEmergencyPhone(e.currentTarget.value)}
              inputMode="tel"
              autoComplete="off"
            />
          </SimpleGrid>
          <Select
            label={pe.user}
            description={pe.userHelp}
            placeholder={pe.noUser}
            data={userOptions.map((user) => ({ value: String(user.id), label: userLabel(user) }))}
            value={userId}
            onChange={chooseUser}
            searchable
            clearable
            nothingFoundMessage={pe.empty}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {pe.cancel}
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {isNew ? pe.create : pe.save}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
