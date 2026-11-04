import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Pagination,
  SegmentedControl,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getErrorMessage } from "../../../api/client";
import {
  listCodeRevisions,
  listCodeTypes,
  type CodeSchemeRevision,
  type CodeTypeRow,
} from "../../../api/coding";
import { formatDateTime } from "../../../i18n/format";
import { CodeSchemeModal } from "./CodeSchemeModal";
import { RecodeSection } from "./RecodeSection";
import { cs } from "./strings";

const SECTIONS = {
  master: "ana-veri",
  documents: "belge",
  lots: "lot",
  migration: "goc",
  history: "gecmis",
} as const;
type Section = keyof typeof SECTIONS;
const TYPES_KEY = ["system", "coding", "types"] as const;

function sectionFrom(value: string | null): Section {
  return (Object.keys(SECTIONS) as Section[]).find((key) => SECTIONS[key] === value) ?? "master";
}

function StateBadge({ row }: { row: CodeTypeRow }) {
  if (row.kind === "standard") return <Badge color="gray">{cs.state.standard}</Badge>;
  if (row.locked) return <Badge color="gray">{cs.state.locked}</Badge>;
  if (row.kind !== "master") return null;
  return (
    <Group gap={4}>
      <Badge color={row.is_active ? "teal" : "gray"}>
        {row.is_active ? cs.state.active : cs.state.inactive}
      </Badge>
    </Group>
  );
}

function formatCell(row: CodeTypeRow) {
  if (row.kind === "standard") return <Text size="sm">{row.samples.join(", ")}</Text>;
  if (row.free) return <Text size="sm">{cs.state.free}</Text>;
  if (row.types.length) {
    return (
      <Stack gap={0}>
        {row.types.map((type) => (
          <Text key={type.value} size="sm">
            {type.label}: {type.format}
          </Text>
        ))}
      </Stack>
    );
  }
  return <Text size="sm">{row.format}</Text>;
}

function nextCell(row: CodeTypeRow) {
  if (row.types.length) {
    return (
      <Stack gap={0}>
        {row.types.map((type) => (
          <Text key={type.value} size="sm" ff="monospace" style={{ whiteSpace: "nowrap" }}>
            {type.next}
          </Text>
        ))}
      </Stack>
    );
  }
  return (
    <Text size="sm" ff="monospace" style={{ whiteSpace: "nowrap" }}>
      {row.next}
    </Text>
  );
}

function changedCell(row: CodeTypeRow) {
  if (!row.updated_at) return "";
  return `${formatDateTime(row.updated_at)}${row.updated_by ? ` · ${row.updated_by}` : ""}`;
}

