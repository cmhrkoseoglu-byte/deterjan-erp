import { Alert, Pagination, Stack, Table, Text } from "@mantine/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listProblems } from "../../api/golive";
import { formatDateTime } from "../../i18n/format";
import { problemPath } from "./paths";
import { gt } from "./strings";

const PAGE_SIZE = 50;

/** Admin: tüm sorun bildirimleri (görevler "Görevlerim"de, burada arşiv). */
export function ProblemsTab() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["golive", "problems", page],
    queryFn: () => listProblems({ page }),
    placeholderData: keepPreviousData,
  });
  const rows = list.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((list.data?.count ?? 0) / PAGE_SIZE));
  return (
    <Stack>
      {list.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(list.error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={640}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{gt.number}</Table.Th>
              <Table.Th>{gt.problems.when}</Table.Th>
              <Table.Th>{gt.problems.reporter}</Table.Th>
              <Table.Th>{gt.problems.description}</Table.Th>
              <Table.Th>{gt.problems.page}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(problemPath(row.id))}
              >
                <Table.Td>{row.number}</Table.Td>
                <Table.Td>{formatDateTime(row.created_at)}</Table.Td>
                <Table.Td>{row.reporter}</Table.Td>
                <Table.Td>
                  <Text size="sm" lineClamp={2}>
                    {row.description}
                  </Text>
                </Table.Td>
                <Table.Td>{row.page_title || row.page_url}</Table.Td>
              </Table.Tr>
            ))}
            {!list.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed">{gt.problems.empty}</Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}
