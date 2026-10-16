import {
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowLeft,
  IconBarcode,
  IconEdit,
  IconFileTypePdf,
  IconPackageExport,
  IconTruckDelivery,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelShipment,
  dispatchShipment,
  getShipment,
  loadShipment,
  undoPick,
  waybillPdfUrl,
  type ShipmentDetail,
  type ShipmentLine,
  type ShipmentPick,
} from "../../api/sales";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { CancelModal } from "../inventory/CancelModal";
import { ExpiryText, Info, Qty } from "../inventory/shared";
import {
  customerPath,
  OPEN_SHIPMENT_STATUSES,
  PICK_ROLES,
  PICKABLE_STATUSES,
  pickPath,
  SALES_BASE,
  salesOrderPath,
  SHIPMENT_WRITE_ROLES,
  UNDOABLE_STATUSES,
} from "./config";
import { ShipmentStatusBadge } from "./shared";
import { EditShipmentModal } from "./ShipmentForms";
import { lineRemaining, useShipmentRefresh } from "./shipmentUtils";
import { st } from "./strings";

/** Sevkiyat detayı: satırlar, okutulan lotlar, yükleme onayı, sevk onayı, irsaliye, kayıt paneli. */
export function ShipmentPage() {
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
  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: 8 }}>
        <ShipmentView shipment={query.data} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <RecordPanel contentType="sales.shipment" objectId={query.data.id} />
      </Grid.Col>
    </Grid>
  );
}

