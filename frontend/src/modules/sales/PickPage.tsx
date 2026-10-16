import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Chip,
  Group,
  Loader,
  Modal,
  Paper,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconPackageExport } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorCode, getErrorMessage } from "../../api/client";
import {
  getShipment,
  loadShipment,
  pickLot,
  shipmentSuggestions,
  undoPick,
  type PickSuggestion,
  type ShipmentDetail,
  type ShipmentPick,
} from "../../api/sales";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { ScanInput, type ScanInputHandle } from "../../components/scan/ScanInput";
import { formatDate, formatNumber } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { ExpiryText, Qty } from "../inventory/shared";
import { PICK_ROLES, PICKABLE_STATUSES, SALES_BASE, shipmentPath } from "./config";
import { ShipmentStatusBadge } from "./shared";
import { PicksTable } from "./ShipmentPage";
import { lineRemaining, useShipmentRefresh } from "./shipmentUtils";
import { st } from "./strings";

const remainingOf = (row: PickSuggestion) => Number(row.remaining_quantity);

/** Depo tablet ekranı: satır başına kalan miktar, lot okutma, FEFO önerisi, "Yükleme tamam". */
export function ShipmentPickPage() {
  const shipmentId = Number(useParams().shipmentId);
  const query = useQuery({
    queryKey: ["sales", "shipment", shipmentId],
    queryFn: () => getShipment(shipmentId),
  });
  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  return <Picking shipment={query.data} />;
}

function Picking({ shipment }: { shipment: ShipmentDetail }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const refresh = useShipmentRefresh();
  const canPick = hasAnyRole(user, PICK_ROLES) && PICKABLE_STATUSES.includes(shipment.status);
  const suggestions = useQuery({
    queryKey: ["sales", "pick-suggestions", shipment.id],
    queryFn: () => shipmentSuggestions(shipment.id),
    enabled: canPick,
  });
  const rows = suggestions.data ?? [];
  const firstOpen = rows.find((row) => remainingOf(row) > 0) ?? rows[0];
  const [selected, setSelected] = useState<number | null>(null);
  const current = rows.find((row) => row.line === (selected ?? firstOpen?.line)) ?? null;
  const [loadOpen, setLoadOpen] = useState(false);
  const [undoing, setUndoing] = useState<ShipmentPick | null>(null);
  const [error, setError] = useState("");

  const planned = shipment.lines.reduce((sum, line) => sum + Number(line.quantity), 0);
  const picked = shipment.lines.reduce((sum, line) => sum + Number(line.picked_quantity ?? 0), 0);
  const short = shipment.lines.some((line) => lineRemaining(line) > 0);
  const hasPicks = shipment.picks.some((pick) => !pick.returned_at);

  const load = useMutation({
    mutationFn: () => loadShipment(shipment.id),
    onSuccess: (saved) => {
      setLoadOpen(false);
      notifications.show({ color: "green", message: st.loaded });
      refresh(saved);
      navigate(`${SALES_BASE}/toplama`);
    },
    onError: (err) => {
      setLoadOpen(false);
      setError(getErrorMessage(err));
    },
  });
  const undo = useMutation({
    mutationFn: (pick: ShipmentPick) => undoPick(shipment.id, pick.id),
    onSuccess: (saved) => {
      setError("");
      setUndoing(null);
      notifications.show({ color: "green", message: st.undone });
      refresh(saved);
    },
    onError: (err) => {
      setUndoing(null);
      setError(getErrorMessage(err));
    },
  });

  return (
    <Stack>
      <Anchor component={Link} to={shipmentPath(shipment.id)} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {st.shipmentTitle(shipment.number)}
        </Group>
      </Anchor>
      <Group justify="space-between">
        <Group>
          <Title order={2}>{st.pickingTitle(shipment.number)}</Title>
          <ShipmentStatusBadge status={shipment.status} />
        </Group>
        <Text size="sm" c="dimmed">
          {[shipment.customer_name, shipment.vehicle_plate, formatDate(shipment.planned_date)]
            .filter(Boolean)
            .join(" · ")}
        </Text>
      </Group>
      <Progress value={planned ? Math.min(100, (picked / planned) * 100) : 0} size="lg" />
      {shipment.min_remaining_shelf_life_days != null && (
        <Alert color="yellow" variant="light" py="xs">
          {st.minShelfLife(shipment.min_remaining_shelf_life_days)}
        </Alert>
      )}
      {canPick && (
        <Text size="sm" c="dimmed">
          {st.pickingIntro}
        </Text>
      )}
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      {canPick && (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm" data-testid="pick-lines">
          {rows.map((row) => (
            <LineCard
              key={row.line}
              row={row}
              active={row.line === current?.line}
              onSelect={() => setSelected(row.line)}
            />
          ))}
        </SimpleGrid>
      )}
      {canPick && suggestions.isLoading && <Loader size="sm" />}

      {canPick && current && (
        <PickForm
          key={current.line}
          shipment={shipment}
          row={current}
          onPicked={(next) => {
            // Eksik kalan satırda kalınır; satır tamamlanınca sıradaki açık satıra geçilir.
            const same = next.find((row) => row.line === current.line);
            const open =
              same && remainingOf(same) > 0 ? same : next.find((row) => remainingOf(row) > 0);
            if (open) setSelected(open.line);
          }}
        />
      )}

      <Title order={4}>{st.picks}</Title>
      <PicksTable
        picks={shipment.picks}
        onUndo={canPick && shipment.status === "PICKING" ? setUndoing : undefined}
      />

      {canPick && shipment.status === "PICKING" && (
        <Paper withBorder p="md" radius="md">
          <Group justify="flex-end">
            <Button
              size="lg"
              color="green"
              leftSection={<IconPackageExport size={20} />}
              disabled={!hasPicks}
              onClick={() => setLoadOpen(true)}
            >
              {st.load}
            </Button>
          </Group>
        </Paper>
      )}

      <ConfirmModal
        opened={loadOpen}
        message={short ? st.loadPartialQuestion : st.loadQuestion}
        confirmLabel={st.load}
        loading={load.isPending}
        onConfirm={() => load.mutate()}
        onClose={() => setLoadOpen(false)}
      />
      <ConfirmModal
        opened={undoing !== null}
        message={undoing ? st.undoQuestion(undoing.lot_no) : ""}
        confirmLabel={st.undo}
        danger
        loading={undo.isPending}
        onConfirm={() => undoing && undo.mutate(undoing)}
        onClose={() => setUndoing(null)}
      />
    </Stack>
  );
}

