import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Pagination,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { IconArrowLeft, IconDownload, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  comparisonExportUrl,
  getComparison,
  listComparisonLines,
  type ComparisonLine,
} from "../../api/golive";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { gt } from "./strings";

const PAGE_SIZE = 50;

function lineNote(line: ComparisonLine): string {
  if (!line.in_file) return gt.notInFile;
  if (Number(line.system_quantity) === 0 && Number(line.file_quantity) !== 0) return gt.notInSystem;
  return "";
}

/** Bir stok karşılaştırmasının satırları: önce farklılar. */
export function ComparisonPage() {
  const id = Number(useParams().comparisonId);
  const [page, setPage] = useState(1);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search, 300);
  const header = useQuery({
    queryKey: ["golive", "comparison", id],
    queryFn: () => getComparison(id),
  });
  const params = {
    page,
    page_size: PAGE_SIZE,
    only_differences: onlyDiff,
    search: debounced || undefined,
  };
  const lines = useQuery({
    queryKey: ["golive", "comparison", id, "lines", params],
    queryFn: () => listComparisonLines(id, params),
    placeholderData: keepPreviousData,
  });
  const comparison = header.data;
  const rows = lines.data?.results ?? [];
  const pages = Math.max(1, Math.ceil((lines.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Stack>
      <Anchor component={Link} to="/gecis/karsilastirma" size="sm">
        <Group gap={4}>
          <IconArrowLeft size={16} />
          {gt.back}
        </Group>
      </Anchor>
      {header.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(header.error)}
        </Alert>
      )}
      {comparison && (
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Title order={2}>{comparison.number}</Title>
            <Text size="sm">
              {gt.date}: {formatDate(comparison.as_of_date)} · {gt.level}:{" "}
              {comparison.level_display}
            </Text>
            <Text size="sm" c="dimmed">
              {comparison.file_name} · {comparison.created_by_name} ·{" "}
              {formatDateTime(comparison.created_at)}
            </Text>
            {comparison.note && <Text size="sm">{comparison.note}</Text>}
            <Badge color={comparison.difference_count ? "red" : "green"} variant="light">
              {comparison.difference_count
                ? gt.comparisonSummary(comparison.line_count, comparison.difference_count)
                : gt.noDifference}
            </Badge>
          </Stack>
          <Button
            component="a"
            href={comparisonExportUrl(id)}
            download
            variant="default"
            leftSection={<IconDownload size={16} />}
          >
            {gt.export}
          </Button>
        </Group>
      )}
      <Group>
        <TextInput
          aria-label={gt.search}
          placeholder={gt.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            setPage(1);
          }}
          w={280}
        />
        <Switch
          label={gt.onlyDifferences}
          checked={onlyDiff}
          onChange={(event) => {
            setOnlyDiff(event.currentTarget.checked);
            setPage(1);
          }}
        />
      </Group>
      <Table.ScrollContainer minWidth={760}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{gt.material}</Table.Th>
              <Table.Th>{gt.lot}</Table.Th>
              <Table.Th>{gt.location}</Table.Th>
              <Table.Th ta="right">{gt.fileQty}</Table.Th>
              <Table.Th ta="right">{gt.systemQty}</Table.Th>
              <Table.Th ta="right">{gt.diff}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((line) => {
              const diff = Number(line.difference);
              return (
                <Table.Tr key={line.id}>
                  <Table.Td>
                    {line.material_code}
                    <Text size="xs" c="dimmed">
                      {line.material_name}
                    </Text>
                  </Table.Td>
                  <Table.Td>{line.lot_no}</Table.Td>
                  <Table.Td>{line.location_code}</Table.Td>
                  <Table.Td ta="right">{formatNumber(line.file_quantity)}</Table.Td>
                  <Table.Td ta="right">{formatNumber(line.system_quantity)}</Table.Td>
                  <Table.Td
                    ta="right"
                    c={diff === 0 ? undefined : "red"}
                    fw={diff ? 600 : undefined}
                  >
                    {formatNumber(line.difference)} {line.unit}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {lineNote(line)}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              );
            })}
            {!lines.isLoading && rows.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text c="dimmed">{gt.noDifference}</Text>
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
