import {
  Alert,
  Anchor,
  Box,
  Button,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import {
  IconCornerDownRight,
  IconFileSpreadsheet,
  IconFileTypePdf,
  IconPlayerPlay,
} from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  getBackwardTrace,
  getForwardTrace,
  getRecall,
  recallExportUrl,
  type BackwardNode,
  type ForwardNode,
  type RecallResult,
} from "../../api/traceability";
import { formatDate, formatDateTime } from "../../i18n/format";
import { lotPath, receiptPath } from "../inventory/config";
import { LotStatusBadge, Qty } from "../inventory/shared";
import { LotMultiPicker, LotPicker } from "./LotPicker";
import { tt } from "./strings";

const BASE = "/izlenebilirlik";
const TABS = { backward: "geri", forward: "ileri", recall: "geri-cagirma" } as const;
type TabKey = keyof typeof TABS;

function tabFromPath(value: string | undefined): TabKey {
  const found = (Object.keys(TABS) as TabKey[]).find((key) => TABS[key] === value);
  return found ?? "backward";
}

/** İzlenebilirlik: geri ve ileri izleme, geri çağırma simülasyonu (laboratuvar, yönetim). */
export function TracePage() {
  const tab = tabFromPath(useParams().tab);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const lots = params.getAll("lot");
  const setLots = (ids: string[]) => {
    const next = new URLSearchParams();
    ids.forEach((id) => next.append("lot", id));
    setParams(next, { replace: true });
  };

  return (
    <Stack>
      <Title order={2}>{tt.title}</Title>
      <Tabs
        value={tab}
        onChange={(value) => {
          if (!value) return;
          const keep = value === "recall" ? lots : lots.slice(0, 1);
          const query = keep.map((id) => `lot=${id}`).join("&");
          navigate(`${BASE}/${TABS[value as TabKey]}${query ? `?${query}` : ""}`);
        }}
      >
        <Tabs.List>
          {(Object.keys(TABS) as TabKey[]).map((key) => (
            <Tabs.Tab key={key} value={key}>
              {tt.tabs[key]}
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      {tab === "recall" ? (
        <RecallPanel lots={lots} onChange={setLots} />
      ) : (
        <TracePanel
          direction={tab}
          lot={lots[0] ?? null}
          onChange={(id) => setLots(id ? [id] : [])}
        />
      )}
    </Stack>
  );
}

// --- geri / ileri izleme ---------------------------------------------------------------------

function TracePanel({
  direction,
  lot,
  onChange,
}: {
  direction: "backward" | "forward";
  lot: string | null;
  onChange: (id: string | null) => void;
}) {
  const query = useQuery<AnyNode>({
    queryKey: ["traceability", direction, lot],
    enabled: Boolean(lot),
    queryFn: () =>
      direction === "backward" ? getBackwardTrace(Number(lot)) : getForwardTrace(Number(lot)),
  });
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {direction === "backward" ? tt.backwardHint : tt.forwardHint}
      </Text>
      <LotPicker value={lot} onChange={onChange} />
      {!lot && (
        <Text size="sm" c="dimmed">
          {tt.pickLot}
        </Text>
      )}
      {query.isLoading && lot && <Loader size="sm" />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.data && (
        <Paper withBorder p="md" radius="md">
          <Stack gap={6}>
            <NodeRow node={query.data} depth={0} direction={direction} root />
            {query.data.children.length === 0 && (
              <Text size="sm" c="dimmed">
                {tt.noChildren}
              </Text>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}

type AnyNode = BackwardNode | ForwardNode;

function NodeRow({
  node,
  depth,
  direction,
  root = false,
}: {
  node: AnyNode;
  depth: number;
  direction: "backward" | "forward";
  root?: boolean;
}) {
  return (
    <>
      <Group gap="xs" wrap="wrap" pl={depth * 24} data-testid="trace-row">
        {!root && (
          <Box c="dimmed" style={{ flexShrink: 0 }}>
            <IconCornerDownRight size={16} />
          </Box>
        )}
        <Anchor component={Link} to={lotPath(node.id)} fw={600} size="sm">
          {node.lot_no}
        </Anchor>
        <Text size="sm">{`${node.material_code} - ${node.material_name}`}</Text>
        {node.quantity !== null && (
          <Text size="sm" c="dimmed" style={{ whiteSpace: "nowrap" }}>
            <Qty value={node.quantity} unit={node.quantity_unit ?? node.unit} />
          </Text>
        )}
        <LotStatusBadge status={node.status} />
        {direction === "backward" ? (
          <BackwardInfo node={node as BackwardNode} />
        ) : (
          <ForwardInfo node={node as ForwardNode} />
        )}
      </Group>
      {(node.children as AnyNode[]).map((child) => (
        <NodeRow
          key={`${node.id}-${child.id}`}
          node={child}
          depth={depth + 1}
          direction={direction}
        />
      ))}
    </>
  );
}

function Tag({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
      {`${label}: `}
      <Text span size="xs" c="var(--mantine-color-text)">
        {children}
      </Text>
    </Text>
  );
}

function BackwardInfo({ node }: { node: BackwardNode }) {
  return (
    <>
      {node.supplier_name && <Tag label={tt.supplier}>{node.supplier_name}</Tag>}
      {node.supplier_lot_no && <Tag label={tt.supplierLot}>{node.supplier_lot_no}</Tag>}
      {node.receipt_id && (
        <Tag label={tt.receipt}>
          <Anchor component={Link} to={receiptPath(node.receipt_id)} size="xs">
            {`${node.receipt_number} (${formatDate(node.receipt_date)})`}
          </Anchor>
        </Tag>
      )}
    </>
  );
}

function ForwardInfo({ node }: { node: ForwardNode }) {
  return (
    <>
      <Tag label={tt.onHand}>
        <Qty value={node.on_hand} unit={node.unit} />
      </Tag>
      {Number(node.shipped) > 0 && (
        <Tag label={tt.shipped}>
          <Qty value={node.shipped} unit={node.unit} />
        </Tag>
      )}
      {Number(node.returned) > 0 && (
        <Tag label={tt.returned}>
          <Qty value={node.returned} unit={node.unit} />
        </Tag>
      )}
    </>
  );
}

// --- geri çağırma ----------------------------------------------------------------------------

function RecallPanel({ lots, onChange }: { lots: string[]; onChange: (ids: string[]) => void }) {
  const [run, setRun] = useState<number[] | null>(lots.length ? lots.map(Number) : null);
  const query = useQuery({
    queryKey: ["traceability", "recall", run],
    enabled: Boolean(run?.length),
    queryFn: () => getRecall(run!),
  });
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        {tt.recallHint}
      </Text>
      <Group align="flex-end">
        <LotMultiPicker value={lots} onChange={onChange} />
        <Button
          leftSection={<IconPlayerPlay size={16} />}
          disabled={lots.length === 0}
          onClick={() => setRun(lots.map(Number))}
        >
          {tt.run}
        </Button>
      </Group>
      {!run && (
        <Text size="sm" c="dimmed">
          {tt.pickLots}
        </Text>
      )}
      {query.isLoading && run && <Loader size="sm" />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.data && run && <RecallView result={query.data} lots={run} />}
    </Stack>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <Stack gap="xs">
      <Title order={4}>{`${title} (${count})`}</Title>
      {count === 0 ? (
        <Text size="sm" c="dimmed">
          {tt.empty}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table striped fz="sm">
            {children}
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

function customerLabel(row: { customer_code: string | null; customer_name: string | null }) {
  return row.customer_name ? `${row.customer_code} - ${row.customer_name}` : tt.noCustomer;
}

function RecallView({ result, lots }: { result: RecallResult; lots: number[] }) {
  const summaryKeys = Object.keys(tt.summary) as (keyof RecallResult["summary"])[];
  return (
    <Stack gap="lg">
      <Group justify="flex-end" gap="xs">
        <Button
          component="a"
          href={recallExportUrl(lots, "xlsx")}
          variant="default"
          leftSection={<IconFileSpreadsheet size={16} />}
        >
          {tt.excel}
        </Button>
        <Button
          component="a"
          href={recallExportUrl(lots, "pdf")}
          target="_blank"
          variant="default"
          leftSection={<IconFileTypePdf size={16} />}
        >
          {tt.pdf}
        </Button>
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }}>
        {summaryKeys.map((key) => (
          <Paper key={key} withBorder p="sm" radius="md" data-testid="recall-summary">
            <Text size="xs" c="dimmed">
              {tt.summary[key]}
            </Text>
            <Text size="xl" fw={700}>
              {result.summary[key]}
            </Text>
          </Paper>
        ))}
      </SimpleGrid>

      <Section title={tt.customers} count={result.customers.length}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{tt.customer}</Table.Th>
            <Table.Th>{tt.product}</Table.Th>
            <Table.Th ta="right">{tt.quantity}</Table.Th>
            <Table.Th>{tt.lots}</Table.Th>
            <Table.Th>{tt.document}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {result.customers.map((row) => (
            <Table.Tr key={`${row.customer_id}-${row.material_id}`}>
              <Table.Td>{customerLabel(row)}</Table.Td>
              <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
              <Table.Td ta="right">
                <Qty value={row.quantity} unit={row.unit} />
              </Table.Td>
              <Table.Td>{row.lots.join(", ")}</Table.Td>
              <Table.Td>{row.documents.join(", ")}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Section>

      <Section title={tt.shipments} count={result.shipments.length}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{tt.document}</Table.Th>
            <Table.Th>{tt.date}</Table.Th>
            <Table.Th>{tt.customer}</Table.Th>
            <Table.Th>{tt.lot}</Table.Th>
            <Table.Th ta="right">{tt.quantity}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {result.shipments.map((row) => (
            <Table.Tr key={`${row.lot_id}-${row.document_number}-${row.source_id}`}>
              <Table.Td>{row.document_number}</Table.Td>
              <Table.Td>{formatDateTime(row.shipped_at)}</Table.Td>
              <Table.Td>{customerLabel(row)}</Table.Td>
              <Table.Td>
                <Anchor component={Link} to={lotPath(row.lot_id)} size="sm">
                  {row.lot_no}
                </Anchor>
              </Table.Td>
              <Table.Td ta="right">
                <Qty value={row.quantity} unit={row.unit} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Section>

      <Section title={tt.stock} count={result.stock.length}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{tt.lot}</Table.Th>
            <Table.Th>{tt.material}</Table.Th>
            <Table.Th>{tt.location}</Table.Th>
            <Table.Th ta="right">{tt.quantity}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {result.stock.map((row) => (
            <Table.Tr key={`${row.lot_id}-${row.location_id}`}>
              <Table.Td>
                <Anchor component={Link} to={lotPath(row.lot_id)} size="sm">
                  {row.lot_no}
                </Anchor>
              </Table.Td>
              <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
              <Table.Td>{`${row.warehouse_code} / ${row.location_code}`}</Table.Td>
              <Table.Td ta="right">
                <Qty value={row.quantity} unit={row.unit} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Section>

      <Section title={tt.affected} count={result.lots.length}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{tt.lot}</Table.Th>
            <Table.Th>{tt.material}</Table.Th>
            <Table.Th>{tt.status}</Table.Th>
            <Table.Th ta="right">{tt.onHand}</Table.Th>
            <Table.Th ta="right">{tt.shipped}</Table.Th>
            <Table.Th ta="right">{tt.returned}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {result.lots.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <Anchor
                    component={Link}
                    to={lotPath(row.id)}
                    size="sm"
                    fw={row.is_selected ? 700 : undefined}
                  >
                    {row.lot_no}
                  </Anchor>
                  {row.is_selected && (
                    <Text size="xs" c="dimmed">
                      {tt.selected}
                    </Text>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
              <Table.Td>
                <LotStatusBadge status={row.status} />
              </Table.Td>
              <Table.Td ta="right">
                <Qty value={row.on_hand} unit={row.unit} />
              </Table.Td>
              <Table.Td ta="right">
                <Qty value={row.shipped} unit={row.unit} />
              </Table.Td>
              <Table.Td ta="right">
                <Qty value={row.returned} unit={row.unit} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Section>
    </Stack>
  );
}
