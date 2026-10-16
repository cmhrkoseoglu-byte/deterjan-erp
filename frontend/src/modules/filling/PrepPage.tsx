import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
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
import { IconArrowLeft, IconBarcode, IconCheck } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  fillingOrderAction,
  getFillingOrder,
  packagingSuggestions,
  pickPackaging,
  type FillingOrderDetail,
  type FillingRequirementRow,
} from "../../api/filling";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatNumber } from "../../i18n/format";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ExpiryText, Qty } from "../inventory/shared";
import { fillingOrderPath, PREP_ROLES, PREP_STATUSES } from "./config";
import { FillingOrderStatusBadge } from "./shared";
import { ft } from "./strings";

const PICKABLE = [...PREP_STATUSES, "MATERIAL_READY", "IN_PROGRESS"];

/** Depo tablet ekranı: ambalaj satırları, lot okutma, FEFO önerisi, "Ambalaj hazır". */
export function FillingPrepPage() {
  const orderId = Number(useParams().orderId);
  const query = useQuery({
    queryKey: ["filling", "order", orderId],
    queryFn: () => getFillingOrder(orderId),
  });
  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  return <Prep order={query.data} />;
}

function Prep({ order }: { order: FillingOrderDetail }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const lines = order.requirements;
  const firstOpen = lines.find((row) => !row.is_ready) ?? lines[0];
  const [selected, setSelected] = useState<number | null>(firstOpen?.id ?? null);
  const [error, setError] = useState("");
  const canPick = hasAnyRole(user, PREP_ROLES) && PICKABLE.includes(order.status);
  const allReady = lines.every((row) => row.is_ready);
  const doneCount = lines.filter((row) => row.is_ready).length;
  const current = lines.find((row) => row.id === selected) ?? null;

  const ready = useMutation({
    mutationFn: () => fillingOrderAction(order.id, "mark-ready"),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: ft.readyOk });
      queryClient.setQueryData(["filling", "order", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["filling"] });
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Stack>
      <Anchor component={Link} to={fillingOrderPath(order.id)} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {ft.orderTitle(order.number)}
        </Group>
      </Anchor>
      <Group justify="space-between">
        <Group>
          <Title order={2}>{ft.prepTitle(order.number)}</Title>
          <FillingOrderStatusBadge status={order.status} />
        </Group>
        <Text size="sm" c="dimmed">
          {`${order.finished_product_code} · ${formatNumber(order.planned_units)} ${order.unit} · ${order.line_location_code ?? ""}`}
        </Text>
      </Group>
      <Progress value={lines.length ? (doneCount / lines.length) * 100 : 0} size="lg" />
      {PREP_STATUSES.includes(order.status) && (
        <Text size="sm" c="dimmed">
          {ft.prepIntro}
        </Text>
      )}
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm" data-testid="prep-lines">
        {lines.map((row) => (
          <LineCard
            key={row.id}
            row={row}
            active={row.id === selected}
            onSelect={() => setSelected(row.id)}
          />
        ))}
      </SimpleGrid>

      {canPick && current && (
        <PickForm
          key={current.id}
          order={order}
          row={current}
          onPicked={(next) => {
            const nextOpen = next.requirements.find((r) => !r.is_ready);
            if (nextOpen) setSelected(nextOpen.id);
          }}
        />
      )}

      {hasAnyRole(user, PREP_ROLES) && PREP_STATUSES.includes(order.status) && (
        <Paper withBorder p="md" radius="md">
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {ft.readyHint}
            </Text>
            <Button
              size="lg"
              color="green"
              leftSection={<IconCheck size={20} />}
              disabled={!allReady}
              loading={ready.isPending}
              onClick={() => ready.mutate()}
            >
              {ft.markReady}
            </Button>
          </Group>
        </Paper>
      )}
    </Stack>
  );
}

function LineCard({
  row,
  active,
  onSelect,
}: {
  row: FillingRequirementRow;
  active: boolean;
  onSelect: () => void;
}) {
  const picked = Number(row.picked_quantity);
  const required = Number(row.required_quantity);
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
          <Text fw={600}>{`${row.sequence}. ${row.material_code}`}</Text>
          {row.is_ready ? (
            <Badge color="green">{ft.done}</Badge>
          ) : (
            <Badge color="orange" variant="light">
              {`${ft.toPick}: ${formatNumber(row.to_pick)} ${row.unit}`}
            </Badge>
          )}
        </Group>
        <Text size="sm" c="dimmed" lineClamp={1}>
          {row.material_name}
        </Text>
        <Progress
          mt="xs"
          color={row.is_ready ? "green" : "orange"}
          value={required ? Math.min(100, (picked / required) * 100) : 0}
        />
        <Text size="sm" mt={4}>
          {`${formatNumber(row.picked_quantity)} / ${formatNumber(row.required_quantity)} ${row.unit}`}
        </Text>
      </Card>
    </UnstyledButton>
  );
}

