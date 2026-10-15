import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowLeft,
  IconCheck,
  IconCopy,
  IconPencil,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { listRecords } from "../../api/masterdata";
import {
  addSpecLine,
  approveSpecification,
  copySpecification,
  getSpecification,
  removeSpecLine,
  updateSpecification,
  updateSpecLine,
  type SpecificationDetail,
  type SpecLine,
  type SpecLinePayload,
  type TestDefinition,
} from "../../api/quality";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime } from "../../i18n/format";
import { ConfirmModal } from "../common/ConfirmModal";
import { normalizeDecimal, trimDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { Info } from "../inventory/shared";
import { LAB_ROLES, QUALITY_BASE, specPath } from "./config";
import { limitText } from "./limits";
import { SpecStatusBadge } from "./shared";
import { qt } from "./strings";

/** Spesifikasyon sürümü: taslakta satır ekle/düzenle/kaldır ve onayla; onaylıdan yeni sürüm aç. */
export function SpecificationPage() {
  const specId = Number(useParams().specId);
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isLab = hasAnyRole(user, LAB_ROLES);
  const [editing, setEditing] = useState<SpecLine | "new" | null>(null);
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState("");
  const query = useQuery({
    queryKey: ["quality", "spec", specId],
    queryFn: () => getSpecification(specId),
  });
  const refresh = (saved?: SpecificationDetail) => {
    if (saved) queryClient.setQueryData(["quality", "spec", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["quality"] });
  };
  const approve = useMutation({
    mutationFn: () => approveSpecification(specId),
    onSuccess: (saved) => {
      setConfirmApprove(false);
      setError("");
      notifications.show({ color: "green", message: qt.specApproved });
      refresh(saved);
    },
    onError: (err) => {
      setConfirmApprove(false);
      setError(getErrorMessage(err));
    },
  });
  const copy = useMutation({
    mutationFn: () => copySpecification(specId),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: qt.specCopied(saved.version_no) });
      refresh();
      navigate(specPath(saved.id));
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const saveNote = useMutation({
    mutationFn: () => updateSpecification(specId, { change_note: (note ?? "").trim() }),
    onSuccess: (saved) => {
      setNote(null);
      refresh(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: (line: SpecLine) => removeSpecLine(line.id),
    onSuccess: () => {
      notifications.show({ color: "green", message: qt.lineRemoved });
      refresh();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  if (query.isLoading) return <Loader />;
  if (query.isError || !query.data)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const spec = query.data;
  const canEdit = isLab && spec.is_editable;

  return (
    <Stack>
      <Anchor component={Link} to={`${QUALITY_BASE}/spesifikasyonlar`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {qt.tabs.specs}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>
            {qt.specTitle(spec.material_code, qt.stage[spec.sample_stage], spec.version_no)}
          </Title>
          <SpecStatusBadge status={spec.status} />
        </Group>
        <Group gap="xs">
          {canEdit && (
            <Button
              color="green"
              leftSection={<IconCheck size={16} />}
              onClick={() => setConfirmApprove(true)}
            >
              {qt.approveSpec}
            </Button>
          )}
          {isLab && !spec.is_editable && (
            <Button
              variant="default"
              leftSection={<IconCopy size={16} />}
              loading={copy.isPending}
              onClick={() => copy.mutate()}
            >
              {qt.copySpec}
            </Button>
          )}
        </Group>
      </Group>
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}
      {!spec.is_editable && (
        <Text size="sm" c="dimmed">
          {qt.lockedSpec}
        </Text>
      )}

      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={qt.material}>
            <Text size="sm">{`${spec.material_code} - ${spec.material_name}`}</Text>
          </Info>
          <Info label={qt.version}>
            <Text size="sm">
              {`v${spec.version_no}${spec.copied_from_no ? ` (${qt.copiedFrom(spec.copied_from_no)})` : ""}`}
            </Text>
          </Info>
          {spec.approved_at && (
            <Info label={qt.approvedBy}>
              <Text size="sm">{`${spec.approved_by_name ?? ""} · ${formatDateTime(spec.approved_at)}`}</Text>
            </Info>
          )}
        </SimpleGrid>
        {note === null ? (
          <Group mt="sm" gap="xs">
            <Text size="sm">
              <Text span c="dimmed" size="sm">
                {`${qt.changeNote}: `}
              </Text>
              {spec.change_note || "—"}
            </Text>
            {canEdit && (
              <ActionIcon
                variant="subtle"
                aria-label={ct.edit}
                onClick={() => setNote(spec.change_note)}
              >
                <IconPencil size={14} />
              </ActionIcon>
            )}
          </Group>
        ) : (
          <Group mt="sm" align="flex-end">
            <Textarea
              label={qt.changeNote}
              autosize
              minRows={1}
              style={{ flex: 1 }}
              value={note}
              onChange={(event) => setNote(event.currentTarget.value)}
            />
            <Button loading={saveNote.isPending} onClick={() => saveNote.mutate()}>
              {ct.save}
            </Button>
          </Group>
        )}
      </Paper>

      <Group justify="space-between">
        <Title order={4}>{qt.specLines}</Title>
        {canEdit && (
          <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => setEditing("new")}>
            {qt.addLine}
          </Button>
        )}
      </Group>
      {spec.lines.length === 0 ? (
        <Text size="sm" c="dimmed">
          {qt.noLines}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={600}>
          <Table striped fz="sm" data-testid="spec-lines">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>#</Table.Th>
                <Table.Th>{qt.test}</Table.Th>
                <Table.Th>{qt.limits}</Table.Th>
                <Table.Th>{qt.target}</Table.Th>
                <Table.Th>{qt.mandatory}</Table.Th>
                {canEdit && <Table.Th />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {spec.lines.map((line) => (
                <Table.Tr key={line.id}>
                  <Table.Td>{line.sequence}</Table.Td>
                  <Table.Td>{`${line.test_code} - ${line.test_name}`}</Table.Td>
                  <Table.Td>{limitText(line)}</Table.Td>
                  <Table.Td>{line.target_value ? trimDecimal(line.target_value) : ""}</Table.Td>
                  <Table.Td>{line.is_mandatory ? ct.yes : ct.no}</Table.Td>
                  {canEdit && (
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <ActionIcon
                          variant="subtle"
                          aria-label={ct.edit}
                          onClick={() => setEditing(line)}
                        >
                          <IconPencil size={14} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={qt.removeLine}
                          onClick={() => remove.mutate(line)}
                        >
                          <IconTrash size={14} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {editing && (
        <LineModal
          specId={spec.id}
          line={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            notifications.show({ color: "green", message: qt.lineSaved });
            refresh();
          }}
        />
      )}
      <ConfirmModal
        opened={confirmApprove}
        message={qt.approveSpecConfirm}
        confirmLabel={qt.approveSpec}
        loading={approve.isPending}
        onConfirm={() => approve.mutate()}
        onClose={() => setConfirmApprove(false)}
      />
    </Stack>
  );
}

function useTests() {
  return useQuery({
    queryKey: ["options", "quality/tests"],
    staleTime: 60_000,
    queryFn: async () =>
      (await listRecords<TestDefinition>("quality/tests", { is_active: true, page_size: 500 }))
        .results,
  });
}

function decimalOrNull(value: string): string | null {
  return value.trim() ? normalizeDecimal(value) : null;
}

function LineModal({
  specId,
  line,
  onClose,
  onDone,
}: {
  specId: number;
  line: SpecLine | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const tests = useTests();
  const [test, setTest] = useState<string | null>(line ? String(line.test) : null);
  const [min, setMin] = useState(line?.min_value ? trimDecimal(line.min_value) : "");
  const [max, setMax] = useState(line?.max_value ? trimDecimal(line.max_value) : "");
  const [target, setTarget] = useState(line?.target_value ? trimDecimal(line.target_value) : "");
  const [text, setText] = useState(line?.text_expected ?? "");
  const [mandatory, setMandatory] = useState(line?.is_mandatory ?? true);
  const [error, setError] = useState("");
  const selected = (tests.data ?? []).find((row) => String(row.id) === test);
  const numeric = (selected?.result_type ?? line?.result_type) === "NUMERIC";
  const mutation = useMutation({
    mutationFn: () => {
      const payload: SpecLinePayload = {
        test: test ? Number(test) : null,
        min_value: numeric ? decimalOrNull(min) : null,
        max_value: numeric ? decimalOrNull(max) : null,
        target_value: numeric ? decimalOrNull(target) : null,
        text_expected: numeric ? "" : text.trim(),
        is_mandatory: mandatory,
      };
      return line ? updateSpecLine(line.id, payload) : addSpecLine(specId, payload);
    },
    onSuccess: onDone,
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened onClose={onClose} title={line ? `${line.test_code}` : qt.addLine}>
      <Stack>
        <Select
          label={qt.lineTest}
          withAsterisk
          searchable
          disabled={line !== null}
          data={(tests.data ?? []).map((row) => ({
            value: String(row.id),
            label: `${row.code} - ${row.name}`,
          }))}
          value={test}
          onChange={setTest}
        />
        {numeric ? (
          <Group grow>
            <TextInput
              label={qt.minValue}
              inputMode="decimal"
              value={min}
              onChange={(event) => setMin(event.currentTarget.value)}
            />
            <TextInput
              label={qt.maxValue}
              inputMode="decimal"
              value={max}
              onChange={(event) => setMax(event.currentTarget.value)}
            />
            <TextInput
              label={qt.target}
              inputMode="decimal"
              value={target}
              onChange={(event) => setTarget(event.currentTarget.value)}
            />
          </Group>
        ) : (
          <TextInput
            label={qt.textExpected}
            value={text}
            onChange={(event) => setText(event.currentTarget.value)}
          />
        )}
        <Checkbox
          label={qt.mandatory}
          checked={mandatory}
          onChange={(event) => setMandatory(event.currentTarget.checked)}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button disabled={!test} loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {ct.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
