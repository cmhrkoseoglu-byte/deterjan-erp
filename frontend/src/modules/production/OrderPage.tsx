import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Grid,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowLeft,
  IconCheck,
  IconFlask2,
  IconPackage,
  IconPlayerPlay,
  IconPlus,
  IconRecycle,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { getLot } from "../../api/inventory";
import { listRecords, type Equipment } from "../../api/masterdata";
import {
  cancelOrder,
  getOrder,
  orderAction,
  saveOrder,
  getTankCheck,
  startBatch,
  type OrderPayload,
  type Priority,
  type ProductionOrderDetail,
  type ReworkAddition,
} from "../../api/production";
import { listRecipes } from "../../api/recipes";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDate, formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { ct } from "../common/strings";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { useOptions } from "../common/useOptions";
import { lotPath, today } from "../inventory/config";
import { idOrNull, useLocations } from "../inventory/options";
import { Info, Qty } from "../inventory/shared";
import {
  BATCH_ROLES,
  BATCHABLE_STATUSES,
  batchPath,
  ORDER_ROLES,
  orderPath,
  PREP_ROLES,
  prepPath,
  PRODUCTION_BASE,
  REWORK_PARAM,
} from "./config";
import { BatchStatusBadge, OrderStatusBadge, ReasonModal } from "./shared";
import { pt } from "./strings";
import { CleaningModal } from "../maintenance/CleaningModal";

const PRIORITY_OPTIONS = ([1, 2, 3, 4] as Priority[]).map((value) => ({
  value: String(value),
  label: pt.priority[value],
}));
const PICKABLE = ["APPROVED", "MATERIAL_PREP", "MATERIAL_READY", "IN_PRODUCTION"];

/** Üretim emri: yeni/taslak formu ya da detay (ihtiyaçlar, hazırlanan lotlar, şarjlar). */
export function OrderPage() {
  const param = useParams().orderId;
  const isNew = param === "yeni";
  const orderId = isNew ? null : Number(param);
  const query = useQuery({
    queryKey: ["production", "order", orderId],
    queryFn: () => getOrder(orderId!),
    enabled: orderId !== null,
  });

  if (!isNew && query.isLoading) return <Loader />;
  if (!isNew && (query.isError || !query.data))
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const order = query.data ?? null;

  return (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, lg: order ? 8 : 12 }}>
        {order ? <OrderDetail order={order} /> : <OrderForm order={null} />}
      </Grid.Col>
      {order && (
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <RecordPanel contentType="production.productionorder" objectId={order.id} />
        </Grid.Col>
      )}
    </Grid>
  );
}

function BackLink() {
  return (
    <Anchor component={Link} to={`${PRODUCTION_BASE}/emirler`} size="sm">
      <Group gap={4}>
        <IconArrowLeft size={14} />
        {pt.tabs.orders}
      </Group>
    </Anchor>
  );
}

interface AdditionDraft {
  material: string | null;
  quantity: string;
  unit: string | null;
  tolerance_pct: string;
  is_water: boolean;
  instruction: string;
}

interface Draft {
  rework_lot: string | null;
  additions: AdditionDraft[];
  recipe: string | null;
  planned_quantity: string;
  unit: string | null;
  planned_date: string;
  equipment: string | null;
  production_location: string | null;
  priority: string;
  notes: string;
}

function toAdditionDraft(row: ReworkAddition): AdditionDraft {
  return {
    material: String(row.material),
    quantity: trimDecimal(row.quantity),
    unit: String(row.unit),
    tolerance_pct: trimDecimal(row.tolerance_pct),
    is_water: row.is_water,
    instruction: row.instruction,
  };
}

const EMPTY_ADDITION: AdditionDraft = {
  material: null,
  quantity: "",
  unit: null,
  tolerance_pct: "2",
  is_water: false,
  instruction: "",
};

function toDraft(order: ProductionOrderDetail | null, reworkLot: string | null = null): Draft {
  return {
    rework_lot: order?.rework_lot ? String(order.rework_lot) : reworkLot,
    additions: (order?.additions ?? []).map(toAdditionDraft),
    recipe: order?.recipe_id ? String(order.recipe_id) : null,
    planned_quantity: order ? trimDecimal(order.planned_quantity) : "",
    unit: order ? String(order.unit) : null,
    planned_date: order?.planned_date ?? today(),
    equipment: order ? String(order.equipment) : null,
    production_location: order ? String(order.production_location) : null,
    priority: String(order?.priority ?? 2),
    notes: order?.notes ?? "",
  };
}

