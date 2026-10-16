import { Alert, Anchor, Badge, Loader, Pagination, Stack, Table, Text } from "@mantine/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { jobDownloadUrl, listJobs, type JobStatus } from "../../api/reporting";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { rt } from "./strings";

const STATUS_COLORS: Record<JobStatus, string> = {
  QUEUED: "gray",
  RUNNING: "blue",
  DONE: "green",
  FAILED: "red",
  EXPIRED: "gray",
};
const PAGE_SIZE = 50;

/** Arka planda hazırlanan rapor dosyaları (yalnızca kullanıcının kendi istekleri). */
export function JobsPanel() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["reporting", "jobs", page],
    queryFn: () => listJobs({ page }),
    placeholderData: keepPreviousData,
    // Hazırlanan iş varken liste kendini yeniler.
    refetchInterval: (q) =>
      q.state.data?.results.some((j) => j.status === "QUEUED" || j.status === "RUNNING")
        ? 5_000
        : false,
  });
  if (query.isLoading) return <Loader />;
  if (query.isError)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const jobs = query.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((query.data?.count ?? 0) / PAGE_SIZE));
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {rt.jobs}. {rt.jobsHint}
      </Text>
      {jobs.length === 0 ? (
        <Text c="dimmed">{rt.noJobs}</Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{rt.report}</Table.Th>
                <Table.Th>{rt.format}</Table.Th>
                <Table.Th>{rt.requestedAt}</Table.Th>
                <Table.Th>{rt.status}</Table.Th>
                <Table.Th ta="right">{rt.rowCount}</Table.Th>
                <Table.Th>{rt.expires}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {jobs.map((job) => (
                <Table.Tr key={job.id}>
                  <Table.Td>{job.title}</Table.Td>
                  <Table.Td>{job.file_format_display}</Table.Td>
                  <Table.Td>{formatDateTime(job.created_at)}</Table.Td>
                  <Table.Td>
                    <Badge color={STATUS_COLORS[job.status]}>{job.status_display}</Badge>
                    {job.error && (
                      <Text size="xs" c="red">
                        {job.error}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">{formatNumber(job.row_count)}</Table.Td>
                  <Table.Td>{formatDateTime(job.expires_at)}</Table.Td>
                  <Table.Td>
                    {job.can_download && (
                      <Anchor href={jobDownloadUrl(job.id)}>{rt.download}</Anchor>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}
