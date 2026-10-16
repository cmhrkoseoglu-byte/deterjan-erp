import { Alert, Badge, Group, Progress, Stack, Text, Tooltip } from "@mantine/core";
import type {
  HazardClass,
  IncidentStatus,
  SdsState,
  Severity,
  SignalWord,
  StorageUtilisation,
} from "../../api/hse";
import { getErrorMessage } from "../../api/client";
import { HazardIcon } from "../../components/hazard/HazardIcon";
import { formatNumber } from "../../i18n/format";
import { INCIDENT_STATUS_COLOR, SDS_STATE_COLOR, SEVERITY_COLOR } from "./config";
import { hs } from "./strings";

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert color="red" variant="light">
      {typeof error === "string" ? error : getErrorMessage(error)}
    </Alert>
  );
}

export function IncidentStatusBadge({ status }: { status: IncidentStatus }) {
  return (
    <Badge color={INCIDENT_STATUS_COLOR[status]} variant="light">
      {hs.incidentStatus[status]}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge color={SEVERITY_COLOR[severity]} variant="outline">
      {hs.severity[severity]}
    </Badge>
  );
}

export function SdsStateBadge({ status, label }: { status: SdsState; label?: string }) {
  return (
    <Badge color={SDS_STATE_COLOR[status]} variant="light" data-status={status}>
      {label || status}
    </Badge>
  );
}

/** GHS piktogram kodu rozeti (görsel dosyası yok; ad ipucunda). */
export function PictogramBadge({ code }: { code: HazardClass }) {
  return (
    <Tooltip label={hs.hazardClass[code]} withArrow>
      <Badge color="red" variant="outline" radius="sm" data-testid="ghs-badge">
        {code}
      </Badge>
    </Tooltip>
  );
}

export function PictogramBadges({ codes }: { codes: readonly HazardClass[] }) {
  if (codes.length === 0) return null;
  return (
    <Group gap={4} wrap="wrap">
      <HazardIcon />
      {codes.map((code) => (
        <PictogramBadge key={code} code={code} />
      ))}
    </Group>
  );
}

export function SignalWordBadge({ word }: { word: SignalWord | "" }) {
  if (!word) return null;
  return (
    <Badge color={word === "DANGER" ? "red" : "orange"} variant="filled">
      {hs.signalWord[word]}
    </Badge>
  );
}

/** Depolama limiti doluluğu: yüzde çubuğu; limit aşıldıysa kırmızı. */
export function UtilisationBar({ row }: { row: StorageUtilisation }) {
  const pct = Number(row.pct);
  const color = row.exceeded ? "red" : pct >= 80 ? "orange" : "teal";
  return (
    <Stack gap={4} data-testid={`utilisation-${row.limit_id}`} data-exceeded={row.exceeded}>
      <Group justify="space-between" gap="xs">
        <Text size="sm" fw={500}>
          {`${row.location_code} - ${row.location_name} · ${row.hazard_class} ${row.hazard_class_display}`}
        </Text>
        <Group gap="xs">
          {row.exceeded && (
            <Badge color="red" variant="filled">
              {hs.exceeded}
            </Badge>
          )}
          <Text size="sm" c={row.exceeded ? "red" : undefined} fw={row.exceeded ? 700 : undefined}>
            {`${formatNumber(row.quantity_kg)} / ${formatNumber(row.limit_kg)} kg (%${formatNumber(row.pct, 0)})`}
          </Text>
        </Group>
      </Group>
      <Progress
        value={Math.min(pct, 100)}
        color={color}
        size="lg"
        aria-label={`${row.location_code} ${row.hazard_class}`}
        data-color={color}
      />
    </Stack>
  );
}
