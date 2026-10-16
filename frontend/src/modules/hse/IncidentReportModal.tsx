import {
  Button,
  Checkbox,
  Group,
  Modal,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertOctagon } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { reportIncident, type Incident, type IncidentType, type Severity } from "../../api/hse";
import { idOrNull, useLocations } from "../inventory/options";
import { equipmentLabel, useEquipmentOptions } from "../maintenance/options";
import { INCIDENT_TYPES, SEVERITIES } from "./config";
import { ErrorAlert } from "./shared";
import { hs } from "./strings";

/** Şimdiki yerel zaman, `datetime-local` biçiminde ("2026-10-16T14:30"). */
function nowLocal(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
}

/** Olay / ramak kala bildirimi: her rol açar (backend INCIDENT_REPORT_ROLES = tüm roller). */
export function IncidentReportModal({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved?: (incident: Incident) => void;
}) {
  const queryClient = useQueryClient();
  const locations = useLocations();
  const equipment = useEquipmentOptions();
  const [draft, setDraft] = useState({
    incident_type: null as string | null,
    occurred_at: nowLocal(),
    place: "",
    location: null as string | null,
    equipment: null as string | null,
    description: "",
    injury: false,
    injured_person: "",
    severity: "LOW" as Severity,
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      reportIncident({
        incident_type: draft.incident_type as IncidentType,
        occurred_at: new Date(draft.occurred_at || nowLocal()).toISOString(),
        place: draft.place.trim(),
        location: idOrNull(draft.location),
        equipment: idOrNull(draft.equipment),
        description: draft.description.trim(),
        injury: draft.injury,
        injured_person: draft.injury ? draft.injured_person.trim() : "",
        severity: draft.severity,
      }),
    onSuccess: (incident) => {
      notifications.show({ color: "green", message: hs.reported(incident.number) });
      void queryClient.invalidateQueries({ queryKey: ["hse"] });
      void queryClient.invalidateQueries({ queryKey: ["workflow"] });
      onSaved?.(incident);
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const ready = Boolean(draft.incident_type) && draft.description.trim() !== "";
  return (
    <Modal opened onClose={onClose} title={hs.reportTitle} size="lg">
      <Stack>
        <Text size="sm" c="dimmed">
          {hs.reportIntro}
        </Text>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label={hs.incidentTypeLabel}
            withAsterisk
            size="md"
            data={INCIDENT_TYPES.map((value) => ({ value, label: hs.incidentType[value] }))}
            value={draft.incident_type}
            onChange={(value) => setDraft({ ...draft, incident_type: value })}
          />
          <TextInput
            label={hs.occurredAt}
            withAsterisk
            type="datetime-local"
            size="md"
            value={draft.occurred_at}
            onChange={(event) => setDraft({ ...draft, occurred_at: event.currentTarget.value })}
          />
        </SimpleGrid>
        <TextInput
          label={hs.place}
          placeholder={hs.placeHint}
          size="md"
          value={draft.place}
          onChange={(event) => setDraft({ ...draft, place: event.currentTarget.value })}
        />
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label={hs.location}
            clearable
            searchable
            data={locations.data ?? []}
            value={draft.location}
            onChange={(value) => setDraft({ ...draft, location: value })}
            nothingFoundMessage={hs.notFound}
          />
          <Select
            label={hs.equipment}
            clearable
            searchable
            data={(equipment.data ?? []).map((row) => ({
              value: String(row.id),
              label: equipmentLabel(row),
            }))}
            value={draft.equipment}
            onChange={(value) => setDraft({ ...draft, equipment: value })}
            nothingFoundMessage={hs.notFound}
          />
        </SimpleGrid>
        <Textarea
          label={hs.description}
          withAsterisk
          autosize
          minRows={3}
          size="md"
          value={draft.description}
          onChange={(event) => setDraft({ ...draft, description: event.currentTarget.value })}
        />
        <Checkbox
          size="md"
          label={hs.injury}
          checked={draft.injury}
          onChange={(event) => setDraft({ ...draft, injury: event.currentTarget.checked })}
        />
        {draft.injury && (
          <TextInput
            label={hs.injuredPerson}
            size="md"
            value={draft.injured_person}
            onChange={(event) => setDraft({ ...draft, injured_person: event.currentTarget.value })}
          />
        )}
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {hs.severityLabel}
          </Text>
          <SegmentedControl
            aria-label={hs.severityLabel}
            data={SEVERITIES.map((value) => ({ value, label: hs.severity[value] }))}
            value={draft.severity}
            onChange={(value) => setDraft({ ...draft, severity: value as Severity })}
          />
        </Stack>
        <ErrorAlert error={error} />
        <Group justify="flex-end">
          <Button variant="default" size="md" onClick={onClose}>
            {hs.cancel}
          </Button>
          <Button
            color="red"
            size="md"
            disabled={!ready}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {hs.send}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** "Olay bildir" düğmesi: her rol olay / ramak kala bildirebilir. */
export function IncidentReportButton({ onSaved }: { onSaved?: (incident: Incident) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        color="red"
        variant="light"
        size="md"
        leftSection={<IconAlertOctagon size={18} />}
        onClick={() => setOpen(true)}
      >
        {hs.reportIncident}
      </Button>
      {open && <IncidentReportModal onClose={() => setOpen(false)} onSaved={onSaved} />}
    </>
  );
}