function TypeTable({
  rows,
  lastLabel,
  onEdit,
}: {
  rows: CodeTypeRow[];
  lastLabel?: string;
  onEdit: (row: CodeTypeRow) => void;
}) {
  return (
    <Table.ScrollContainer minWidth={720}>
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{cs.colType}</Table.Th>
            <Table.Th>{cs.colFormat}</Table.Th>
            <Table.Th>{cs.colNext}</Table.Th>
            {lastLabel && <Table.Th>{lastLabel}</Table.Th>}
            <Table.Th>{cs.colState}</Table.Th>
            <Table.Th>{cs.colChanged}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.key}>
              <Table.Td>{row.label}</Table.Td>
              <Table.Td>{formatCell(row)}</Table.Td>
              <Table.Td>{row.kind === "standard" || row.free ? "" : nextCell(row)}</Table.Td>
              {lastLabel && <Table.Td>{row.last_number}</Table.Td>}
              <Table.Td>
                <StateBadge row={row} />
              </Table.Td>
              <Table.Td>
                <Text size="xs" c="dimmed">
                  {changedCell(row)}
                </Text>
              </Table.Td>
              <Table.Td>
                {row.configurable && (
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => onEdit(row)}
                    aria-label={`${cs.edit}: ${row.label}`}
                  >
                    {cs.edit}
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function describeRevision(revision: CodeSchemeRevision): string {
  const parts: string[] = [];
  const prefixes = Object.values(revision.type_prefixes);
  if (prefixes.length) parts.push(`${cs.prefix}: ${prefixes.join(", ")}`);
  else if (revision.prefix) parts.push(`${cs.prefix}: ${revision.prefix}`);
  parts.push(`${cs.width}: ${revision.width}`);
  if (revision.year_format) parts.push(`${cs.yearFormat}: ${revision.year_format}`);
  if (revision.date_format) parts.push(`${cs.dateFormat}: ${revision.date_format}`);
  if (revision.key.startsWith("document.") || revision.key.startsWith("lot.")) {
    // belge ve lotta etkinlik yok
  } else {
    parts.push(revision.is_active ? cs.state.active : cs.state.inactive);
  }
  for (const [prefix, next] of Object.entries(revision.counters)) {
    parts.push(cs.counterSet(prefix, next));
  }
  return parts.join(" · ");
}

function HistorySection() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["system", "coding", "revisions", page],
    queryFn: () => listCodeRevisions(page),
    placeholderData: keepPreviousData,
  });
  if (query.isLoading) return <Loader />;
  if (query.isError) {
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  }
  const rows = query.data?.results ?? [];
  if (!rows.length) return <Text c="dimmed">{cs.historyEmpty}</Text>;
  const pages = Math.ceil((query.data?.count ?? 0) / 50);
  return (
    <Stack>
      <Table.ScrollContainer minWidth={720}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{cs.colWhen}</Table.Th>
              <Table.Th>{cs.colType}</Table.Th>
              <Table.Th>{cs.colWho}</Table.Th>
              <Table.Th>{cs.colWhat}</Table.Th>
              <Table.Th>{cs.colNote}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((revision) => (
              <Table.Tr key={revision.id}>
                <Table.Td>{formatDateTime(revision.changed_at)}</Table.Td>
                <Table.Td>
                  {revision.label} ({cs.revision(revision.revision)})
                </Table.Td>
                <Table.Td>{revision.changed_by_name}</Table.Td>
                <Table.Td>
                  <Text size="sm">{describeRevision(revision)}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{revision.note}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {pages > 1 && <Pagination value={page} onChange={setPage} total={pages} />}
    </Stack>
  );
}

/** Sistem > Kodlama sistematiği (yalnız admin): ana veri kod biçimleri, belge ve lot numaraları,
 * değişiklik geçmişi. */
export function CodingPanel() {
  const [params, setParams] = useSearchParams();
  const section = sectionFrom(params.get("bolum"));
  const [editing, setEditing] = useState<CodeTypeRow | null>(null);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: TYPES_KEY, queryFn: () => listCodeTypes() });
  const rows = query.data ?? [];

  function select(value: string) {
    const next = new URLSearchParams(params);
    next.set("bolum", SECTIONS[value as Section]);
    setParams(next, { replace: true });
  }

  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{cs.intro}</Text>
        <Text size="sm" mt={4}>
          {cs.iso}
        </Text>
      </Alert>
      <SegmentedControl
        value={section}
        onChange={select}
        data={(Object.keys(SECTIONS) as Section[]).map((key) => ({
          value: key,
          label: cs.sections[key],
        }))}
      />
      {query.isLoading && <Loader />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isSuccess && section === "master" && (
        <TypeTable
          rows={rows.filter((row) => row.kind === "master" || row.kind === "standard")}
          onEdit={setEditing}
        />
      )}
      {query.isSuccess && section === "documents" && (
        <Stack gap="xs">
          <TypeTable
            rows={rows.filter((row) => row.kind === "document")}
            lastLabel={cs.colLastYear}
            onEdit={setEditing}
          />
          <Text size="xs" c="dimmed">
            {cs.lockedHelp}
          </Text>
        </Stack>
      )}
      {query.isSuccess && section === "lots" && (
        <TypeTable
          rows={rows.filter((row) => row.kind === "lot")}
          lastLabel={cs.colLastToday}
          onEdit={setEditing}
        />
      )}
      {query.isSuccess && section === "migration" && <RecodeSection types={rows} />}
      {section === "history" && <HistorySection />}
      <CodeSchemeModal
        row={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          void queryClient.invalidateQueries({ queryKey: ["system", "coding"] });
        }}
      />
    </Stack>
  );
}
