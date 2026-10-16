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
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowLeft, IconCheck, IconSearch, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import {
  cancelIncident,
  closeIncident,
  getIncident,
  saveInvestigation,
  startInvestigation,
  type Incident,
  type InvestigationPayload,
  type Severity,
} from "../../api/hse";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { AttachmentPanel } from "../../components/attachments/AttachmentPanel";
import { formatDate, formatDateTime } from "../../i18n/format";
import { RecordPanel } from "../../workflow/RecordPanel";
import { CancelModal } from "../inventory/CancelModal";
import { Info } from "../inventory/shared";
import { HSE_BASE, HSE_ROLES, SEVERITIES, isIncidentOpen } from "./config";
import { ErrorAlert, IncidentStatusBadge, SeverityBadge } from "./shared";
import { hs } from "./strings";

const CONTENT_TYPE = "hse.incident";

interface InvestigationDraft {
  severity: Severity;
  root_cause: string;
  corrective_action: string;
  action_owner: string;
  action_due: string;
}

function draftOf(incident: Incident): InvestigationDraft {
  return {
    severity: incident.severity,
    root_cause: incident.root_cause,
    corrective_action: incident.corrective_action,
    action_owner: incident.action_owner,
    action_due: incident.action_due ?? "",
  };
}

function payloadOf(draft: InvestigationDraft): InvestigationPayload {
  return {
    severity: draft.severity,
    root_cause: draft.root_cause.trim(),
    corrective_action: draft.corrective_action.trim(),
    action_owner: draft.action_owner.trim(),
    action_due: draft.action_due || null,
  };
}

function InvestigationFields({
  draft,
  onChange,
}: {
  draft: InvestigationDraft;
  onChange: (draft: InvestigationDraft) => void;
}) {
  return (
    <Stack>
      <Select
        label={hs.severityLabel}
        allowDeselect={false}
        data={SEVERITIES.map((value) => ({ value, label: hs.severity[value] }))}
        value={draft.severity}
        w={200}
        onChange={(value) => onChange({ ...draft, severity: (value ?? "LOW") as Severity })}
      />
      <Textarea
        label={hs.rootCause}
        autosize
        minRows={2}
        value={draft.root_cause}
        onChange={(event) => onChange({ ...draft, root_cause: event.currentTarget.value })}
      />
      <Textarea
        label={hs.correctiveAction}
        autosize
        minRows={2}
        value={draft.corrective_action}
        onChange={(event) => onChange({ ...draft, corrective_action: event.currentTarget.value })}
      />
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <TextInput
          label={hs.actionOwner}
          value={draft.action_owner}
          onChange={(event) => onChange({ ...draft, action_owner: event.currentTarget.value })}
        />
        <TextInput
          label={hs.actionDue}
          type="date"
          value={draft.action_due}
          onChange={(event) => onChange({ ...draft, action_due: event.currentTarget.value })}
        />
      </SimpleGrid>
    </Stack>
  );
}

