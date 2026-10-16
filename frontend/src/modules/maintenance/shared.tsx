import { ActionIcon, Badge, Button, Group, Stack, TextInput } from "@mantine/core";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import type { CalibrationState, MaintenanceKind, WorkOrderStatus } from "../../api/maintenance";
import { CALIBRATION_COLOR, KIND_COLOR, WORK_ORDER_STATUS_COLOR } from "./config";
import { mt } from "./strings";

export function WorkOrderStatusBadge({ status }: { status: WorkOrderStatus }) {
  return (
    <Badge color={WORK_ORDER_STATUS_COLOR[status]} variant="light">
      {mt.status[status]}
    </Badge>
  );
}

export function KindBadge({ kind }: { kind: MaintenanceKind }) {
  return (
    <Badge color={KIND_COLOR[kind]} variant="outline">
      {mt.kind[kind]}
    </Badge>
  );
}

export function CalibrationBadge({ status, label }: { status: CalibrationState; label: string }) {
  return (
    <Badge color={CALIBRATION_COLOR[status]} variant="light" data-status={status}>
      {label}
    </Badge>
  );
}

/** Kontrol listesi maddeleri düzenleyicisi (metin satırı ekle / kaldır). */
export function ChecklistEditor({
  items,
  onChange,
  label = mt.checklist,
  description,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  label?: string;
  description?: string;
}) {
  return (
    <Stack gap="xs" data-testid="checklist-editor">
      <Group justify="space-between">
        <Stack gap={0}>
          <span style={{ fontSize: "var(--mantine-font-size-sm)", fontWeight: 500 }}>{label}</span>
          {description && (
            <span style={{ fontSize: "var(--mantine-font-size-xs)", opacity: 0.7 }}>
              {description}
            </span>
          )}
        </Stack>
        <Button
          size="compact-sm"
          variant="light"
          leftSection={<IconPlus size={14} />}
          onClick={() => onChange([...items, ""])}
        >
          {mt.addChecklistItem}
        </Button>
      </Group>
      {items.map((item, index) => (
        <Group key={index} gap="xs" wrap="nowrap">
          <TextInput
            style={{ flex: 1 }}
            aria-label={`${mt.checklistItem} ${index + 1}`}
            placeholder={`${mt.checklistItem} ${index + 1}`}
            value={item}
            onChange={(event) => {
              const value = event.currentTarget.value;
              onChange(items.map((row, i) => (i === index ? value : row)));
            }}
          />
          <ActionIcon
            variant="subtle"
            color="red"
            aria-label={mt.removeItem}
            onClick={() => onChange(items.filter((_, i) => i !== index))}
          >
            <IconTrash size={16} />
          </ActionIcon>
        </Group>
      ))}
    </Stack>
  );
}
