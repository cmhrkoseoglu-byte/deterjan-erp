import {
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
  Modal,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowBackUp,
  IconArrowLeft,
  IconArrowsTransferDown,
  IconCheck,
  IconLock,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  getLot,
  getLotTrace,
  listMovements,
  reverseMovement,
  type StockMovement,
  type TraceDirection,
} from "../../api/inventory";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { AttachmentPanel } from "../../components/attachments/AttachmentPanel";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ct } from "../common/strings";
import { LotQualitySection } from "../quality/LotQualitySection";
import {
  INVENTORY_BASE,
  LOT_BLOCK_ROLES,
  MANUAL_RELEASE_ROLES,
  receiptPath,
  STOCK_WRITE_ROLES,
} from "./config";
import { LotDecisionModal, type LotDecision } from "./LotDecisionModal";
import { LotLabelButton, PalletSection } from "./LotLabels";
import { ExpiryText, Info, LotStatusBadge, Qty } from "./shared";
import { it } from "./strings";
import { TraceTree } from "./TraceTree";
import { TransferModal } from "./TransferModal";

/** Lot detay: durum, lokasyon bakiyeleri, soy ağacı (geri/ileri), hareketler, yorum paneli. */
export function LotPage() {
  const lotId = Number(useParams().lotId);
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canBlock = hasAnyRole(user, LOT_BLOCK_ROLES);
  const canRelease = hasAnyRole(user, MANUAL_RELEASE_ROLES);
  const canMove = hasAnyRole(user, STOCK_WRITE_ROLES);
  const [direction, setDirection] = useState<TraceDirection>("backward");
  const [decision, setDecision] = useState<LotDecision | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [reversing, setReversing] = useState<StockMovement | null>(null);

  const lot = useQuery({ queryKey: ["inventory", "lot", lotId], queryFn: () => getLot(lotId) });
  const trace = useQuery({
    queryKey: ["inventory", "lot", lotId, "trace", direction],
    queryFn: () => getLotTrace(lotId, direction),
  });
  const movements = useQuery({
    queryKey: ["inventory", "lot", lotId, "movements"],
    queryFn: () => listMovements({ lot: lotId, page_size: 200 }),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["inventory"] });

  if (lot.isLoading) return <Loader />;
  if (lot.isError || !lot.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(lot.error)}
      </Alert>
    );
  const data = lot.data;
  const allowed = new Set(data.allowed_transitions);
  const inQuarantine = data.balances.some((row) => row.location_type === "QUARANTINE");

  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <Stack>
          <Anchor component={Link} to={`${INVENTORY_BASE}/lotlar`} size="sm">
            <Group gap={4}>
              <IconArrowLeft size={14} />
              {it.tabs.lots}
            </Group>
          </Anchor>
          <Group justify="space-between" align="flex-start">
            <Group>
              <Title order={2}>{data.lot_no}</Title>
              <LotStatusBadge status={data.status} />
              {data.is_expired && (
                <Badge color="red" variant="filled">
                  {it.expired}
                </Badge>
              )}
            </Group>
            <Group gap="xs">
              {canRelease && allowed.has("RELEASED") && (
                <Button
                  color="green"
                  variant="light"
                  leftSection={<IconCheck size={16} />}
                  onClick={() => setDecision("release")}
                >
                  {it.manualRelease}
                </Button>
              )}
              {canBlock && allowed.has("BLOCKED") && (
                <Button
                  color="orange"
                  variant="light"
                  leftSection={<IconLock size={16} />}
                  onClick={() => setDecision("block")}
                >
                  {it.block}
                </Button>
              )}
              {canMove && data.balances.length > 0 && (
                <Button
                  variant="default"
                  leftSection={<IconArrowsTransferDown size={16} />}
                  onClick={() => setTransferOpen(true)}
                >
                  {it.transfer}
                </Button>
              )}
              <LotLabelButton lot={data} />
            </Group>
          </Group>

          <Paper withBorder p="md" radius="md">
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
              <Info label={it.material}>
                <Text size="sm">{`${data.material_code} - ${data.material_name}`}</Text>
              </Info>
              <Info label={it.total}>
                <Qty value={data.total_quantity} unit={data.unit} />
              </Info>
              <Info label={it.source}>
                <Text size="sm">{data.source_display}</Text>
                {data.receipt && (
                  <Anchor component={Link} to={receiptPath(data.receipt.id)} size="sm">
                    {data.receipt.number}
                  </Anchor>
                )}
              </Info>
              <Info label={it.expiry}>
                <ExpiryText date={data.expiry_date} expired={data.is_expired} />
              </Info>
              <Info label={it.manufactured}>
                <Text size="sm">{formatDate(data.manufactured_at)}</Text>
              </Info>
              <Info label={it.supplier}>
                <Text size="sm">
                  {[data.supplier_name, data.supplier_lot_no].filter(Boolean).join(" · ")}
                </Text>
              </Info>
              {data.released_by_name && (
                <Info label={it.releasedBy}>
                  <Text size="sm">{`${data.released_by_name} · ${formatDateTime(data.released_at)}`}</Text>
                </Info>
              )}
              {data.status_note && (
                <Info label={it.statusNote}>
                  <Text size="sm">{data.status_note}</Text>
                </Info>
              )}
            </SimpleGrid>
          </Paper>

          <LotQualitySection lot={data} />
          <PalletSection lot={data} />

          <Title order={4}>{it.balances}</Title>
          {data.balances.length === 0 ? (
            <Text size="sm" c="dimmed">
              {it.noStock}
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={360}>
              <Table striped>
                <Table.Tbody>
                  {data.balances.map((row) => (
                    <Table.Tr key={row.location}>
                      <Table.Td>{`${row.location_code} - ${row.location_name}`}</Table.Td>
                      <Table.Td ta="right">
                        <Qty value={row.quantity} unit={data.unit} />
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}

          <Group justify="space-between">
            <Title order={4}>{it.trace}</Title>
            <SegmentedControl
              size="xs"
              value={direction}
              onChange={(value) => setDirection(value as TraceDirection)}
              data={[
                { value: "backward", label: it.traceBackward },
                { value: "forward", label: it.traceForward },
              ]}
            />
          </Group>
          <Paper withBorder p="sm" radius="md">
            {trace.isLoading ? (
              <Loader size="sm" />
            ) : trace.data && trace.data.children.length > 0 ? (
              <TraceTree root={trace.data} />
            ) : (
              <Text size="sm" c="dimmed">
                {direction === "backward" ? it.traceEmptyBackward : it.traceEmptyForward}
              </Text>
            )}
          </Paper>

          <Title order={4}>{it.movements}</Title>
          <Table.ScrollContainer minWidth={640}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{it.date}</Table.Th>
                  <Table.Th>{it.movementType}</Table.Th>
                  <Table.Th>{it.location}</Table.Th>
                  <Table.Th ta="right">{it.quantity}</Table.Th>
                  <Table.Th>{it.document}</Table.Th>
                  <Table.Th>{it.createdBy}</Table.Th>
                  {canMove && <Table.Th />}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(movements.data?.results ?? []).map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td style={{ whiteSpace: "nowrap" }}>
                      {formatDateTime(row.created_at)}
                    </Table.Td>
                    <Table.Td>
                      {row.movement_type_display}
                      {row.is_reversed && (
                        <Badge ml={6} size="xs" color="gray">
                          {it.reversedBadge}
                        </Badge>
                      )}
                      {row.note && (
                        <Text size="xs" c="dimmed">
                          {row.note}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>{row.location_code}</Table.Td>
                    <Table.Td ta="right" c={Number(row.quantity) < 0 ? "red" : "green"}>
                      {`${Number(row.quantity) > 0 ? "+" : ""}${formatNumber(row.quantity)} ${row.unit}`}
                    </Table.Td>
                    <Table.Td>{row.document_number}</Table.Td>
                    <Table.Td>{row.created_by_name}</Table.Td>
                    {canMove && (
                      <Table.Td>
                        {!row.is_reversed && row.movement_type !== "REVERSAL" && (
                          <Button
                            size="compact-xs"
                            variant="subtle"
                            leftSection={<IconArrowBackUp size={14} />}
                            onClick={() => setReversing(row)}
                          >
                            {it.reverse}
                          </Button>
                        )}
                      </Table.Td>
                    )}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Stack>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <Stack>
          <AttachmentPanel
            contentType="inventory.lot"
            objectId={data.id}
            defaultKind={data.source === "PURCHASE" ? "SUPPLIER_COA" : "OTHER"}
          />
          <RecordPanel contentType="inventory.lot" objectId={data.id} />
        </Stack>
      </Grid.Col>

      <LotDecisionModal
        lot={data}
        decision={decision}
        needsTarget={inQuarantine}
        onClose={() => setDecision(null)}
        onDone={() => {
          setDecision(null);
          refresh();
        }}
      />
      <TransferModal
        lot={data}
        opened={transferOpen}
        onClose={() => setTransferOpen(false)}
        onDone={() => {
          setTransferOpen(false);
          refresh();
        }}
      />
      <ReverseModal
        movement={reversing}
        onClose={() => setReversing(null)}
        onDone={() => {
          setReversing(null);
          refresh();
        }}
      />
    </Grid>
  );
}

function ReverseModal({
  movement,
  onClose,
  onDone,
}: {
  movement: StockMovement | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: () => reverseMovement(movement!.id, reason),
    onSuccess: () => {
      notifications.show({ color: "green", message: it.reversed });
      setReason("");
      onDone();
    },
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });
  return (
    <Modal opened={movement !== null} onClose={onClose} title={it.reverseTitle}>
      <Stack>
        {movement && (
          <Text size="sm">
            {`${movement.movement_type_display} · ${movement.location_code} · ${formatNumber(movement.quantity)} ${movement.unit}`}
          </Text>
        )}
        <Textarea
          label={it.reverseReason}
          withAsterisk
          autosize
          minRows={2}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button
            color="red"
            disabled={!reason.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {it.reverse}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