function LineCard({
  row,
  active,
  onSelect,
}: {
  row: PickSuggestion;
  active: boolean;
  onSelect: () => void;
}) {
  const quantity = Number(row.quantity);
  const done = remainingOf(row) <= 0;
  return (
    <UnstyledButton onClick={onSelect} aria-pressed={active}>
      <Card
        withBorder
        padding="md"
        radius="md"
        style={{
          borderColor: active ? "var(--mantine-color-blue-6)" : undefined,
          borderWidth: active ? 2 : undefined,
        }}
      >
        <Group justify="space-between" wrap="nowrap">
          <Text fw={600}>{`${row.line_no}. ${row.product_code}`}</Text>
          {done ? (
            <Badge color="green">{st.done}</Badge>
          ) : (
            <Badge color="orange" variant="light">
              {`${st.remaining}: ${formatNumber(row.remaining_quantity)} ${row.unit}`}
            </Badge>
          )}
        </Group>
        <Text size="sm" c="dimmed" lineClamp={1}>
          {row.product_name}
        </Text>
        <Progress
          mt="xs"
          color={done ? "green" : "orange"}
          value={quantity ? Math.min(100, (Number(row.picked_quantity) / quantity) * 100) : 0}
        />
        <Text size="sm" mt={4}>
          {`${formatNumber(row.picked_quantity)} / ${formatNumber(row.quantity)} ${row.unit}`}
        </Text>
      </Card>
    </UnstyledButton>
  );
}

/**
 * Okutulan lot için önerilen miktar: satırın kalanı, lotun öneri satırlarındaki miktarla sınırlı.
 * Rezerve lot tüm lokasyonlardaki rezervasyonlarından toplanır (toplam); rezervesiz lot ise tek
 * lokasyondan alınır (backend `_free_stock_location`), bu yüzden en çok stoklu lokasyon esas alınır.
 */
function defaultQuantity(row: PickSuggestion, lotId: number): string {
  const remaining = remainingOf(row);
  if (remaining <= 0) return "";
  const own = row.suggestions.filter((item) => item.lot === lotId);
  if (own.length === 0) return trimDecimal(String(remaining));
  const reserved = own.filter((item) => item.reserved);
  const available = reserved.length
    ? reserved.reduce((sum, item) => sum + Number(item.quantity), 0)
    : Math.max(...own.map((item) => Number(item.quantity)));
  return trimDecimal(String(Math.min(remaining, available)));
}

