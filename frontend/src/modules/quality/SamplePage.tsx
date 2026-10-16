import {
  Alert,
  Anchor,
  Badge,
  Button,
  Grid,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowLeft,
  IconCertificate,
  IconGavel,
  IconLink,
  IconPencil,
  IconX,
} from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  assignSpecification,
  cancelSample,
  coaUrl,
  decide,
  getSample,
  listSpecifications,
  recordResult,
  type DecisionType,
  type QualityDecision,
  type SampleDetail,
  type SampleLine,
} from "../../api/quality";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { ct } from "../common/strings";
import { normalizeDecimal } from "../common/forms";
import { lotPath } from "../inventory/config";
import { idOrNull, useLocations } from "../inventory/options";
import { Info, LotStatusBadge } from "../inventory/shared";
import { ReasonModal } from "../production/shared";
import type { LotStatus } from "../../api/inventory";
import {
  APPROVAL_ROLES,
  DECISIONS,
  IN_PROCESS_DECISIONS,
  LAB_ROLES,
  OPEN_SAMPLE_STATUSES,
  QUALITY_BASE,
  specPath,
} from "./config";
import { limitText, numericOutOfSpec, resultText } from "./limits";
import { ReviewModal } from "./QualityPage";
import { ApprovalBadge, DecisionBadge, SampleStatusBadge } from "./shared";
import { qt } from "./strings";