function CloseModal({
  incident,
  draft: initial,
  onClose,
  onDone,
}: {
  incident: Incident;
  draft: InvestigationDraft;
  onClose: () => void;
  onDone: (saved: Incident) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [note, setNote] = useState(incident.closed_note);
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => closeIncident(incident.id, { ...payloadOf(draft), closed_note: note.trim() }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: hs.closedMsg });
      onDone(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const ready = draft.root_cause.trim() !== "" && draft.corrective_action.trim() !== "";
  return (
    <Modal opened onClose={onClose} title={hs.closeTitle} size="lg">
      <Stack>
        <Text size="sm" c="dimmed">
          {hs.closeHint}
        </Text>
        <InvestigationFields draft={draft} onChange={setDraft} />
        <Textarea
          label={hs.closedNote}
          autosize
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {hs.cancel}
          </Button>
          <Button
            color="green"
            leftSection={<IconCheck size={18} />}
            disabled={!ready}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {hs.closeIncident}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function TextBlock({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
        {value}
      </Text>
    </Stack>
  );
}

function IncidentView({ incident }: { incident: Incident }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const manager = hasAnyRole(user, HSE_ROLES);
  const open = isIncidentOpen(incident);
  const [draft, setDraft] = useState(() => draftOf(incident));
  const [closing, setClosing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const refresh = (saved: Incident) => {
    queryClient.setQueryData(["hse", "incident", incident.id], saved);
    setDraft(draftOf(saved));
    void queryClient.invalidateQueries({ queryKey: ["hse"] });
    void queryClient.invalidateQueries({ queryKey: ["workflow"] });
  };
  const investigate = useMutation({
    mutationFn: () => startInvestigation(incident.id, payloadOf(draft)),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: hs.investigationStarted });
      refresh(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const save = useMutation({
    mutationFn: () => saveInvestigation(incident.id, payloadOf(draft)),
    onSuccess: (saved) => {
      setError("");
      notifications.show({ color: "green", message: hs.investigationSaved });
      refresh(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const can = (status: Incident["status"]) => incident.allowed_transitions.includes(status);

  return (
    <Stack>
      <Anchor component={Link} to={`${HSE_BASE}/olaylar`} size="sm">
        <Group gap={4}>
          <IconArrowLeft size={14} />
          {hs.tabs.incidents}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Group>
          <Title order={2}>{hs.incidentTitle(incident.number)}</Title>
          <IncidentStatusBadge status={incident.status} />
          <SeverityBadge severity={incident.severity} />
        </Group>
        {manager && open && (
          <Group gap="xs">
            {can("INVESTIGATING") && (
              <Button
                size="md"
                leftSection={<IconSearch size={18} />}
                loading={investigate.isPending}
                onClick={() => investigate.mutate()}
              >
                {hs.investigate}
              </Button>
            )}
            {can("CLOSED") && (
              <Button
                size="md"
                color="green"
                leftSection={<IconCheck size={18} />}
                onClick={() => setClosing(true)}
              >
                {hs.closeIncident}
              </Button>
            )}
            {can("CANCELLED") && (
              <Button
                size="md"
                color="red"
                variant="light"
                leftSection={<IconX size={18} />}
                onClick={() => setCancelling(true)}
              >
                {hs.cancelIncident}
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
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }}>
          <Info label={hs.incidentTypeLabel}>
            <Text size="sm" fw={600}>
              {incident.incident_type_display}
            </Text>
          </Info>
          <Info label={hs.occurredAt}>
            <Text size="sm">{formatDateTime(incident.occurred_at)}</Text>
          </Info>
          <Info label={hs.place}>
            <Text size="sm">{incident.place}</Text>
          </Info>
          {incident.location_code && (
            <Info label={hs.location}>
              <Text size="sm">{incident.location_code}</Text>
            </Info>
          )}
          {incident.equipment_code && (
            <Info label={hs.equipment}>
              <Text size="sm">{incident.equipment_code}</Text>
            </Info>
          )}
          <Info label={hs.injury}>
            {incident.injury ? (
              <Badge color="red" variant="light">
                {incident.injured_person ? `${hs.yes} · ${incident.injured_person}` : hs.yes}
              </Badge>
            ) : (
              <Text size="sm">{hs.no}</Text>
            )}
          </Info>
          <Info label={hs.reportedBy}>
            <Text size="sm">
              {`${incident.created_by_name ?? ""} · ${formatDateTime(incident.created_at)}`}
            </Text>
          </Info>
          {incident.status === "CANCELLED" && (
            <Info label={hs.cancelReason}>
              <Text size="sm">{incident.cancel_reason}</Text>
            </Info>
          )}
        </SimpleGrid>
        <Stack gap={0} mt="sm">
          <TextBlock label={hs.description} value={incident.description} />
        </Stack>
      </Paper>

      <Stack gap="xs">
        <Title order={4}>{hs.investigation}</Title>
        {manager && open ? (
          <Paper withBorder p="md" radius="md" data-testid="incident-investigation">
            <Stack>
              <InvestigationFields draft={draft} onChange={setDraft} />
              {incident.status === "INVESTIGATING" && (
                <Group justify="flex-end">
                  <Button variant="light" loading={save.isPending} onClick={() => save.mutate()}>
                    {hs.saveInvestigation}
                  </Button>
                </Group>
              )}
            </Stack>
          </Paper>
        ) : incident.root_cause || incident.corrective_action || incident.closed_note ? (
          <Paper withBorder p="md" radius="md">
            <Stack gap="sm">
              <TextBlock label={hs.rootCause} value={incident.root_cause} />
              <TextBlock label={hs.correctiveAction} value={incident.corrective_action} />
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                {incident.action_owner && (
                  <Info label={hs.actionOwner}>
                    <Text size="sm">{incident.action_owner}</Text>
                  </Info>
                )}
                {incident.action_due && (
                  <Info label={hs.actionDue}>
                    <Text size="sm">{formatDate(incident.action_due)}</Text>
                  </Info>
                )}
              </SimpleGrid>
              <TextBlock label={hs.closedNote} value={incident.closed_note} />
            </Stack>
          </Paper>
        ) : (
          <Text size="sm" c="dimmed">
            {hs.noInvestigation}
          </Text>
        )}
      </Stack>

      <AttachmentPanel
        contentType={CONTENT_TYPE}
        objectId={incident.id}
        defaultKind="PHOTO"
        title={hs.attachmentsTitle}
      />

      {closing && (
        <CloseModal
          incident={incident}
          draft={draft}
          onClose={() => setClosing(false)}
          onDone={(saved) => {
            setClosing(false);
            refresh(saved);
          }}
        />
      )}
      <CancelModal
        opened={cancelling}
        cancel={(reason) => cancelIncident(incident.id, reason)}
        onClose={() => setCancelling(false)}
        onDone={(saved) => {
          setCancelling(false);
          refresh(saved);
        }}
      />
    </Stack>
  );
}

/** Olay / kaza kaydı (`OL-`): bildiren ve yönetim görür; yönetim incelemeye alır, kök neden ve
 * düzeltici faaliyetle kapatır ya da iptal eder. Ekler ve yorumlar kayda bağlıdır. */
export function IncidentPage() {
  const incidentId = Number(useParams().incidentId);
  const query = useQuery({
    queryKey: ["hse", "incident", incidentId],
    queryFn: () => getIncident(incidentId),
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
        <IncidentView key={query.data.id} incident={query.data} />
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 4 }}>
        <RecordPanel contentType={CONTENT_TYPE} objectId={query.data.id} />
      </Grid.Col>
    </Grid>
  );
}