function useRecipes() {
  return useQuery({
    queryKey: ["options", "approved-recipes"],
    staleTime: 60_000,
    queryFn: async () => (await listRecipes({ is_active: true, page_size: 500 })).results,
  });
}

function useMixingTanks() {
  return useQuery({
    queryKey: ["options", "mixing-tanks"],
    staleTime: 60_000,
    queryFn: async () =>
      (
        await listRecords<Equipment>("equipment", {
          is_active: true,
          equipment_type: "MIXING_TANK",
          page_size: 500,
        })
      ).results,
  });
}

function OrderForm({
  order,
  onSaved,
}: {
  order: ProductionOrderDetail | null;
  onSaved?: (saved: ProductionOrderDetail) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [draft, setDraft] = useState(() => toDraft(order, searchParams.get(REWORK_PARAM)));
  const [error, setError] = useState("");
  const reworkLotId = idOrNull(draft.rework_lot);
  const reworkLot = useQuery({
    queryKey: ["inventory", "lot", reworkLotId],
    queryFn: () => getLot(reworkLotId!),
    enabled: reworkLotId !== null,
  });
  const recipes = useRecipes();
  const tanks = useMixingTanks();
  const units = useOptions({ endpoint: "units" });
  const locations = useLocations();
  const set = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const recipe = (recipes.data ?? []).find((row) => String(row.id) === draft.recipe);
  const isRework = reworkLotId !== null;
  const recipeOptions = (recipes.data ?? [])
    .filter((row) => row.approved_version)
    .filter((row) => !reworkLot.data || row.product === reworkLot.data.material)
    .map((row) => ({
      value: String(row.id),
      label: `${row.code} - ${row.name} (v${row.approved_version!.version_no})`,
    }));
  const tankOptions = (tanks.data ?? []).map((row) => ({
    value: String(row.id),
    label: `${row.code} - ${row.name}${
      row.capacity ? ` (${formatNumber(row.capacity)} ${row.capacity_unit_code ?? ""})` : ""
    }`,
  }));
  const productionLocations = (locations.data ?? []).filter((row) => row.type === "PRODUCTION");

  const save = useMutation({
    mutationFn: () => {
      const payload: OrderPayload = {
        recipe_version: recipe?.approved_version?.id ?? null,
        ...(isRework
          ? {
              rework_lot: reworkLotId,
              additions: draft.additions.map((row) => ({
                material: Number(row.material),
                quantity: normalizeDecimal(row.quantity),
                unit: Number(row.unit),
                tolerance_pct: normalizeDecimal(row.tolerance_pct || "0"),
                is_water: row.is_water,
                instruction: row.instruction.trim(),
              })),
            }
          : {}),
        planned_quantity: normalizeDecimal(draft.planned_quantity),
        unit: idOrNull(draft.unit),
        planned_date: draft.planned_date,
        equipment: idOrNull(draft.equipment),
        production_location: idOrNull(draft.production_location),
        priority: Number(draft.priority) as Priority,
        notes: draft.notes.trim(),
      };
      return saveOrder(order?.id ?? null, payload);
    },
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: pt.saved });
      queryClient.setQueryData(["production", "order", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["production"] });
      if (!order) navigate(orderPath(saved.id), { replace: true });
      onSaved?.(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Stack>
      {!order && (
        <>
          <BackLink />
          <Title order={2}>{isRework ? pt.newReworkOrder : pt.newOrder}</Title>
        </>
      )}
      {isRework && reworkLot.data && (
        <Alert color="orange" variant="light" icon={<IconRecycle size={18} />}>
          {pt.reworkIntro(
            reworkLot.data.lot_no,
            `${reworkLot.data.material_code} - ${reworkLot.data.material_name}`,
            `${formatNumber(reworkLot.data.total_quantity)} ${reworkLot.data.unit}`,
          )}
        </Alert>
      )}
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
          <Select
            label={pt.recipe}
            withAsterisk={!isRework}
            description={isRework ? pt.reworkRecipeHint : undefined}
            clearable={isRework}
            searchable
            data={recipeOptions}
            value={draft.recipe}
            onChange={(value) => set({ recipe: value })}
            error={recipe && !recipe.approved_version ? pt.noApprovedVersion : undefined}
          />
          <Group gap="xs" grow wrap="nowrap">
            <TextInput
              label={pt.plannedQuantity}
              description={isRework ? pt.reworkQuantityHint : undefined}
              withAsterisk
              inputMode="decimal"
              value={draft.planned_quantity}
              onChange={(event) => set({ planned_quantity: event.currentTarget.value })}
            />
            <Select
              label={pt.unit}
              withAsterisk
              searchable
              data={units.data ?? []}
              value={draft.unit}
              onChange={(value) => set({ unit: value })}
            />
          </Group>
          <TextInput
            label={pt.plannedDate}
            type="date"
            withAsterisk
            value={draft.planned_date}
            onChange={(event) => set({ planned_date: event.currentTarget.value })}
          />
          <Select
            label={pt.tank}
            withAsterisk
            data={tankOptions}
            value={draft.equipment}
            onChange={(value) => set({ equipment: value, production_location: null })}
          />
          <Select
            label={pt.productionLocation}
            description={pt.productionLocationHint}
            clearable
            data={productionLocations}
            value={draft.production_location}
            onChange={(value) => set({ production_location: value })}
          />
          <Select
            label={pt.priorityLabel}
            data={PRIORITY_OPTIONS}
            value={draft.priority}
            allowDeselect={false}
            onChange={(value) => set({ priority: value ?? "2" })}
          />
        </SimpleGrid>
        <Textarea
          mt="sm"
          label={pt.notes}
          autosize
          minRows={1}
          value={draft.notes}
          onChange={(event) => set({ notes: event.currentTarget.value })}
        />
      </Paper>
      {isRework && (
        <AdditionsEditor
          rows={draft.additions}
          units={units.data ?? []}
          onChange={(additions) => set({ additions })}
        />
      )}
      <Group justify="flex-end">
        <Button loading={save.isPending} onClick={() => save.mutate()}>
          {pt.saveDraft}
        </Button>
      </Group>
    </Stack>
  );
}

/** Yeniden işleme emrinin düzeltme listesi: lota eklenecek malzemeler (ör. tuz, su, parfüm). */
function AdditionsEditor({
  rows,
  units,
  onChange,
}: {
  rows: AdditionDraft[];
  units: { value: string; label: string }[];
  onChange: (rows: AdditionDraft[]) => void;
}) {
  const materials = useOptions({ endpoint: "materials" });
  const update = (index: number, patch: Partial<AdditionDraft>) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="xs">
        <Title order={5}>{pt.additions}</Title>
        <Button
          size="xs"
          variant="light"
          leftSection={<IconPlus size={14} />}
          onClick={() => onChange([...rows, { ...EMPTY_ADDITION }])}
        >
          {pt.addAddition}
        </Button>
      </Group>
      <Text size="sm" c="dimmed" mb="xs">
        {pt.additionsHint}
      </Text>
      <Stack gap="xs" data-testid="additions">
        {rows.map((row, index) => (
          <Group key={index} gap="xs" align="flex-end" wrap="wrap">
            <Select
              label={pt.material}
              searchable
              w={240}
              data={materials.data ?? []}
              value={row.material}
              onChange={(value) => update(index, { material: value })}
            />
            <TextInput
              label={pt.quantity}
              inputMode="decimal"
              w={100}
              value={row.quantity}
              onChange={(event) => update(index, { quantity: event.currentTarget.value })}
            />
            <Select
              label={pt.unit}
              w={100}
              data={units}
              value={row.unit}
              onChange={(value) => update(index, { unit: value })}
            />
            <TextInput
              label={pt.tolerance}
              inputMode="decimal"
              w={80}
              value={row.tolerance_pct}
              onChange={(event) => update(index, { tolerance_pct: event.currentTarget.value })}
            />
            <TextInput
              label={pt.instruction}
              w={220}
              value={row.instruction}
              onChange={(event) => update(index, { instruction: event.currentTarget.value })}
            />
            <Checkbox
              mb={8}
              label={pt.waterShort}
              checked={row.is_water}
              onChange={(event) => update(index, { is_water: event.currentTarget.checked })}
            />
            <ActionIcon
              mb={4}
              variant="subtle"
              color="red"
              aria-label={pt.removeAddition}
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        ))}
      </Stack>
    </Paper>
  );
}