/** Numune detayı: sınırlarla sonuç girişi, düzeltme geçmişi, karar, CoA ve yorum paneli. */
export function SamplePage() {
  const sampleId = Number(useParams().sampleId);
  const query = useQuery({
    queryKey: ["quality", "sample", sampleId],
    queryFn: () => getSample(sampleId),
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
        <SampleDetailView sample={query.data} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <RecordPanel contentType="quality.sample" objectId={query.data.id} />
      </Grid.Col>
    </Grid>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return (saved: SampleDetail) => {
    queryClient.setQueryData(["quality", "sample", saved.id], saved);
    void queryClient.invalidateQueries({ queryKey: ["quality"] });
    void queryClient.invalidateQueries({ queryKey: ["inventory"] });
  };
}

function SampleDetailView({ sample }: { sample: SampleDetail }) {
  const { user } = useAuth();
  const refresh = useRefresh();
  const isLab = hasAnyRole(user, LAB_ROLES);
  const isOpen = OPEN_SAMPLE_STATUSES.includes(sample.status);
  const canEnter = isLab && (sample.status === "PENDING" || sample.status === "IN_TEST");
  const [deciding, setDeciding] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [review, setReview] = useState<{ row: QualityDecision; approve: boolean } | null>(null);
  const pending = sample.decisions.find((row) => row.approval_status === "PENDING");

  return (
    <Stack>
      <Anchor component={Link} to={`${QUALITY_BASE}/kuyruk`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {qt.backToQueue}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{qt.sampleTitle(sample.number)}</Title>
          <SampleStatusBadge status={sample.status} />
        </Group>
        <Group gap="xs">
          {canEnter && sample.specification && (
            <Button leftSection={<IconGavel size={16} />} onClick={() => setDeciding(true)}>
              {qt.decide}
            </Button>
          )}
          {pending && hasAnyRole(user, APPROVAL_ROLES) && (
            <>
              <Button color="green" onClick={() => setReview({ row: pending, approve: true })}>
                {qt.approve}
              </Button>
              <Button
                color="red"
                variant="light"
                onClick={() => setReview({ row: pending, approve: false })}
              >
                {qt.refuse}
              </Button>
            </>
          )}
          {sample.coa_available && (
            <Button
              component="a"
              href={coaUrl(sample.id)}
              target="_blank"
              variant="default"
              leftSection={<IconCertificate size={16} />}
            >
              {qt.coa}
            </Button>
          )}
          {isLab && sample.allowed_transitions.includes("CANCELLED") && (
            <Button
              color="red"
              variant="subtle"
              leftSection={<IconX size={16} />}
              onClick={() => setCancelling(true)}
            >
              {qt.cancelSample}
            </Button>
          )}
        </Group>
      </Group>

      <Paper withBorder p="md" radius="md">
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={qt.lot}>
            <Anchor component={Link} to={lotPath(sample.lot)} size="sm">
              {sample.lot_no}
            </Anchor>
            <LotStatusBadge status={sample.lot_status as LotStatus} />
          </Info>
          <Info label={qt.material}>
            <Text size="sm">{`${sample.material_code} - ${sample.material_name}`}</Text>
          </Info>
          <Info label={qt.stageLabel}>
            <Text size="sm">{qt.stage[sample.stage]}</Text>
          </Info>
          <Info label={qt.spec}>
            {sample.specification ? (
              <Anchor component={Link} to={specPath(sample.specification)} size="sm">
                {sample.specification_label}
              </Anchor>
            ) : null}
          </Info>
          <Info label={qt.origin}>
            <Text size="sm">{sample.origin_display}</Text>
          </Info>
          <Info label={qt.takenBy}>
            <Text size="sm">
              {[sample.taken_by_name, formatDateTime(sample.taken_at)].filter(Boolean).join(" · ")}
            </Text>
          </Info>
          {sample.decided_at && (
            <Info label={qt.decidedAt}>
              <Text size="sm">{formatDateTime(sample.decided_at)}</Text>
            </Info>
          )}
          {sample.note && (
            <Info label={qt.note}>
              <Text size="sm">{sample.note}</Text>
            </Info>
          )}
          {sample.status === "CANCELLED" && (
            <Info label={qt.cancelReason}>
              <Text size="sm">{sample.cancel_reason}</Text>
            </Info>
          )}
        </SimpleGrid>
      </Paper>

      {!sample.specification && isOpen && <AssignSpec sample={sample} canAssign={isLab} />}

      {sample.specification && (
        <>
          <Title order={4}>{qt.results}</Title>
          {isOpen && sample.missing_tests.length > 0 && (
            <Alert color="yellow" variant="light">
              {qt.missing(sample.missing_tests.join(", "))}
            </Alert>
          )}
          {sample.out_of_spec_tests.length > 0 && (
            <Alert color="red" variant="light">
              {qt.outOfSpecList(sample.out_of_spec_tests.join(", "))}
            </Alert>
          )}
          <Table.ScrollContainer minWidth={720}>
            <Table fz="sm" data-testid="results">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{qt.test}</Table.Th>
                  <Table.Th>{qt.limits}</Table.Th>
                  <Table.Th>{qt.result}</Table.Th>
                  <Table.Th>{qt.measuredBy}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sample.lines.map((row) => (
                  <ResultRow key={row.line.id} sample={sample} row={row} editable={canEnter} />
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}

      {sample.decisions.length > 0 && (
        <>
          <Title order={4}>{qt.decisions}</Title>
          <Stack gap="xs">
            {sample.decisions.map((row) => (
              <Paper key={row.id} withBorder p="sm" radius="md">
                <Group gap="xs">
                  <DecisionBadge decision={row.decision} />
                  {row.approval_status !== "NOT_REQUIRED" && (
                    <ApprovalBadge status={row.approval_status} />
                  )}
                  <Text size="sm" c="dimmed">
                    {`${row.decided_by_name ?? ""} · ${formatDateTime(row.decided_at)}`}
                  </Text>
                  {row.release_location_code && (
                    <Badge variant="outline" color="gray">
                      {row.release_location_code}
                    </Badge>
                  )}
                </Group>
                {row.reason && <Text size="sm">{row.reason}</Text>}
                {row.approved_at && (
                  <Text size="sm" c="dimmed">
                    {`${qt.approvedBy}: ${row.approved_by_name ?? ""} · ${formatDateTime(row.approved_at)}${
                      row.approval_note ? ` · ${row.approval_note}` : ""
                    }`}
                  </Text>
                )}
              </Paper>
            ))}
          </Stack>
        </>
      )}

      {deciding && (
        <DecisionModal sample={sample} onClose={() => setDeciding(false)} onDone={refresh} />
      )}
      <ReasonModal
        opened={cancelling}
        title={qt.cancelSample}
        label={qt.cancelReason}
        confirmLabel={qt.cancelSample}
        submit={(reason) => cancelSample(sample.id, reason)}
        onClose={() => setCancelling(false)}
        onDone={(saved) => {
          setCancelling(false);
          notifications.show({ color: "green", message: qt.cancelled });
          refresh(saved);
        }}
      />
      <ReviewModal
        target={review}
        onClose={() => setReview(null)}
        onDone={() => {
          setReview(null);
          void getSample(sample.id).then(refresh);
        }}
      />
    </Stack>
  );
}

function AssignSpec({ sample, canAssign }: { sample: SampleDetail; canAssign: boolean }) {
  const refresh = useRefresh();
  const specs = useQuery({
    queryKey: ["quality", "specs", "approved", sample.material, sample.stage],
    queryFn: () =>
      listSpecifications({
        material: sample.material,
        sample_stage: sample.stage,
        status: "APPROVED",
      }),
  });
  const approved = specs.data?.results[0];
  const mutation = useMutation({
    mutationFn: () => assignSpecification(sample.id, approved!.id),
    onSuccess: refresh,
    onError: (err) => notifications.show({ color: "red", message: getErrorMessage(err) }),
  });
  return (
    <Alert color="yellow" variant="light">
      <Stack gap="xs">
        <Text size="sm">{approved ? qt.assignSpecHint : qt.noSpec}</Text>
        {canAssign && approved && (
          <Group>
            <Button
              size="xs"
              leftSection={<IconLink size={14} />}
              loading={mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {`${qt.assignSpec} (v${approved.version_no})`}
            </Button>
          </Group>
        )}
      </Stack>
    </Alert>
  );
}

/** Bir test satırı: sınır, geçerli sonuç (spec dışıysa kırmızı), giriş ve düzeltme geçmişi. */
function ResultRow({
  sample,
  row,
  editable,
}: {
  sample: SampleDetail;
  row: SampleLine;
  editable: boolean;
}) {
  const refresh = useRefresh();
  const { line, current, history } = row;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [passed, setPassed] = useState<string>("true");
  const [instrument, setInstrument] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const isCorrection = current !== null;
  const showInput = editable && (!current || editing);
  const preview = numericOutOfSpec(line, value);

  const mutation = useMutation({
    mutationFn: () =>
      recordResult(sample.id, {
        spec_line: line.id,
        numeric_value: line.result_type === "NUMERIC" ? normalizeDecimal(value) : null,
        text_value: line.result_type === "TEXT" ? value.trim() : "",
        passed: line.result_type === "PASS_FAIL" ? passed === "true" : null,
        instrument: instrument.trim(),
        note: note.trim(),
      }),
    onSuccess: (saved) => {
      setEditing(false);
      setValue("");
      setNote("");
      setError("");
      notifications.show({ color: "green", message: qt.saved(line.test_code) });
      refresh(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const filled = line.result_type === "PASS_FAIL" || value.trim() !== "";
  const canSave = filled && (!isCorrection || note.trim() !== "");

  return (
    <>
      <Table.Tr>
        <Table.Td>
          <Text size="sm" fw={500}>
            {line.test_name}
          </Text>
          <Text size="xs" c="dimmed">
            {line.is_mandatory ? qt.mandatory : qt.optional}
          </Text>
        </Table.Td>
        <Table.Td>{limitText(line)}</Table.Td>
        <Table.Td>
          {current ? (
            <Group gap="xs" wrap="wrap">
              <Text
                size="sm"
                fw={600}
                c={current.is_within_spec ? "green" : "red"}
                data-testid={`result-${line.test_code}`}
              >
                {resultText(line, current)}
              </Text>
              {!current.is_within_spec && (
                <Badge color="red" size="xs" style={{ flexShrink: 0, overflow: "visible" }}>
                  {qt.outOfSpec}
                </Badge>
              )}
              {history.length > 0 && (
                <Tooltip
                  multiline
                  w={260}
                  label={history
                    .map(
                      (old) =>
                        `${resultText(line, old)} · ${formatDateTime(old.measured_at)} · ${old.measured_by_name ?? ""}`,
                    )
                    .join("\n")}
                >
                  <Badge variant="outline" color="gray" size="xs">
                    {qt.history(history.length)}
                  </Badge>
                </Tooltip>
              )}
              {editable && !editing && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  leftSection={<IconPencil size={12} />}
                  onClick={() => setEditing(true)}
                >
                  {qt.correct}
                </Button>
              )}
            </Group>
          ) : (
            !showInput && "—"
          )}
          {current?.note && (
            <Text size="xs" c="dimmed">
              {current.note}
            </Text>
          )}
        </Table.Td>
        <Table.Td>
          {current &&
            `${current.measured_by_name ?? ""} · ${formatDateTime(current.measured_at)}${
              current.instrument ? ` · ${current.instrument}` : ""
            }`}
        </Table.Td>
      </Table.Tr>
      {showInput && (
        <Table.Tr>
          <Table.Td colSpan={4}>
            <Group align="flex-end" gap="xs" wrap="wrap">
              {line.result_type === "PASS_FAIL" ? (
                <SegmentedControl
                  aria-label={line.test_name}
                  value={passed}
                  onChange={setPassed}
                  data={[
                    { value: "true", label: qt.pass },
                    { value: "false", label: qt.fail },
                  ]}
                />
              ) : (
                <TextInput
                  label={`${line.test_name}${line.unit ? ` (${line.unit})` : ""}`}
                  inputMode={line.result_type === "NUMERIC" ? "decimal" : undefined}
                  value={value}
                  w={180}
                  error={preview ? qt.outOfSpec : undefined}
                  styles={preview ? { input: { color: "var(--mantine-color-red-7)" } } : undefined}
                  onChange={(event) => setValue(event.currentTarget.value)}
                />
              )}
              <TextInput
                label={qt.instrument}
                value={instrument}
                w={160}
                onChange={(event) => setInstrument(event.currentTarget.value)}
              />
              {isCorrection && (
                <TextInput
                  label={qt.correctionReason}
                  description={qt.correctionHint}
                  withAsterisk
                  value={note}
                  w={240}
                  onChange={(event) => setNote(event.currentTarget.value)}
                />
              )}
              <Button
                disabled={!canSave}
                loading={mutation.isPending}
                onClick={() => mutation.mutate()}
              >
                {qt.save}
              </Button>
              {editing && (
                <Button variant="default" onClick={() => setEditing(false)}>
                  {ct.cancel}
                </Button>
              )}
            </Group>
            {error && (
              <Text size="sm" c="red" mt={4}>
                {error}
              </Text>
            )}
          </Table.Td>
        </Table.Tr>
      )}
    </>
  );
}

function DecisionModal({
  sample,
  onClose,
  onDone,
}: {
  sample: SampleDetail;
  onClose: () => void;
  onDone: (saved: SampleDetail) => void;
}) {
  const inProcess = sample.stage === "IN_PROCESS";
  const options = (inProcess ? IN_PROCESS_DECISIONS : DECISIONS).filter(
    (value) => value !== "REWORK" || sample.material_type === "BULK" || sample.stage === "RETURN",
  );
  const hasOutOfSpec = sample.out_of_spec_tests.length > 0;
  const [decision, setDecision] = useState<DecisionType>(
    hasOutOfSpec ? (inProcess ? "REJECT" : "CONDITIONAL_RELEASE") : "RELEASE",
  );
  const [reason, setReason] = useState("");
  const [location, setLocation] = useState<string | null>(
    sample.default_release_location ? String(sample.default_release_location) : null,
  );
  const [error, setError] = useState("");
  const locations = useLocations();
  const releasing = !inProcess && (decision === "RELEASE" || decision === "CONDITIONAL_RELEASE");
  const reasonRequired = decision !== "RELEASE";
  const mutation = useMutation({
    mutationFn: () =>
      decide(sample.id, {
        decision,
        reason: reason.trim(),
        release_location: releasing ? idOrNull(location) : null,
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: qt.decided });
      onDone(saved);
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const label = (value: DecisionType) =>
    inProcess ? qt.inProcessDecision[value as "RELEASE" | "REJECT"] : qt.decision[value];

  return (
    <Modal opened onClose={onClose} title={`${qt.decisionTitle}: ${sample.lot_no}`}>
      <Stack>
        {sample.missing_tests.length > 0 && (
          <Alert color="yellow" variant="light">
            {qt.missing(sample.missing_tests.join(", "))}
          </Alert>
        )}
        {hasOutOfSpec && (
          <Alert color="red" variant="light">
            {qt.outOfSpecList(sample.out_of_spec_tests.join(", "))}
          </Alert>
        )}
        <SegmentedControl
          aria-label={qt.decisionLabel}
          fullWidth
          value={decision}
          onChange={(value) => setDecision(value as DecisionType)}
          data={options.map((value) => ({
            value,
            label: label(value),
            disabled: value === "RELEASE" && hasOutOfSpec && !inProcess,
          }))}
        />
        <Text size="sm" c="dimmed">
          {inProcess
            ? qt.inProcessHint
            : decision === "REWORK" && sample.stage === "RETURN"
              ? qt.returnReworkHint
              : qt.decisionHint[decision]}
        </Text>
        {releasing && (
          <Select
            label={qt.releaseLocation}
            description={qt.releaseLocationHint}
            searchable
            clearable
            data={(locations.data ?? []).filter((row) => row.type !== "QUARANTINE")}
            value={location}
            onChange={setLocation}
          />
        )}
        <Textarea
          label={reasonRequired ? qt.reasonRequired : qt.reason}
          withAsterisk={reasonRequired}
          autosize
          minRows={2}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
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
          <Button
            disabled={reasonRequired && !reason.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {qt.decide}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
