import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle, IconSearch, IconUserPlus } from "@tabler/icons-react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  EMPLOYEES_PAGE_SIZE,
  listDepartments,
  listEmployees,
  type Employee,
} from "../../api/personnel";
import { formatDate } from "../../i18n/format";
import { EmployeeFormModal } from "./EmployeeFormModal";
import { employeePath, pe, PERSONNEL_KEY } from "./strings";

type Status = "active" | "left" | "all";
const STATUS_FILTER: Record<Status, boolean | undefined> = {
  active: true,
  left: false,
  all: undefined,
};
// Sicil no, telefon ve tarih dar ekranda bölünmesin (tablo yatay kayar).
const NO_WRAP = { whiteSpace: "nowrap" } as const;

/** Durum rozeti: çalışıyor ya da ayrılış tarihiyle ayrıldı. */
export function EmployeeStatus({ employee }: { employee: Employee }) {
  return employee.is_active ? (
    <Badge size="sm" color="green" variant="light">
      {pe.working}
    </Badge>
  ) : (
    <Badge size="sm" color="gray">
      {employee.termination_date ? pe.leftOn(formatDate(employee.termination_date)) : pe.left}
    </Badge>
  );
}

/** Personel listesi: arama, birim ve durum süzgeci, yeni kart; satıra basınca kart açılır. */
export function PersonnelPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [department, setDepartment] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("active");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const filters = {
    search: debounced,
    department: department ?? "",
    is_active: STATUS_FILTER[status],
  };
  const query = useQuery({
    queryKey: [...PERSONNEL_KEY, "employees", filters, page],
    queryFn: () => listEmployees({ ...filters, page }),
    placeholderData: keepPreviousData,
  });
  const departments = useQuery({
    queryKey: [...PERSONNEL_KEY, "departments"],
    queryFn: listDepartments,
  });

  // Süzgeç değişince ilk sayfaya dönülür.
  function filterBy(change: () => void) {
    change();
    setPage(1);
  }

  const rows = query.data?.results ?? [];
  const count = query.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(count / EMPLOYEES_PAGE_SIZE));
  return (
    <Stack>
      <Group justify="space-between" align="flex-end">
        <Title order={2}>{pe.title}</Title>
        <Button leftSection={<IconUserPlus size={18} />} onClick={() => setCreating(true)}>
          {pe.newEmployee}
        </Button>
      </Group>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{pe.intro}</Text>
      </Alert>
      <Group align="flex-end" wrap="wrap">
        <TextInput
          placeholder={pe.search}
          aria-label={pe.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => {
            const value = e.currentTarget.value;
            filterBy(() => setSearch(value));
          }}
          style={{ flex: 1, minWidth: 220 }}
          maw={360}
        />
        <Select
          aria-label={pe.department}
          placeholder={pe.allDepartments}
          data={departments.data ?? []}
          value={department}
          onChange={(value) => filterBy(() => setDepartment(value))}
          clearable
          searchable
          w={220}
        />
        <SegmentedControl
          aria-label={pe.status}
          value={status}
          onChange={(value) => filterBy(() => setStatus(value as Status))}
          data={[
            { value: "active", label: pe.statusActive },
            { value: "left", label: pe.statusLeft },
            { value: "all", label: pe.statusAll },
          ]}
        />
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading ? (
        <Loader />
      ) : rows.length === 0 ? (
        <Text c="dimmed">{pe.empty}</Text>
      ) : (
        <>
          <Text size="sm" c="dimmed">
            {pe.count(count)}
          </Text>
          <Table.ScrollContainer minWidth={860}>
            <Table striped highlightOnHover data-testid="employees">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{pe.fullName}</Table.Th>
                  <Table.Th>{pe.employeeNo}</Table.Th>
                  <Table.Th>{pe.department}</Table.Th>
                  <Table.Th>{pe.titleField}</Table.Th>
                  <Table.Th>{pe.phone}</Table.Th>
                  <Table.Th>{pe.hireDate}</Table.Th>
                  <Table.Th>{pe.status}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((employee) => (
                  <Table.Tr
                    key={employee.id}
                    style={{ cursor: "pointer" }}
                    onClick={() => navigate(employeePath(employee.id))}
                  >
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {employee.full_name}
                      </Text>
                      {employee.user_info && (
                        <Text size="xs" c="dimmed">
                          {employee.user_info.username}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td style={NO_WRAP}>{employee.employee_no}</Table.Td>
                    <Table.Td>{employee.department}</Table.Td>
                    <Table.Td>{employee.title}</Table.Td>
                    <Table.Td style={NO_WRAP}>{employee.phone}</Table.Td>
                    <Table.Td style={NO_WRAP}>{formatDate(employee.hire_date)}</Table.Td>
                    <Table.Td>
                      <EmployeeStatus employee={employee} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
        </>
      )}
      {creating && (
        <EmployeeFormModal
          employee={null}
          onClose={() => setCreating(false)}
          onSaved={(saved) => {
            setCreating(false);
            notifications.show({ color: "green", message: pe.created(saved.full_name) });
            queryClient.invalidateQueries({ queryKey: PERSONNEL_KEY });
            navigate(employeePath(saved.id));
          }}
        />
      )}
    </Stack>
  );
}
