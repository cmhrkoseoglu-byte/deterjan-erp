import { Alert, Button, Checkbox, Group, Modal, Select, Stack, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { reportBreakdown, type WorkOrder } from "../../api/maintenance";
import { idOrNull } from "../inventory/options";
import { equipmentLabel, useEquipmentOptions } from "./options";
import { mt } from "./strings";

/** Arıza bildirimi penceresi: onarım iş emri açar, istenirse ekipmanın duruşunu başlatır. */
export function BreakdownModal({
  equipmentId,
  onClose,
  onSaved,
}: {
  equipmentId?: number;
  onClose: () => void;
  onSaved?: (order: WorkOrder) => void;
}) {
  const queryClient = useQueryClient();
  const equipment = useEquipmentOptions();
  const [draft, setDraft] = useState({
    equipment: equipmentId ? String(equipmentId) : null,
    description: "",
    stop: true,
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      reportBreakdown({
        equipment: idOrNull(draft.equipment)!,
        description: draft.description.trim(),
        stop_equipment: draft.stop,
      }),
    onSuccess: (order) => {
      notifications.show({ color: "green", message: mt.breakdownReported(order.number) });
      void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
      void queryClient.invalidateQueries({ queryKey: ["workflow"] });
      onSaved?.(order);
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={mt.breakdownTitle}>
      <Stack>
        <Select
          label={mt.equipment}
          withAsterisk
          searchable
          size="md"
          data={(equipment.data ?? []).map((row) => ({
            value: String(row.id),
            label: equipmentLabel(row),
          }))}
          value={draft.equipment}
          onChange={(value) => setDraft({ ...draft, equipment: value })}
          nothingFoundMessage={mt.notFound}
        />
        <Textarea
          label={mt.breakdownDescription}
          withAsterisk
          autosize
          minRows={3}
          size="md"
          value={draft.description}
          onChange={(event) => setDraft({ ...draft, description: event.currentTarget.value })}
        />
        <Checkbox
          size="md"
          label={mt.stopEquipment}
          checked={draft.stop}
          onChange={(event) => setDraft({ ...draft, stop: event.currentTarget.checked })}
        />
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button variant="default" size="md" onClick={onClose}>
            {mt.cancel}
          </Button>
          <Button
            color="red"
            size="md"
            disabled={!draft.equipment || !draft.description.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.send}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** "Arıza bildir" düğmesi: her rol arıza bildirebilir (backend BREAKDOWN_ROLES = tüm roller). */
export function BreakdownButton({ equipmentId }: { equipmentId?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        color="red"
        variant="light"
        size="md"
        leftSection={<IconAlertTriangle size={18} />}
        onClick={() => setOpen(true)}
      >
        {mt.reportBreakdown}
      </Button>
      {open && <BreakdownModal equipmentId={equipmentId} onClose={() => setOpen(false)} />}
    </>
  );
}
