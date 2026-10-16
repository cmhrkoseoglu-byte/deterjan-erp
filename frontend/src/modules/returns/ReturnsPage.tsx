import {
  Alert,
  Badge,
  Button,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconPlus, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listReturns, type ReturnStatus } from "../../api/returns";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate } from "../../i18n/format";
import { ct } from "../common/strings";
import { RETURN_EDIT_ROLES, RETURN_STATUS_COLOR, returnPath } from "./config";
import { rt } from "./strings";

const PAGE_SIZE = 50;
const STATUS_OPTIONS = (["DRAFT", "RECEIVED", "CLOSED", "CANCELLED"] as const).map((value) => ({
  value,
  label: rt.status_[value],
}));

export function ReturnStatusBadge({ status }: { status: ReturnStatus }) {
  return (
    <Badge color={RETURN_STATUS_COLOR[status]} variant="light">
      {rt.status_[status]}
    </Badge>
  );
}

/** Müşteri iadeleri listesi (sevkiyat yeni iade açar; laboratuvar ve depo izler). */
export function ReturnsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [debounced] = useDebouncedValue(search, 300);
  const params = {
    page,
    page_size: PAGE_SIZE,
    search: debounced || undefined,
    status: status ?? undefined,
  };
  const query = useQuery({
    queryKey: ["returns", "list", params],
    queryFn: () => listReturns(params),
    placeholderData: keepPreviousData,
  });
  const rows = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{rt.title}</Title>
        {hasAnyRole(user, RETURN_EDIT_ROLES) && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => navigate(returnPath("yeni"))}>
            {rt.newReturn}
          </Button>
        )}
      </Group>
      <Group>
        <TextInput
          placeholder={rt.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
        />
        <Select
          placeholder={rt.allStatuses}
          clearable
          data={STATUS_OPTIONS}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        />
      </Group>
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={720}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{rt.number}</Table.Th>
              <Table.Th>{rt.returnDate}</Table.Th>
              <Table.Th>{rt.customer}</Table.Th>
              <Table.Th>{rt.reason}</Table.Th>
              <Table.Th ta="right">{rt.lineCount}</Table.Th>
              <Table.Th>{rt.status}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(returnPath(row.id))}
              >
                <Table.Td fw={600}>{row.number}</Table.Td>
                <Table.Td>{formatDate(row.return_date)}</Table.Td>
                <Table.Td>{row.customer_name}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={1}>
                    {row.reason}
                  </Text>
                </Table.Td>
                <Table.Td ta="right">{row.line_count}</Table.Td>
                <Table.Td>
                  <ReturnStatusBadge status={row.status} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {!query.isLoading && rows.length === 0 && (
        <Text size="sm" c="dimmed">
          {ct.empty}
        </Text>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}