function ShipmentView({ shipment }: { shipment: ShipmentDetail }) {
  const { user } = useAuth();
  const refresh = useShipmentRefresh();
  const writer = hasAnyRole(user, SHIPMENT_WRITE_ROLES);
  const picker = hasAnyRole(user, PICK_ROLES);
  const open = OPEN_SHIPMENT_STATUSES.includes(shipment.status);
  const [error, setError] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [loadOpen, setLoadOpen] = useState(false);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [undoing, setUndoing] = useState<ShipmentPick | null>(null);
  const short = shipment.lines.some((line) => lineRemaining(line) > 0);
  const hasPicks = shipment.picks.some((pick) => !pick.returned_at);

  const onError = (err: unknown) => setError(getErrorMessage(err));
  const load = useMutation({
    mutationFn: () => loadShipment(shipment.id),
    onSuccess: (saved) => {
      setError("");
      setLoadOpen(false);
      notifications.show({ color: "green", message: st.loaded });
      refresh(saved);
    },
    onError: (err) => {
      setLoadOpen(false);
      onError(err);
    },
  });
  const dispatch = useMutation({
    mutationFn: () => dispatchShipment(shipment.id),
    onSuccess: (saved) => {
      setError("");
      setDispatchOpen(false);
      notifications.show({ color: "green", message: st.dispatched });
      refresh(saved);
    },
    onError: (err) => {
      setDispatchOpen(false);
      onError(err);
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
      onError(err);
    },
  });

  return (
    <Stack>
      <Anchor component={Link} to={`${SALES_BASE}/sevkiyatlar`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {st.tabs.shipments}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{st.shipmentTitle(shipment.number)}</Title>
          <ShipmentStatusBadge status={shipment.status} />
        </Group>
        <Group gap="xs">
          {picker && PICKABLE_STATUSES.includes(shipment.status) && (
            <Button
              component={Link}
              to={pickPath(shipment.id)}
              leftSection={<IconBarcode size={16} />}
            >
              {st.openPicking}
            </Button>
          )}
          {picker && shipment.status === "PICKING" && (
            <Button
              color="green"
              variant="light"
              leftSection={<IconPackageExport size={16} />}
              disabled={!hasPicks}
              onClick={() => setLoadOpen(true)}
            >
              {st.load}
            </Button>
          )}
          {writer && shipment.status === "LOADED" && (
            <Button
              color="green"
              leftSection={<IconTruckDelivery size={16} />}
              onClick={() => setDispatchOpen(true)}
            >
              {st.dispatch}
            </Button>
          )}
          {["LOADED", "DISPATCHED"].includes(shipment.status) && (
            <Button
              component="a"
              href={waybillPdfUrl(shipment.id)}
              target="_blank"
              rel="noopener"
              variant="light"
              leftSection={<IconFileTypePdf size={16} />}
            >
              {st.waybill}
            </Button>
          )}
          {writer && open && (
            <Button
              variant="default"
              leftSection={<IconEdit size={16} />}
              onClick={() => setEditOpen(true)}
            >
              {st.editHeader}
            </Button>
          )}
          {writer && open && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {st.cancelShipment}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={st.order}>
            <Anchor component={Link} to={salesOrderPath(shipment.sales_order)} size="sm">
              {shipment.order_number}
            </Anchor>
          </Info>
          <Info label={st.customer}>
            <Anchor component={Link} to={customerPath(shipment.customer)} size="sm">
              {`${shipment.customer_code} - ${shipment.customer_name}`}
            </Anchor>
          </Info>
          <Info label={st.plannedDate}>
            <Text size="sm">{formatDate(shipment.planned_date)}</Text>
          </Info>
          <Info label={st.vehiclePlate}>
            <Text size="sm">{shipment.vehicle_plate}</Text>
          </Info>
          <Info label={st.driverName}>
            <Text size="sm">{shipment.driver_name}</Text>
          </Info>
          <Info label={st.driverId}>
            <Text size="sm" data-testid="driver-id">
              {shipment.driver_id_no_masked}
            </Text>
          </Info>
          <Info label={st.carrier}>
            <Text size="sm">{shipment.carrier}</Text>
          </Info>
          <Info label={st.loadingLocation}>
            <Text size="sm">{shipment.loading_location_code}</Text>
          </Info>
          <Info label={st.shelfLife}>
            <Text size="sm">
              {shipment.min_remaining_shelf_life_days != null
                ? st.shelfLifeDays(shipment.min_remaining_shelf_life_days)
                : st.noShelfLife}
            </Text>
          </Info>
          <Info label={st.deliveryAddress}>
            <Text size="sm">{shipment.delivery_address}</Text>
          </Info>
          {shipment.loaded_at && (
            <Info label={st.loadedBy}>
              <Text size="sm">{`${shipment.loaded_by_name ?? ""} · ${formatDateTime(shipment.loaded_at)}`}</Text>
            </Info>
          )}
          {shipment.dispatched_at && (
            <Info label={st.dispatchedBy}>
              <Text size="sm">{`${shipment.dispatched_by_name ?? ""} · ${formatDateTime(shipment.dispatched_at)}`}</Text>
            </Info>
          )}
          <Info label={st.notes}>
            <Text size="sm">{shipment.notes}</Text>
          </Info>
          {shipment.status === "CANCELLED" && (
            <Info label={st.cancelInfo}>
              <Text size="sm">{shipment.cancel_reason}</Text>
            </Info>
          )}
        </SimpleGrid>
      </Paper>

      <Title order={4}>{st.lines}</Title>
      <ShipmentLinesTable lines={shipment.lines} />

      <Title order={4}>{st.picks}</Title>
      <PicksTable
        picks={shipment.picks}
        onUndo={picker && UNDOABLE_STATUSES.includes(shipment.status) ? setUndoing : undefined}
      />

      <ConfirmModal
        opened={loadOpen}
        message={short ? st.loadPartialQuestion : st.loadQuestion}
        confirmLabel={st.load}
        loading={load.isPending}
        onConfirm={() => load.mutate()}
        onClose={() => setLoadOpen(false)}
      />
      <ConfirmModal
        opened={dispatchOpen}
        message={st.dispatchQuestion}
        confirmLabel={st.dispatch}
        loading={dispatch.isPending}
        onConfirm={() => dispatch.mutate()}
        onClose={() => setDispatchOpen(false)}
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
      <CancelModal
        opened={cancelOpen}
        cancel={(reason) => cancelShipment(shipment.id, reason)}
        onClose={() => setCancelOpen(false)}
        onDone={(saved) => {
          setCancelOpen(false);
          notifications.show({ color: "green", message: st.shipmentCancelled });
          refresh(saved);
        }}
      />
      {editOpen && (
        <EditShipmentModal
          shipment={shipment}
          onClose={() => setEditOpen(false)}
          onDone={(saved) => {
            setEditOpen(false);
            refresh(saved);
          }}
        />
      )}
    </Stack>
  );
}

export function ShipmentLinesTable({ lines }: { lines: ShipmentLine[] }) {
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table striped fz="sm" data-testid="shipment-lines">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>{st.product}</Table.Th>
            <Table.Th ta="right">{st.lineQuantity}</Table.Th>
            <Table.Th ta="right">{st.picked}</Table.Th>
            <Table.Th ta="right">{st.remaining}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {lines.map((line) => {
            const remaining = lineRemaining(line);
            return (
              <Table.Tr key={line.id}>
                <Table.Td>{line.line_no}</Table.Td>
                <Table.Td>{`${line.product_code} - ${line.product_name}`}</Table.Td>
                <Table.Td ta="right">
                  <Qty value={line.quantity} unit={line.unit} />
                </Table.Td>
                <Table.Td ta="right">
                  <Qty value={line.picked_quantity} unit={line.unit} />
                </Table.Td>
                <Table.Td ta="right">
                  <Text span size="sm" c={remaining > 0 ? "orange" : "green"} fw={600}>
                    {formatNumber(String(remaining))}
                  </Text>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function PicksTable({
  picks,
  onUndo,
}: {
  picks: ShipmentPick[];
  onUndo?: (pick: ShipmentPick) => void;
}) {
  if (picks.length === 0)
    return (
      <Text size="sm" c="dimmed">
        {st.noPicks}
      </Text>
    );
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table striped fz="sm" data-testid="shipment-picks">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>#</Table.Th>
            <Table.Th>{st.lot}</Table.Th>
            <Table.Th>{st.expiry}</Table.Th>
            <Table.Th ta="right">{st.quantity}</Table.Th>
            <Table.Th>{`${st.from} → ${st.to}`}</Table.Th>
            <Table.Th>{st.pickedBy}</Table.Th>
            <Table.Th>{st.reason}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {picks.map((pick) => (
            <Table.Tr key={pick.id} c={pick.returned_at ? "dimmed" : undefined}>
              <Table.Td>{pick.line_no}</Table.Td>
              <Table.Td>
                <Anchor component={Link} to={`/depo/lotlar/${pick.lot}`} size="sm">
                  {pick.lot_no}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <ExpiryText date={pick.expiry_date} />
              </Table.Td>
              <Table.Td ta="right">{formatNumber(pick.quantity)}</Table.Td>
              <Table.Td>{`${pick.from_location_code} → ${pick.to_location_code}`}</Table.Td>
              <Table.Td>{`${pick.picked_by_name ?? ""} · ${formatDateTime(pick.picked_at)}`}</Table.Td>
              <Table.Td>{pick.deviation_reason}</Table.Td>
              <Table.Td>
                {pick.returned_at ? (
                  <Badge color="gray" variant="light">
                    {st.returned}
                  </Badge>
                ) : pick.is_shipped ? (
                  <Badge color="teal" variant="light">
                    {st.shippedBadge}
                  </Badge>
                ) : (
                  onUndo && (
                    <Button
                      size="compact-xs"
                      color="red"
                      variant="subtle"
                      onClick={() => onUndo(pick)}
                    >
                      {st.undo}
                    </Button>
                  )
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}