function PickForm({
  order,
  row,
  onPicked,
}: {
  order: FillingOrderDetail;
  row: FillingRequirementRow;
  onPicked: (order: FillingOrderDetail) => void;
}) {
  const queryClient = useQueryClient();
  const scanRef = useRef<HTMLInputElement>(null);
  const [lotNo, setLotNo] = useState("");
  const [lotId, setLotId] = useState<number | null>(null);
  const [fromLocation, setFromLocation] = useState<number | null>(null);
  const [quantity, setQuantity] = useState(Number(row.to_pick) > 0 ? trimDecimal(row.to_pick) : "");
  const [error, setError] = useState("");
  const suggestions = useQuery({
    queryKey: ["filling", "pick-suggestions", order.id, row.id],
    queryFn: () => packagingSuggestions(order.id, row.id),
  });

  const pick = useMutation({
    mutationFn: () =>
      pickPackaging(order.id, {
        requirement: row.id,
        ...(lotId ? { lot: lotId } : { lot_no: lotNo.trim() }),
        ...(fromLocation ? { from_location: fromLocation } : {}),
        quantity: normalizeDecimal(quantity),
      }),
    onSuccess: async (saved) => {
      setError("");
      setLotNo("");
      setLotId(null);
      setFromLocation(null);
      notifications.show({ color: "green", message: ft.pickedOk(saved.lot_no) });
      const next = await queryClient.fetchQuery({
        queryKey: ["filling", "order", order.id],
        queryFn: () => getFillingOrder(order.id),
      });
      void queryClient.invalidateQueries({ queryKey: ["filling"] });
      onPicked(next);
    },
    onError: (err) => {
      setError(getErrorMessage(err));
      scanRef.current?.select();
    },
  });
  const canSubmit = (lotId !== null || lotNo.trim() !== "") && quantity.trim() !== "";

  return (
    <Paper withBorder p="md" radius="md">
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{`${row.material_code} - ${row.material_name}`}</Title>
          <Text size="sm">
            {`${ft.required}: `}
            <Qty value={row.required_quantity} unit={row.unit} />
          </Text>
        </Group>
        <Group align="flex-end" grow>
          <TextInput
            ref={scanRef}
            size="lg"
            label={ft.scan}
            placeholder={ft.scanPlaceholder}
            leftSection={<IconBarcode size={20} />}
            autoFocus
            value={lotNo}
            onChange={(event) => {
              setLotNo(event.currentTarget.value);
              setLotId(null);
              setFromLocation(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && canSubmit) pick.mutate();
            }}
          />
          <TextInput
            size="lg"
            label={`${ft.quantity} (${row.unit})`}
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && canSubmit) pick.mutate();
            }}
          />
        </Group>
        {error && (
          <Alert color="red" variant="light" data-testid="pick-error">
            {error}
          </Alert>
        )}
        <Text fw={600} size="sm">
          {ft.fefo}
        </Text>
        {suggestions.isLoading ? (
          <Loader size="sm" />
        ) : (suggestions.data ?? []).length === 0 ? (
          <Text size="sm" c="dimmed">
            {ft.noSuggestion}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={360}>
            <Table fz="md" verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{ft.lotNo}</Table.Th>
                  <Table.Th>{ft.from}</Table.Th>
                  <Table.Th>{ft.expiry}</Table.Th>
                  <Table.Th ta="right">{ft.quantity}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {(suggestions.data ?? []).map((balance) => {
                  const chosen = lotId === balance.lot && fromLocation === balance.location;
                  return (
                    <Table.Tr
                      key={balance.id}
                      style={{ cursor: "pointer" }}
                      bg={chosen ? "var(--mantine-color-blue-light)" : undefined}
                      onClick={() => {
                        setLotId(balance.lot);
                        setFromLocation(balance.location);
                        setLotNo(balance.lot_no);
                      }}
                    >
                      <Table.Td>{balance.lot_no}</Table.Td>
                      <Table.Td>{balance.location_code}</Table.Td>
                      <Table.Td>
                        <ExpiryText date={balance.expiry_date} />
                      </Table.Td>
                      <Table.Td ta="right">
                        <Qty value={balance.quantity} unit={balance.unit} />
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
            loading={pick.isPending}
            onClick={() => pick.mutate()}
          >
            {ft.pick}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
