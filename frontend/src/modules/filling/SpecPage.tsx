import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconCheck, IconCopy, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  addSpecLine,
  getSpec,
  removeSpecLine,
  saveSpec,
  specAction,
  updateSpecLine,
  type PackagingSpecDetail,
  type PackagingSpecLine,
} from "../../api/filling";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { useOptions } from "../common/useOptions";
import { idOrNull } from "../inventory/options";
import { Info } from "../inventory/shared";
import { FILLING_BASE, PLAN_ROLES, specPath } from "./config";
import { SpecStatusBadge } from "./shared";
import { ft } from "./strings";

/** Ambalaj reçetesi: yeni / taslak düzenleme, onay ve yeni sürüm açma. */
export function SpecPage() {
  const param = useParams().specId;
  const specId = param === "yeni" ? null : Number(param);
  const query = useQuery({
    queryKey: ["filling", "spec", specId],
    queryFn: () => getSpec(specId!),
    enabled: specId !== null,
  });
  if (specId !== null && query.isLoading) return <Loader />;
  if (specId !== null && (query.isError || !query.data))
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const spec = query.data ?? null;
  return (
    <Stack>
      <Anchor component={Link} to={`${FILLING_BASE}/ambalaj-receteleri`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {ft.tabs.specs}
        </Group>
      </Anchor>
      <SpecView key={spec?.id ?? "new"} spec={spec} />
      {spec && <RecordPanel contentType="filling.packagingspec" objectId={spec.id} />}
    </Stack>
  );
}

interface LineDraft {
  id?: number;
  material: string | null;
  quantity_per_unit: string;
  scrap_allowance_pct: string;
}

interface Draft {
  finished_product: string | null;
  bulk_product: string | null;
  fill_quantity: string;
  fill_unit: string | null;
  fill_tolerance_pct: string;
  units_per_case: string;
  cases_per_pallet: string;
  change_note: string;
  lines: LineDraft[];
}

function toDraft(spec: PackagingSpecDetail | null): Draft {
  return {
    finished_product: spec ? String(spec.finished_product) : null,
    bulk_product: spec ? String(spec.bulk_product) : null,
    fill_quantity: spec ? trimDecimal(spec.fill_quantity) : "",
    fill_unit: spec ? String(spec.fill_unit) : null,
    fill_tolerance_pct: spec ? trimDecimal(spec.fill_tolerance_pct) : "1",
    units_per_case: spec ? String(spec.units_per_case) : "12",
    cases_per_pallet: spec?.cases_per_pallet ? String(spec.cases_per_pallet) : "",
    change_note: spec?.change_note ?? "",
    lines: (spec?.lines ?? []).map((line) => ({
      id: line.id,
      material: String(line.material),
      quantity_per_unit: trimDecimal(line.quantity_per_unit),
      scrap_allowance_pct: trimDecimal(line.scrap_allowance_pct ?? "0"),
    })),
  };
}

function linePayload(line: LineDraft): PackagingSpecLine {
  return {
    material: Number(line.material),
    quantity_per_unit: normalizeDecimal(line.quantity_per_unit),
    scrap_allowance_pct: normalizeDecimal(line.scrap_allowance_pct || "0"),
  };
}

/** Taslağın satırlarını kaydeder: kaldırılan silinir, yeni eklenir, değişen güncellenir. */
async function syncLines(spec: PackagingSpecDetail, lines: LineDraft[]) {
  const kept = new Set(lines.map((line) => line.id).filter(Boolean));
  for (const old of spec.lines) if (old.id && !kept.has(old.id)) await removeSpecLine(old.id);
  for (const line of lines) {
    if (!line.id) {
      await addSpecLine(spec.id, linePayload(line));
      continue;
    }
    const old = spec.lines.find((row) => row.id === line.id);
    const payload = linePayload(line);
    if (
      old &&
      (old.material !== payload.material ||
        Number(old.quantity_per_unit) !== Number(payload.quantity_per_unit) ||
        Number(old.scrap_allowance_pct ?? 0) !== Number(payload.scrap_allowance_pct))
    )
      await updateSpecLine(line.id, payload);
  }
}

function SpecView({ spec }: { spec: PackagingSpecDetail | null }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canPlan = hasAnyRole(user, PLAN_ROLES);
  const editable = canPlan && (spec === null || spec.is_editable);
  const [draft, setDraft] = useState(() => toDraft(spec));
  const [error, setError] = useState("");
  const [confirmApprove, setConfirmApprove] = useState(false);
  const finished = useOptions({ endpoint: "materials", params: { material_type: "FINISHED" } });
  const bulk = useOptions({ endpoint: "materials", params: { material_type: "BULK" } });
  const packaging = useOptions({ endpoint: "materials", params: { material_type: "PACKAGING" } });
  const units = useOptions({ endpoint: "units" });
  const set = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));
  const setLine = (index: number, patch: Partial<LineDraft>) =>
    set({ lines: draft.lines.map((line, i) => (i === index ? { ...line, ...patch } : line)) });

  const done = (saved: PackagingSpecDetail, message: string) => {
    setError("");
    notifications.show({ color: "green", message });
    queryClient.setQueryData(["filling", "spec", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["filling"] });
    if (saved.id !== spec?.id) navigate(specPath(saved.id), { replace: spec === null });
  };

  const save = useMutation({
    mutationFn: async () => {
      const header = {
        finished_product: idOrNull(draft.finished_product),
        bulk_product: idOrNull(draft.bulk_product),
        fill_quantity: normalizeDecimal(draft.fill_quantity),
        fill_unit: idOrNull(draft.fill_unit),
        fill_tolerance_pct: normalizeDecimal(draft.fill_tolerance_pct || "0"),
        units_per_case: Number(draft.units_per_case),
        cases_per_pallet: draft.cases_per_pallet ? Number(draft.cases_per_pallet) : null,
        change_note: draft.change_note.trim(),
      };
      if (!spec) return saveSpec(null, { ...header, lines: draft.lines.map(linePayload) });
      await saveSpec(spec.id, header);
      await syncLines(spec, draft.lines);
      return getSpec(spec.id);
    },
    onSuccess: (saved) => done(saved, ft.saved),
    onError: (err) => setError(getErrorMessage(err)),
  });
  const action = useMutation({
    mutationFn: (name: "copy" | "approve") => specAction(spec!.id, name),
    onSuccess: (saved, name) => {
      setConfirmApprove(false);
      done(saved, name === "approve" ? ft.approved : ft.saved);
    },
    onError: (err) => {
      setConfirmApprove(false);
      setError(getErrorMessage(err));
    },
  });
  const materialLabel = (id: string | null) =>
    (packaging.data ?? []).find((option) => option.value === id)?.label ?? "";

  return (
    <Stack>
      <Group justify="space-between">
        <Group>
          <Title order={2}>
            {spec ? ft.specTitle(spec.finished_product_code, spec.version_no) : ft.newSpec}
          </Title>
          {spec && <SpecStatusBadge status={spec.status} />}
        </Group>
        {canPlan && spec && (
          <Group gap="xs">
            {spec.is_editable && (
              <Button
                color="green"
                leftSection={<IconCheck size={16} />}
                onClick={() => setConfirmApprove(true)}
              >
                {ft.approveSpec}
              </Button>
            )}
            {spec.status !== "DRAFT" && (
              <Button
                variant="light"
                leftSection={<IconCopy size={16} />}
                loading={action.isPending}
                onClick={() => action.mutate("copy")}
              >
                {ft.copySpec}
              </Button>
            )}
          </Group>
        )}
      </Group>
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
          <Select
            label={ft.product}
            withAsterisk
            searchable
            disabled={!editable || spec !== null}
            data={finished.data ?? []}
            value={draft.finished_product}
            onChange={(value) => set({ finished_product: value })}
          />
          <Select
            label={ft.bulk}
            withAsterisk
            searchable
            disabled={!editable}
            data={bulk.data ?? []}
            value={draft.bulk_product}
            onChange={(value) => set({ bulk_product: value })}
          />
          <Group gap="xs" grow wrap="nowrap">
            <TextInput
              label={ft.fillQuantity}
              withAsterisk
              inputMode="decimal"
              disabled={!editable}
              value={draft.fill_quantity}
              onChange={(event) => set({ fill_quantity: event.currentTarget.value })}
            />
            <Select
              label={ft.fillUnit}
              withAsterisk
              disabled={!editable}
              data={units.data ?? []}
              value={draft.fill_unit}
              onChange={(value) => set({ fill_unit: value })}
            />
          </Group>
          <TextInput
            label={ft.fillTolerance}
            inputMode="decimal"
            disabled={!editable}
            value={draft.fill_tolerance_pct}
            onChange={(event) => set({ fill_tolerance_pct: event.currentTarget.value })}
          />
          <TextInput
            label={ft.unitsPerCase}
            withAsterisk
            inputMode="numeric"
            disabled={!editable}
            value={draft.units_per_case}
            onChange={(event) => set({ units_per_case: event.currentTarget.value })}
          />
          <TextInput
            label={ft.casesPerPallet}
            inputMode="numeric"
            disabled={!editable}
            value={draft.cases_per_pallet}
            onChange={(event) => set({ cases_per_pallet: event.currentTarget.value })}
          />
          <TextInput
            label={ft.changeNote}
            disabled={!editable}
            value={draft.change_note}
            onChange={(event) => set({ change_note: event.currentTarget.value })}
          />
          {spec?.approved_at && (
            <Info label={ft.approvedAt}>
              <Text size="sm">{`${spec.approved_by_name ?? ""} · ${formatDateTime(spec.approved_at)}`}</Text>
            </Info>
          )}
        </SimpleGrid>
      </Paper>

      <Group justify="space-between">
        <Title order={4}>{ft.lines}</Title>
        {editable && (
          <Button
            size="xs"
            variant="light"
            leftSection={<IconPlus size={14} />}
            onClick={() =>
              set({
                lines: [
                  ...draft.lines,
                  { material: null, quantity_per_unit: "1", scrap_allowance_pct: "0" },
                ],
              })
            }
          >
            {ft.addLine}
          </Button>
        )}
      </Group>
      <Table.ScrollContainer minWidth={560}>
        <Table striped fz="sm" data-testid="spec-lines">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{ft.material}</Table.Th>
              <Table.Th>{ft.perUnit}</Table.Th>
              <Table.Th>{ft.allowance}</Table.Th>
              {editable && <Table.Th />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {draft.lines.map((line, index) =>
              editable ? (
                <Table.Tr key={line.id ?? `new-${index}`}>
                  <Table.Td>
                    <Select
                      aria-label={ft.material}
                      searchable
                      data={packaging.data ?? []}
                      value={line.material}
                      onChange={(value) => setLine(index, { material: value })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      aria-label={ft.perUnit}
                      inputMode="decimal"
                      value={line.quantity_per_unit}
                      onChange={(event) =>
                        setLine(index, { quantity_per_unit: event.currentTarget.value })
                      }
                    />
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      aria-label={ft.allowance}
                      inputMode="decimal"
                      value={line.scrap_allowance_pct}
                      onChange={(event) =>
                        setLine(index, { scrap_allowance_pct: event.currentTarget.value })
                      }
                    />
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={ft.removeLine}
                      onClick={() => set({ lines: draft.lines.filter((_, i) => i !== index) })}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              ) : (
                <Table.Tr key={line.id ?? index}>
                  <Table.Td>
                    {materialLabel(line.material) ||
                      spec?.lines.find((row) => row.id === line.id)?.material_code}
                  </Table.Td>
                  <Table.Td>{formatNumber(line.quantity_per_unit)}</Table.Td>
                  <Table.Td>%{formatNumber(line.scrap_allowance_pct)}</Table.Td>
                </Table.Tr>
              ),
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {editable && (
        <Group justify="flex-end">
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            {ft.saveDraft}
          </Button>
        </Group>
      )}
      <ConfirmModal
        opened={confirmApprove}
        message={ft.approveSpecConfirm}
        confirmLabel={ft.approveSpec}
        loading={action.isPending}
        onConfirm={() => action.mutate("approve")}
        onClose={() => setConfirmApprove(false)}
      />
    </Stack>
  );
}
