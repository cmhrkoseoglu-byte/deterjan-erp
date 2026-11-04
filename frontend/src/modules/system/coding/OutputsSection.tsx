import { Alert, Badge, Button, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { getErrorMessage } from "../../../api/client";
import { listOutputs, type OutputDocumentRow } from "../../../api/coding";
import { formatDate } from "../../../i18n/format";
import { OutputModal } from "./OutputModal";
import { cs } from "./strings";

const OUTPUTS_KEY = ["system", "coding", "outputs"] as const;
const collator = new Intl.Collator("tr");

/** Çıktılar gruplarına göre (Türkçe sırayla). */
function grouped(rows: OutputDocumentRow[]): [string, OutputDocumentRow[]][] {
  const groups = new Map<string, OutputDocumentRow[]>();
  for (const row of rows) groups.set(row.group, [...(groups.get(row.group) ?? []), row]);
  return [...groups.entries()]
    .sort(([a], [b]) => collator.compare(a, b))
    .map(([group, items]) => [
      group,
      [...items].sort((a, b) => collator.compare(a.label, b.label)),
    ]);
}

function StateCell({ row }: { row: OutputDocumentRow }) {
  return (
    <Group gap={4}>
      <Badge color={row.is_active ? "teal" : "gray"}>
        {row.is_active ? cs.outputState.on : cs.outputState.off}
      </Badge>
      {row.template_changed && (
        <Badge color="orange" variant="light">
          {cs.templateChanged}
        </Badge>
      )}
      {row.legal && (
        <Badge color="yellow" variant="light">
          {cs.legal}
        </Badge>
      )}
    </Group>
  );
}

/** Kodlama > Çıktılar: basılı çıktıların doküman no, yayın tarihi, revizyon ve bant durumu. */
export function OutputsSection() {
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: OUTPUTS_KEY, queryFn: listOutputs });
  const rows = query.data ?? [];
  // Pencere listedeki güncel satırı gösterir (kaydedince yenilenir).
  const editing = rows.find((row) => row.key === editingKey) ?? null;

  function saved(row: OutputDocumentRow) {
    queryClient.setQueryData<OutputDocumentRow[]>(OUTPUTS_KEY, (old) =>
      old?.map((item) => (item.key === row.key ? row : item)),
    );
  }

  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{cs.outputsIntro}</Text>
        <Text size="sm" mt={4}>
          {cs.outputsHow}
        </Text>
      </Alert>
      {query.isLoading && <Loader />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isSuccess && (
        <Table.ScrollContainer minWidth={760}>
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{cs.colOutput}</Table.Th>
                <Table.Th>{cs.colDocCode}</Table.Th>
                <Table.Th>{cs.colRevision}</Table.Th>
                <Table.Th>{cs.colState}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {grouped(rows).map(([group, items]) => (
                <Fragment key={group}>
                  <Table.Tr bg="var(--mantine-color-default-hover)">
                    <Table.Th colSpan={5} scope="colgroup">
                      {group}
                    </Table.Th>
                  </Table.Tr>
                  {items.map((row) => (
                    <Table.Tr key={row.key}>
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          <Text size="sm">{row.label}</Text>
                          {row.formats.map((format) => (
                            <Badge key={format} size="xs" variant="outline" color="gray">
                              {format}
                            </Badge>
                          ))}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        {row.doc_code ? (
                          <Text size="sm" ff="monospace" style={{ whiteSpace: "nowrap" }}>
                            {row.doc_code}
                          </Text>
                        ) : (
                          <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                            {cs.suggested(row.suggested_code)}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: "nowrap" }}>
                        {row.revision_no === null
                          ? ""
                          : `${cs.revNo(row.revision_no)} · ${formatDate(row.revision_date)}`}
                      </Table.Td>
                      <Table.Td>
                        <StateCell row={row} />
                      </Table.Td>
                      <Table.Td>
                        <Button
                          size="xs"
                          variant="light"
                          onClick={() => setEditingKey(row.key)}
                          aria-label={`${cs.edit}: ${row.label}`}
                        >
                          {cs.edit}
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Fragment>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <OutputModal row={editing} onClose={() => setEditingKey(null)} onSaved={saved} />
    </Stack>
  );
}