function PickForm({
  shipment,
  row,
  onPicked,
}: {
  shipment: ShipmentDetail;
  row: PickSuggestion;
  onPicked: (rows: PickSuggestion[]) => void;
}) {
  const queryClient = useQueryClient();
  const refresh = useShipmentRefresh();
  const scanRef = useRef<ScanInputHandle>(null);
  const quantityRef = useRef<HTMLInputElement>(null);
  const [lot, setLot] = useState<{ id: number; lot_no: string } | null>(null);
  const [quantity, setQuantity] = useState("");
  const [reasonOpen, setReasonOpen] = useState(false);
  const [reason, setReason] = useState("");
  // İstek sürerken ikinci Enter ya da tıklama aynı toplamayı tekrar göndermesin. `isPending` bir
  // sonraki render'a kadar güncellenmediğinden ref ile hemen kilitlenir.
  const submitting = useRef(false);

  const pick = useMutation({
    mutationFn: (withReason: string) =>
      pickLot(shipment.id, {
        lot: lot!.id,
        quantity: quantity.trim() ? normalizeDecimal(quantity) : null,
        ...(withReason ? { reason: withReason } : {}),
      }),
    onSuccess: async (saved) => {
      notifications.show({ color: "green", message: st.pickedOk(lot!.lot_no) });
      setLot(null);
      setQuantity("");
      setReason("");
      setReasonOpen(false);
      scanRef.current?.clear();
      refresh(saved);
      const next = await queryClient.fetchQuery({
        queryKey: ["sales", "pick-suggestions", shipment.id],
        queryFn: () => shipmentSuggestions(shipment.id),
      });
      onPicked(next);
      scanRef.current?.focus();
    },
    onError: (err) => {
      if (getErrorCode(err) === "lot_not_reserved") {
        setReasonOpen(true);
        return;
      }
      setReasonOpen(false);
      scanRef.current?.showError(getErrorMessage(err));
    },
    onSettled: () => {
      submitting.current = false;
    },
  });

  function submit(withReason: string) {
    if (submitting.current || pick.isPending) return;
    submitting.current = true;
    pick.mutate(withReason);
  }

  function choose(id: number, lotNo: string) {
    setLot({ id, lot_no: lotNo });
    setQuantity(defaultQuantity(row, id));
    quantityRef.current?.focus();
    quantityRef.current?.select();
  }

  const canSubmit = lot !== null && remainingOf(row) > 0;

  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{`${row.product_code} - ${row.product_name}`}</Title>
          <Text size="sm">
            {`${st.remaining}: `}
            <Qty value={row.remaining_quantity} unit={row.unit} />
          </Text>
        </Group>
        <Group align="flex-start" grow>
          <ScanInput
            ref={scanRef}
            expect="lot"
            expectedMaterial={{ id: row.product, code: row.product_code }}
            label={st.scanLot}
            placeholder={st.scanPlaceholder}
            autoFocus
            disabled={remainingOf(row) <= 0}
            onLot={(scanned) => choose(scanned.id, scanned.lot_no)}
          />
          <TextInput
            ref={quantityRef}
            size="lg"
            label={`${st.pickQuantity} (${row.unit})`}
            description={st.pickQuantityHint}
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && canSubmit) submit("");
            }}
          />
        </Group>
        {lot && (
          <Text size="sm">
            {`${st.lot}: `}
            <Text span fw={700} data-testid="picked-lot">
              {lot.lot_no}
            </Text>
          </Text>
        )}
        <Text fw={600} size="sm">
          {st.fefo}
        </Text>
        {row.suggestions.length === 0 ? (
          <Text size="sm" c="dimmed">
            {st.noSuggestion}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={420}>
            <Table fz="md" verticalSpacing="sm" highlightOnHover data-testid="pick-suggestions">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{st.lot}</Table.Th>
                  <Table.Th>{st.location}</Table.Th>
                  <Table.Th>{st.expiry}</Table.Th>
                  <Table.Th ta="right">{st.quantity}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {row.suggestions.map((item) => {
                  const chosen = lot?.id === item.lot;
                  return (
                    <Table.Tr
                      key={`${item.lot}-${item.location}-${item.reserved ? "r" : "f"}`}
                      style={{ cursor: item.meets_shelf_life ? "pointer" : "not-allowed" }}
                      bg={chosen ? "var(--mantine-color-blue-light)" : undefined}
                      c={item.meets_shelf_life ? undefined : "dimmed"}
                      onClick={() => item.meets_shelf_life && choose(item.lot, item.lot_no)}
                    >
                      <Table.Td>{item.lot_no}</Table.Td>
                      <Table.Td>{item.location_code}</Table.Td>
                      <Table.Td>
                        <ExpiryText date={item.expiry_date} expired={!item.meets_shelf_life} />
                      </Table.Td>
                      <Table.Td ta="right">
                        <Qty value={item.quantity} unit={row.unit} />
                      </Table.Td>
                      <Table.Td>
                        {!item.meets_shelf_life ? (
                          <Badge color="red" variant="light">
                            {st.shelfLifeShort}
                          </Badge>
                        ) : (
                          item.reserved && <Badge variant="light">{st.reservedBadge}</Badge>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        <Group justify="flex-end">
          <Button
            size="lg"
            disabled={!canSubmit}
            loading={pick.isPending && !reasonOpen}
            onClick={() => submit("")}
          >
            {st.pick}
          </Button>
        </Group>
      </Stack>

      <Modal opened={reasonOpen} onClose={() => setReasonOpen(false)} title={st.otherLotTitle}>
        <Stack>
          <Text size="sm">{st.otherLotIntro(lot?.lot_no ?? "")}</Text>
          <Chip.Group value={reason} onChange={(value) => setReason(String(value))}>
            <Group gap="xs">
              {st.otherLotReasons.map((text) => (
                <Chip key={text} value={text}>
                  {text}
                </Chip>
              ))}
            </Group>
          </Chip.Group>
          <TextInput
            label={st.reason}
            withAsterisk
            maxLength={200}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setReasonOpen(false)}>
              {ct.cancel}
            </Button>
            <Button
              color="orange"
              disabled={!reason.trim()}
              loading={pick.isPending}
              onClick={() => submit(reason.trim())}
            >
              {st.pickWithReason}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  );
}
