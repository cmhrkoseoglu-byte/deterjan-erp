import { Badge, Group, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";
import type { DocumentStatus, LotStatus } from "../../api/inventory";
import { formatDate, formatNumber } from "../../i18n/format";
import { LOT_STATUS_COLOR } from "./config";
import { it } from "./strings";

export function LotStatusBadge({ status }: { status: LotStatus }) {
  return (
    <Badge color={LOT_STATUS_COLOR[status]} variant="light">
      {it.lotStatus[status]}
    </Badge>
  );
}

const DOC_COLOR: Record<DocumentStatus, string> = {
  DRAFT: "blue",
  POSTED: "green",
  CANCELLED: "gray",
};

export function DocStatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <Badge color={DOC_COLOR[status]} variant="light">
      {it.docStatus[status]}
    </Badge>
  );
}

/** Miktar + birim: "1.250,5 KG". */
export function Qty({ value, unit }: { value: string | null | undefined; unit?: string }) {
  return (
    <Text span size="sm" style={{ whiteSpace: "nowrap" }}>
      {formatNumber(value)} {unit}
    </Text>
  );
}

/** SKT; geçmişse kırmızı. */
export function ExpiryText({ date, expired }: { date: string | null; expired?: boolean }) {
  if (!date) return null;
  return (
    <Text span size="sm" c={expired ? "red" : undefined} fw={expired ? 600 : undefined}>
      {formatDate(date)}
    </Text>
  );
}

export function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Group gap={4} mih={22}>
        {children || <Text size="sm">—</Text>}
      </Group>
    </Stack>
  );
}
