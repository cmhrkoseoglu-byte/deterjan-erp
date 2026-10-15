import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
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
  IconCopy,
  IconDroplet,
  IconPencil,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  addLine,
  addStep,
  approveVersion,
  copyVersion,
  getVersion,
  listVersions,
  removeLine,
  removeStep,
  scaleVersion,
  updateLine,
  updateStep,
  updateVersion,
  type LinePayload,
  type RecipeLine,
  type RecipeStep,
  type RecipeVersionDetail,
  type StepPayload,
} from "../../api/recipes";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime, formatNumber } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal } from "../common/forms";
import { RecordFormModal } from "../common/RecordFormModal";
import { ct } from "../common/strings";
import { useOptions } from "../common/useOptions";
import { compareLines, type LineChange } from "./compare";
import { RECIPE_WRITE_ROLES, RECIPES_BASE, lineFields, stepFields, versionFields } from "./config";
import { StatusBadge } from "./StatusBadge";
import { rt } from "./strings";

const NOWRAP = { whiteSpace: "nowrap" } as const;

type Removal = { kind: "line"; item: RecipeLine } | { kind: "step"; item: RecipeStep };

/** Reçete sürümü: satırlar, adımlar, onay, kopyalama, karşılaştırma ve ölçekleme. */
export function VersionPage() {
  const params = useParams();
  const recipeId = Number(params.recipeId);
  const versionId = Number(params.versionId);
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canWrite = hasAnyRole(user, RECIPE_WRITE_ROLES);

  const [lineEdit, setLineEdit] = useState<{ open: boolean; line: RecipeLine | null }>({
    open: false,
    line: null,
  });
  const [stepEdit, setStepEdit] = useState<{ open: boolean; step: RecipeStep | null }>({
    open: false,
    step: null,
  });
  const [headerOpen, setHeaderOpen] = useState(false);
  const [removal, setRemoval] = useState<Removal | null>(null);
  const [approveOpen, setApproveOpen] = useState(false);
  const [copyOpen, setCopyOpen] = useState(false);
  const [note, setNote] = useState("");
  const [compareId, setCompareId] = useState<string | null>(null);

  const version = useQuery({
    queryKey: ["version", versionId],
    queryFn: () => getVersion(versionId),
  });
  const versions = useQuery({
    queryKey: ["recipe", recipeId, "versions"],
    queryFn: () => listVersions(recipeId),
  });
  const other = useQuery({
    queryKey: ["version", Number(compareId)],
    queryFn: () => getVersion(Number(compareId)),
    enabled: Boolean(compareId),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["version", versionId] });
    void queryClient.invalidateQueries({ queryKey: ["recipe", recipeId] });
    void queryClient.invalidateQueries({ queryKey: ["recipes"] });
  };
  const fail = (error: unknown) =>
    notifications.show({ color: "red", message: getErrorMessage(error) });

  const approve = useMutation({
    mutationFn: () => approveVersion(versionId, note),
    onSuccess: () => {
      notifications.show({ color: "green", message: rt.approved });
      setApproveOpen(false);
      refresh();
    },
    onError: fail,
  });
  const copy = useMutation({
    mutationFn: () => copyVersion(versionId, note),
    onSuccess: (created) => {
      notifications.show({ color: "green", message: rt.copied(created.version_no) });
      setCopyOpen(false);
      refresh();
      navigate(`${RECIPES_BASE}/${recipeId}/surumler/${created.id}`);
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (target: Removal) =>
      target.kind === "line" ? removeLine(target.item.id) : removeStep(target.item.id),
    onSuccess: refresh,
    onError: fail,
    onSettled: () => setRemoval(null),
  });

  if (version.isLoading) return <Loader />;
  if (version.isError || !version.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(version.error)}
      </Alert>
    );
  const data = version.data;
  const editable = canWrite && data.can_edit;
  const otherVersions = (versions.data ?? []).filter((v) => v.id !== versionId);

  return (
    <Stack>
      <Anchor component={Link} to={`${RECIPES_BASE}/${recipeId}`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {`${data.recipe_code} - ${data.recipe_name}`}
        </Group>
      </Anchor>

      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{rt.version(data.version_no)}</Title>
          <StatusBadge status={data.status} />
        </Group>
        <Group>
          {data.can_approve && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => {
                setNote("");
                setApproveOpen(true);
              }}
            >
              {rt.approve}
            </Button>
          )}
          {canWrite && (
            <Button
              variant="default"
              leftSection={<IconCopy size={16} />}
              onClick={() => {
                setNote("");
                setCopyOpen(true);
              }}
            >
              {rt.copy}
            </Button>
          )}
        </Group>
      </Group>

      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <Info
            label={rt.batch}
            value={`${formatNumber(data.batch_size)} ${data.batch_unit_code}`}
          />
          <Info
            label={rt.createdBy}
            value={[data.created_by_name, formatDateTime(data.created_at)]
              .filter(Boolean)
              .join(", ")}
          />
          <Info
            label={rt.approvedBy}
            value={
              data.approved_by_name
                ? `${data.approved_by_name}, ${formatDateTime(data.approved_at)}`
                : "-"
            }
          />
        </SimpleGrid>
        {data.change_note && (
          <Text size="sm" mt="sm" style={{ whiteSpace: "pre-wrap" }}>
            <b>{rt.changeNote}:</b> {data.change_note}
          </Text>
        )}
        {editable && (
          <Button
            variant="subtle"
            size="xs"
            mt="sm"
            leftSection={<IconPencil size={14} />}
            onClick={() => setHeaderOpen(true)}
          >
            {rt.editHeader}
          </Button>
        )}
      </Paper>
      {!data.can_edit && (
        <Alert color="gray" variant="light">
          {rt.locked}
        </Alert>
      )}

      <Group justify="space-between" mt="sm">
        <Title order={3}>{rt.lines}</Title>
        {editable && (
          <Button
            size="sm"
            leftSection={<IconPlus size={16} />}
            onClick={() => setLineEdit({ open: true, line: null })}
          >
            {rt.addLine}
          </Button>
        )}
      </Group>
      <LinesTable
        lines={data.lines}
        editable={editable}
        onEdit={(line) => setLineEdit({ open: true, line })}
        onRemove={(line) => setRemoval({ kind: "line", item: line })}
      />

      <Group justify="space-between" mt="sm">
        <Title order={3}>{rt.steps}</Title>
        {editable && (
          <Button
            size="sm"
            variant="light"
            leftSection={<IconPlus size={16} />}
            onClick={() => setStepEdit({ open: true, step: null })}
          >
            {rt.addStep}
          </Button>
        )}
      </Group>
      <StepsTable
        steps={data.steps}
        editable={editable}
        onEdit={(step) => setStepEdit({ open: true, step })}
        onRemove={(step) => setRemoval({ kind: "step", item: step })}
      />

      {otherVersions.length > 0 && (
        <Stack gap="xs" mt="sm">
          <Title order={3}>{rt.compare}</Title>
          <Select
            label={rt.compareWith}
            data={otherVersions.map((v) => ({
              value: String(v.id),
              label: `v${v.version_no} (${rt.status[v.status]})`,
            }))}
            value={compareId}
            onChange={setCompareId}
            clearable
            maw={320}
          />
          {other.data && <CompareTable base={data} other={other.data} />}
        </Stack>
      )}

      {data.lines.length > 0 && <ScalePanel version={data} />}

      <RecordFormModal<RecipeLine>
        opened={lineEdit.open}
        title={lineEdit.line ? `${rt.line}: ${lineEdit.line.material_code}` : rt.addLine}
        fields={lineFields}
        record={lineEdit.line}
        defaults={{ tolerance_pct: "2" }}
        onClose={() => setLineEdit({ open: false, line: null })}
        onSubmit={(payload) =>
          lineEdit.line
            ? updateLine(lineEdit.line.id, payload as LinePayload)
            : addLine(versionId, payload as LinePayload)
        }
        onSaved={() => {
          setLineEdit({ open: false, line: null });
          refresh();
        }}
      />
      <RecordFormModal<RecipeStep>
        opened={stepEdit.open}
        title={stepEdit.step ? `${rt.step} ${stepEdit.step.sequence}` : rt.addStep}
        fields={stepFields}
        record={stepEdit.step}
        onClose={() => setStepEdit({ open: false, step: null })}
        onSubmit={(payload) =>
          stepEdit.step
            ? updateStep(stepEdit.step.id, payload as StepPayload)
            : addStep(versionId, payload as StepPayload)
        }
        onSaved={() => {
          setStepEdit({ open: false, step: null });
          refresh();
        }}
      />
      <RecordFormModal<RecipeVersionDetail>
        opened={headerOpen}
        title={rt.editHeader}
        fields={versionFields}
        record={data}
        onClose={() => setHeaderOpen(false)}
        onSubmit={(payload) => updateVersion(versionId, payload)}
        onSaved={() => {
          setHeaderOpen(false);
          refresh();
        }}
      />
      <ConfirmModal
        opened={removal !== null}
        message={
          removal?.kind === "line"
            ? rt.removeLineConfirm(removal.item.material_code)
            : removal
              ? rt.removeStepConfirm(removal.item.sequence)
              : ""
        }
        confirmLabel={rt.remove}
        danger
        loading={remove.isPending}
        onConfirm={() => removal && remove.mutate(removal)}
        onClose={() => setRemoval(null)}
      />
      <Modal opened={approveOpen} onClose={() => setApproveOpen(false)} title={rt.approve}>
        <Stack>
          <Text size="sm">{rt.approveConfirm(data.version_no)}</Text>
          <Textarea label="Not" value={note} onChange={(e) => setNote(e.currentTarget.value)} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setApproveOpen(false)}>
              {ct.cancel}
            </Button>
            <Button color="green" loading={approve.isPending} onClick={() => approve.mutate()}>
              {rt.approve}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal opened={copyOpen} onClose={() => setCopyOpen(false)} title={rt.copy}>
        <Stack>
          <Textarea
            label={rt.changeNote}
            placeholder={rt.copyNote}
            value={note}
            onChange={(e) => setNote(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCopyOpen(false)}>
              {ct.cancel}
            </Button>
            <Button loading={copy.isPending} onClick={() => copy.mutate()}>
              {rt.copy}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm">{value}</Text>
    </div>
  );
}

