import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  FileInput,
  Group,
  Modal,
  Pagination,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDownload, IconFileSpreadsheet, IconPlus } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  COMPARISON_TEMPLATE_URL,
  createComparison,
  listComparisons,
  type StockComparison,
} from "../../api/golive";
import type { ImportReport } from "../../api/masterdata";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime } from "../../i18n/format";
import { ReportView } from "../common/ImportModal";
import { reportFromError } from "../common/importReport";
import { ct } from "../common/strings";
import { comparisonPath } from "./paths";
import { gt } from "./strings";

const PAGE_SIZE = 50;

function NewComparisonModal({
  opened,
  onClose,
  onCreated,
}: {
  opened: boolean;
  onClose: () => void;
  onCreated: (comparison: StockComparison) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [asOf, setAsOf] = useState("");
  const [onlyFile, setOnlyFile] = useState(false);
  const [note, setNote] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState("");

  const create = useMutation({
    mutationFn: () =>
      createComparison({
        file: file!,
        as_of_date: asOf || null,
        only_file_materials: onlyFile,
        note,
      }),
    onSuccess: (comparison) => {
      notifications.show({ color: "green", message: gt.compared(comparison.difference_count) });
      setFile(null);
      setReport(null);
      setNote("");
      onCreated(comparison);
    },
    onError: (err) => {
      const failed = reportFromError(err);
      setReport(failed);
      setError(failed ? "" : getErrorMessage(err));
    },
  });

  return (
    <Modal opened={opened} onClose={onClose} title={gt.newComparison} size="xl">
      <Stack>
        <Text size="sm">{gt.comparisonIntro}</Text>
        <Anchor href={COMPARISON_TEMPLATE_URL} download size="sm">
          <Group gap={4}>
            <IconDownload size={16} />
            {gt.template}
          </Group>
        </Anchor>
        <FileInput
          label={gt.file}
          accept=".xlsx,.csv"
          leftSection={<IconFileSpreadsheet size={16} />}
          value={file}
          onChange={(value) => {
            setFile(value);
            setReport(null);
            setError("");
          }}
          clearable
          required
        />
        <TextInput
          type="date"
          label={gt.asOf}
          description={gt.asOfHelp}
          value={asOf}
          onChange={(event) => setAsOf(event.currentTarget.value)}
          w={220}
        />
        <Checkbox
          label={gt.onlyFile}
          description={gt.onlyFileHelp}
          checked={onlyFile}
          onChange={(event) => setOnlyFile(event.currentTarget.checked)}
        />
        <Textarea
          label={gt.note}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
          autosize
          minRows={1}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        {report && <ReportView report={report} hasErrors />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.close}
          </Button>
          <Button disabled={!file} loading={create.isPending} onClick={() => create.mutate()}>
            {gt.compare}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function ComparisonsTab() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canCreate = hasAnyRole(user, ["depo", "yonetim"]);
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const list = useQuery({
    queryKey: ["golive", "comparisons", page],
    queryFn: () => listComparisons({ page }),
    placeholderData: keepPreviousData,
  });
  const rows = list.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((list.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" maw={720}>
          {gt.comparisonIntro}
        </Text>
        {canCreate && (
          <Button leftSection={<IconPlus size={16} />} onClick={() => setModalOpen(true)}>
            {gt.newComparison}
          </Button>
        )}
      </Group>
      {list.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(list.error)}
        </Alert>
      )}
      <Table.ScrollContainer minWidth={720}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{gt.number}</Table.Th>
              <Table.Th>{gt.date}</Table.Th>
              <Table.Th>{gt.level}</Table.Th>
              <Table.Th>{gt.differences}</Table.Th>
              <Table.Th>{gt.createdBy}</Table.Th>
              <Table.Th>{gt.note}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr
                key={row.id}
                style={{ cursor: "pointer" }}
                onClick={() => navigate(comparisonPath(row.id))}
              >
                <Table.Td>{row.number}</Table.Td>
                <Table.Td>{formatDate(row.as_of_date)}</Table.Td>
                <Table.Td>{row.level_display}</Table.Td>
                <Table.Td>
                  {row.difference_count === 0 ? (
                    <Badge color="green" variant="light">
                      {gt.noDifference}
                    </Badge>
                  ) : (
                    <Badge color="red" variant="light">
                      {gt.comparisonSummary(row.line_count, row.difference_count)}
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  {row.created_by_name}
                  <Text size="xs" c="dimmed">
                    {formatDateTime(row.created_at)}
                  </Text>
                </Table.Td>
                <Table.Td>{row.note}</Table.Td>
              </Table.Tr>
            ))}
            {!list.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed">{gt.empty}</Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
      <NewComparisonModal
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreated={(comparison) => {
          setModalOpen(false);
          void queryClient.invalidateQueries({ queryKey: ["golive", "comparisons"] });
          navigate(comparisonPath(comparison.id));
        }}
      />
    </Stack>
  );
}