function OrderDetail({ order }: { order: ProductionOrderDetail }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [startOpen, setStartOpen] = useState(false);
  const canPlan = hasAnyRole(user, ORDER_ROLES);
  const canPrep = hasAnyRole(user, PREP_ROLES);
  const canBatch = hasAnyRole(user, BATCH_ROLES);
  const isDraft = order.status === "DRAFT";
  const remaining = Number(order.remaining_quantity);

  const refresh = (saved: ProductionOrderDetail) => {
    queryClient.setQueryData(["production", "order", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["production"] });
  };
  const approve = useMutation({
    mutationFn: () => orderAction(order.id, "approve"),
    onSuccess: (saved) => {
      setConfirmApprove(false);
      setError("");
      notifications.show({ color: "green", message: pt.approved });
      refresh(saved);
    },
    onError: (err) => {
      setConfirmApprove(false);
      setError(getErrorMessage(err));
    },
  });

  return (
    <Stack>
      <BackLink />
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{pt.orderTitle(order.number)}</Title>
          <OrderStatusBadge status={order.status} />
          {order.rework_lot && (
            <Badge color="orange" variant="light" leftSection={<IconRecycle size={12} />}>
              {pt.rework}
            </Badge>
          )}
        </Group>
        <Group gap="xs">
          {canPlan && isDraft && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setConfirmApprove(true)}
            >
              {pt.approve}
            </Button>
          )}
          {canPrep && PICKABLE.includes(order.status) && (
            <Button
              leftSection={<IconPackage size={16} />}
              onClick={() => navigate(prepPath(order.id))}
            >
              {pt.openPrep}
            </Button>
          )}
          {canBatch && BATCHABLE_STATUSES.includes(order.status) && remaining > 0 && (
            <Button
              color="violet"
              leftSection={<IconPlayerPlay size={16} />}
              onClick={() => setStartOpen(true)}
            >
              {pt.startBatch}
            </Button>
          )}
          {canPlan && order.allowed_transitions.includes("CANCELLED") && (
            <Button
              color="red"
              variant="light"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelOpen(true)}
            >
              {pt.cancelOrder}
            </Button>
          )}
        </Group>
      </Group>

      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      {canPlan && isDraft ? (
        <OrderForm key={order.id} order={order} onSaved={refresh} />
      ) : (
        <Paper withBorder p="md" radius="md">
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
            <Info label={pt.product}>
              <Text size="sm">{`${order.product_code} - ${order.product_name}`}</Text>
            </Info>
            <Info label={pt.recipe}>
              <Text size="sm">
                {order.recipe_code
                  ? pt.recipeVersion(order.recipe_code, order.version_no ?? 0)
                  : pt.noRecipe}
              </Text>
            </Info>
            {order.rework_lot && (
              <Info label={pt.reworkLot}>
                <Anchor component={Link} to={lotPath(order.rework_lot)} size="sm">
                  {order.rework_lot_no}
                </Anchor>
              </Info>
            )}
            <Info label={pt.plannedQuantity}>
              <Qty value={order.planned_quantity} unit={order.unit_code} />
            </Info>
            <Info label={pt.plannedDate}>
              <Text size="sm">{formatDate(order.planned_date)}</Text>
            </Info>
            <Info label={pt.tank}>
              <Text size="sm">{`${order.equipment_code} - ${order.equipment_name}`}</Text>
            </Info>
            <Info label={pt.productionLocation}>
              <Text size="sm">{order.production_location_code}</Text>
            </Info>
            <Info label={pt.priorityLabel}>
              <Text size="sm">{pt.priority[order.priority]}</Text>
            </Info>
            {order.approved_at && (
              <Info label={pt.approvedBy}>
                <Text size="sm">{`${order.approved_by_name ?? ""} · ${formatDateTime(order.approved_at)}`}</Text>
              </Info>
            )}
            {BATCHABLE_STATUSES.includes(order.status) && (
              <Info label={pt.remaining}>
                <Qty value={order.remaining_quantity} unit={order.base_unit} />
              </Info>
            )}
            {order.completed_at && (
              <Info label={pt.completedAt}>
                <Text size="sm">{formatDateTime(order.completed_at)}</Text>
              </Info>
            )}
            {order.status === "CANCELLED" && (
              <Info label={pt.cancelReason}>
                <Text size="sm">{order.cancel_reason}</Text>
              </Info>
            )}
            {order.notes && (
              <Info label={pt.notes}>
                <Text size="sm">{order.notes}</Text>
              </Info>
            )}
          </SimpleGrid>
        </Paper>
      )}

      {order.requirements.length > 0 && (
        <>
          <Title order={4}>{pt.requirements}</Title>
          <Table.ScrollContainer minWidth={680}>
            <Table striped fz="sm" data-testid="requirements">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{pt.material}</Table.Th>
                  <Table.Th ta="right">{pt.required}</Table.Th>
                  <Table.Th ta="right">{pt.tolerance}</Table.Th>
                  <Table.Th ta="right">{pt.picked}</Table.Th>
                  <Table.Th ta="right">{pt.consumed}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {order.requirements.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.sequence}</Table.Td>
                    <Table.Td>
                      <Group gap="xs">
                        <Text size="sm">{`${row.material_code} - ${row.material_name}`}</Text>
                        {row.is_water && (
                          <Badge size="xs" variant="light" color="cyan">
                            {pt.water}
                          </Badge>
                        )}
                        {row.lot && (
                          <Badge size="xs" variant="light" color="orange">
                            {`${pt.reworkLot}: ${row.lot_no}`}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.required_quantity} unit={row.unit} />
                    </Table.Td>
                    <Table.Td ta="right">%{formatNumber(row.tolerance_pct)}</Table.Td>
                    <Table.Td ta="right">
                      {!row.is_picked ? (
                        "—"
                      ) : (
                        <Text span size="sm" c={row.is_ready ? "green" : undefined}>
                          {formatNumber(row.picked_quantity)} {row.unit}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.consumed_quantity} unit={row.unit} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}

      {order.picks.length > 0 && (
        <>
          <Title order={4}>{pt.picks}</Title>
          <Table.ScrollContainer minWidth={680}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{pt.material}</Table.Th>
                  <Table.Th>{pt.lot}</Table.Th>
                  <Table.Th ta="right">{pt.quantity}</Table.Th>
                  <Table.Th>{pt.from}</Table.Th>
                  <Table.Th>{pt.by}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {order.picks.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>{row.material_code}</Table.Td>
                    <Table.Td>
                      <Anchor component={Link} to={lotPath(row.lot)} size="sm">
                        {row.lot_no}
                      </Anchor>
                      {row.returned_at && (
                        <Badge ml="xs" size="xs" color="gray">
                          {pt.returned}
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td ta="right">
                      <Qty value={row.quantity} unit={row.unit} />
                    </Table.Td>
                    <Table.Td>{`${row.from_location_code} → ${row.to_location_code}`}</Table.Td>
                    <Table.Td>{`${row.picked_by_name ?? ""} · ${formatDateTime(row.picked_at)}`}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}

      {order.status !== "DRAFT" && order.status !== "CANCELLED" && (
        <>
          <Title order={4}>{pt.batches}</Title>
          {order.batches.length === 0 ? (
            <Text size="sm" c="dimmed">
              {pt.noBatches}
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={680}>
              <Table striped highlightOnHover fz="sm" data-testid="batches">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{pt.batchNo}</Table.Th>
                    <Table.Th>{pt.tank}</Table.Th>
                    <Table.Th ta="right">{pt.batchQuantity}</Table.Th>
                    <Table.Th ta="right">{pt.output}</Table.Th>
                    <Table.Th ta="right">{pt.yieldPct}</Table.Th>
                    <Table.Th>{pt.outputLot}</Table.Th>
                    <Table.Th>{pt.status}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {order.batches.map((row) => (
                    <Table.Tr
                      key={row.id}
                      style={{ cursor: "pointer" }}
                      onClick={() => navigate(batchPath(row.id))}
                    >
                      <Table.Td>{row.batch_no}</Table.Td>
                      <Table.Td>{row.equipment_code}</Table.Td>
                      <Table.Td ta="right">
                        <Qty value={row.planned_quantity} unit={row.unit} />
                      </Table.Td>
                      <Table.Td ta="right">
                        <Qty value={row.actual_output_quantity} unit={row.unit} />
                      </Table.Td>
                      <Table.Td ta="right">
                        {row.yield_pct ? `%${formatNumber(row.yield_pct)}` : ""}
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          <IconFlask2 size={14} />
                          <Anchor
                            component={Link}
                            to={lotPath(row.output_lot)}
                            size="sm"
                            onClick={(event) => event.stopPropagation()}
                          >
                            {row.output_lot_no}
                          </Anchor>
                          <Text size="xs" c="dimmed">
                            {row.output_lot_status_display}
                          </Text>
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        <BatchStatusBadge status={row.status} />
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </>
      )}

      <ConfirmModal
        opened={confirmApprove}
        message={pt.approveConfirm}
        confirmLabel={pt.approve}
        loading={approve.isPending}
        onConfirm={() => approve.mutate()}
        onClose={() => setConfirmApprove(false)}
      />
      <ReasonModal
        opened={cancelOpen}
        title={pt.cancelTitle}
        hint={order.picks.length ? pt.cancelHint : undefined}
        label={pt.cancelReason}
        confirmLabel={pt.cancelOrder}
        submit={(reason) => cancelOrder(order.id, reason)}
        onClose={() => setCancelOpen(false)}
        onDone={(saved) => {
          setCancelOpen(false);
          notifications.show({ color: "green", message: pt.cancelled });
          refresh(saved);
        }}
      />
      <StartBatchModal order={order} opened={startOpen} onClose={() => setStartOpen(false)} />
    </Stack>
  );
}

function StartBatchModal({
  order,
  opened,
  onClose,
}: {
  order: ProductionOrderDetail;
  opened: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tanks = useMixingTanks();
  const [equipment, setEquipment] = useState<string | null>(String(order.equipment));
  const [quantity, setQuantity] = useState(trimDecimal(order.suggested_batch_quantity));
  const [error, setError] = useState("");
  const [cleaning, setCleaning] = useState(false);
  const tankId = idOrNull(equipment);
  // Faz 4: ürün değişimi temizliği (Karar D-14) ve tank duruşu; backend de denetler.
  const check = useQuery({
    queryKey: ["production", "tank-check", tankId, order.product],
    queryFn: () => getTankCheck(tankId!, order.product),
    enabled: opened && tankId !== null,
  });
  const tankCode = (tanks.data ?? []).find((row) => row.id === tankId)?.code ?? "";
  const mutation = useMutation({
    mutationFn: () =>
      startBatch({
        order: order.id,
        equipment: idOrNull(equipment),
        planned_quantity: quantity.trim() ? normalizeDecimal(quantity) : null,
      }),
    onSuccess: (batch) => {
      notifications.show({ color: "green", message: pt.started(batch.batch_no) });
      void queryClient.invalidateQueries({ queryKey: ["production"] });
      navigate(batchPath(batch.id));
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened={opened} onClose={onClose} title={pt.startTitle}>
      <Stack>
        <Select
          label={pt.tank}
          data={(tanks.data ?? []).map((row) => ({
            value: String(row.id),
            label: `${row.code} - ${row.name}`,
          }))}
          value={equipment}
          allowDeselect={false}
          onChange={setEquipment}
        />
        <TextInput
          label={`${pt.batchQuantity} (${order.base_unit})`}
          description={pt.batchQuantityHint(
            formatNumber(order.remaining_quantity),
            order.base_unit,
          )}
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.currentTarget.value)}
        />
        {check.data?.is_down && (
          <Alert color="red" variant="light" data-testid="tank-down">
            {pt.tankDown(tankCode, check.data.downtime_reason ?? "")}
          </Alert>
        )}
        {check.data?.required && (
          <Alert color="orange" variant="light" data-testid="cleaning-required">
            <Stack gap="xs">
              <Text size="sm">
                {pt.cleaningRequired(tankCode, check.data.previous_product_code ?? "")}
              </Text>
              <Group>
                <Button size="xs" color="orange" onClick={() => setCleaning(true)}>
                  {pt.cleaningRecord}
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button
            color="violet"
            loading={mutation.isPending}
            disabled={Boolean(check.data?.required || check.data?.is_down)}
            onClick={() => mutation.mutate()}
          >
            {pt.startBatch}
          </Button>
        </Group>
        {cleaning && tankId !== null && (
          <CleaningModal
            equipmentId={tankId}
            onClose={() => setCleaning(false)}
            onSaved={() => {
              setCleaning(false);
              void check.refetch();
            }}
          />
        )}
      </Stack>
    </Modal>
  );
}