function LinesTable({
  lines,
  editable,
  onEdit,
  onRemove,
}: {
  lines: RecipeLine[];
  editable: boolean;
  onEdit: (line: RecipeLine) => void;
  onRemove: (line: RecipeLine) => void;
}) {
  if (lines.length === 0) return <Text c="dimmed">{rt.noLines}</Text>;
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={50}>{rt.sequence}</Table.Th>
            <Table.Th>{rt.material}</Table.Th>
            <Table.Th ta="right">{rt.quantity}</Table.Th>
            <Table.Th ta="right">{rt.tolerance}</Table.Th>
            <Table.Th>{rt.instruction}</Table.Th>
            {editable && <Table.Th w={80} aria-label={ct.actions} />}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {lines.map((line) => (
            <Table.Tr key={line.id}>
              <Table.Td>{line.sequence}</Table.Td>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <Text size="sm">{`${line.material_code} - ${line.material_name}`}</Text>
                  {line.is_water && (
                    <Badge
                      size="xs"
                      variant="light"
                      leftSection={<IconDroplet size={10} />}
                      style={{ flexShrink: 0 }}
                    >
                      {rt.water}
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td
                ta="right"
                style={NOWRAP}
              >{`${formatNumber(line.quantity)} ${line.unit_code}`}</Table.Td>
              <Table.Td ta="right">{`±${formatNumber(line.tolerance_pct)}`}</Table.Td>
              <Table.Td>
                <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                  {line.instruction}
                </Text>
              </Table.Td>
              {editable && (
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon variant="subtle" aria-label={ct.edit} onClick={() => onEdit(line)}>
                      <IconPencil size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={rt.removeLine}
                      onClick={() => onRemove(line)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function StepsTable({
  steps,
  editable,
  onEdit,
  onRemove,
}: {
  steps: RecipeStep[];
  editable: boolean;
  onEdit: (step: RecipeStep) => void;
  onRemove: (step: RecipeStep) => void;
}) {
  if (steps.length === 0) return <Text c="dimmed">{rt.noSteps}</Text>;
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={50}>{rt.sequence}</Table.Th>
            <Table.Th>{rt.description}</Table.Th>
            <Table.Th ta="right">{rt.duration}</Table.Th>
            <Table.Th ta="right">{rt.temperature}</Table.Th>
            <Table.Th ta="right">{rt.rpm}</Table.Th>
            {editable && <Table.Th w={80} aria-label={ct.actions} />}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {steps.map((step) => (
            <Table.Tr key={step.id}>
              <Table.Td>{step.sequence}</Table.Td>
              <Table.Td style={{ whiteSpace: "pre-wrap" }}>{step.description}</Table.Td>
              <Table.Td ta="right">{step.duration_min ?? ""}</Table.Td>
              <Table.Td ta="right">{formatNumber(step.temperature_c)}</Table.Td>
              <Table.Td ta="right">{step.mixer_rpm ?? ""}</Table.Td>
              {editable && (
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    <ActionIcon variant="subtle" aria-label={ct.edit} onClick={() => onEdit(step)}>
                      <IconPencil size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={rt.removeStep}
                      onClick={() => onRemove(step)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </Table.Td>
              )}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

const CHANGE_LABEL: Record<LineChange, { label: string; color: string }> = {
  added: { label: rt.compareAdded, color: "green" },
  removed: { label: rt.compareRemoved, color: "red" },
  changed: { label: rt.compareChanged, color: "orange" },
  same: { label: rt.compareSame, color: "gray" },
};

function qty(line: RecipeLine | null): string {
  return line
    ? `${formatNumber(line.quantity)} ${line.unit_code} (±${formatNumber(line.tolerance_pct)}%)`
    : "-";
}

/** İki sürümün satırlarını yan yana gösterir (eski sürüm solda). */
function CompareTable({ base, other }: { base: RecipeVersionDetail; other: RecipeVersionDetail }) {
  const [left, right] = base.version_no < other.version_no ? [base, other] : [other, base];
  const rows = compareLines(left.lines, right.lines);
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{rt.material}</Table.Th>
            <Table.Th ta="right">{`v${left.version_no}`}</Table.Th>
            <Table.Th ta="right">{`v${right.version_no}`}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.key}>
              <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
              <Table.Td ta="right" style={NOWRAP}>
                {qty(row.left)}
              </Table.Td>
              <Table.Td ta="right" style={NOWRAP}>
                {qty(row.right)}
              </Table.Td>
              <Table.Td>
                <Badge variant="light" color={CHANGE_LABEL[row.change].color}>
                  {CHANGE_LABEL[row.change].label}
                </Badge>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** Hedef üretim miktarına göre ihtiyaç listesi (temel birimde). */
function ScalePanel({ version }: { version: RecipeVersionDetail }) {
  const [qtyText, setQtyText] = useState(version.batch_size.replace(/\.?0+$/, ""));
  const [unit, setUnit] = useState<string | null>(String(version.batch_unit));
  const units = useOptions({ endpoint: "units" });
  const scale = useMutation({
    mutationFn: () => scaleVersion(version.id, normalizeDecimal(qtyText), unit ?? ""),
  });

  return (
    <Stack gap="xs" mt="sm">
      <Title order={3}>{rt.scaleTitle}</Title>
      <Group align="flex-end">
        <TextInput
          label={rt.scaleQty}
          inputMode="decimal"
          value={qtyText}
          onChange={(e) => setQtyText(e.currentTarget.value)}
          w={160}
        />
        <Select label={rt.unit} data={units.data ?? []} value={unit} onChange={setUnit} w={200} />
        <Button variant="light" loading={scale.isPending} onClick={() => scale.mutate()}>
          {rt.scale}
        </Button>
      </Group>
      {scale.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(scale.error)}
        </Alert>
      )}
      {scale.data && (
        <>
          <Text size="xs" c="dimmed">
            {rt.scaleHint}
          </Text>
          <Table striped>
            <Table.Tbody>
              {scale.data.map((row) => (
                <Table.Tr key={row.line}>
                  <Table.Td>{`${row.material_code} - ${row.material_name}`}</Table.Td>
                  <Table.Td ta="right">{`${formatNumber(row.quantity)} ${row.unit_code}`}</Table.Td>
                  <Table.Td ta="right">{`±${formatNumber(row.tolerance_pct)}%`}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </>
      )}
    </Stack>
  );
}
