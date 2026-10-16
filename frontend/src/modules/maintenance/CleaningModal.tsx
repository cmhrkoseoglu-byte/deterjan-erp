import { Alert, Button, Group, Modal, Stack, Text, TextInput, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { recordCleaning, type WorkOrder } from "../../api/maintenance";
import { cleanItems, equipmentLabel, useEquipmentOptions } from "./options";
import { ChecklistEditor } from "./shared";
import { mt } from "./strings";

/** Tank temizliği kaydı (tablette tek ekran): ürün değişimi temizliği kuralını karşılar. Kayıt
 * tamamlanmış bir temizlik iş emri olarak açılır. */
export function CleaningModal({
  equipmentId,
  onClose,
  onSaved,
}: {
  equipmentId: number;
  onClose: () => void;
  onSaved?: (order: WorkOrder) => void;
}) {
  const queryClient = useQueryClient();
  const equipment = useEquipmentOptions();
  const tank = (equipment.data ?? []).find((row) => row.id === equipmentId);
  const [workDone, setWorkDone] = useState("");
  const [items, setItems] = useState<string[]>([]);
  const [duration, setDuration] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      recordCleaning({
        equipment: equipmentId,
        work_done: workDone.trim(),
        checklist: cleanItems(items),
        duration_minutes: duration.trim() ? Number(duration) : null,
      }),
    onSuccess: (order) => {
      notifications.show({ color: "green", message: mt.cleaningSaved(order.number) });
      void queryClient.invalidateQueries({ queryKey: ["maintenance"] });
      onSaved?.(order);
      onClose();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  const durationInvalid = duration.trim() !== "" && !/^\d+$/.test(duration.trim());
  return (
    <Modal opened onClose={onClose} title={mt.cleaningTitle} size="lg">
      <Stack>
        {tank && (
          <Text fw={600} size="lg">
            {equipmentLabel(tank)}
          </Text>
        )}
        <Textarea
          label={mt.workDone}
          withAsterisk
          autosize
          minRows={3}
          size="md"
          value={workDone}
          onChange={(event) => setWorkDone(event.currentTarget.value)}
        />
        <ChecklistEditor items={items} onChange={setItems} description={mt.cleaningChecklistHint} />
        <TextInput
          label={mt.duration}
          inputMode="numeric"
          size="md"
          w={200}
          value={duration}
          error={durationInvalid || undefined}
          onChange={(event) => setDuration(event.currentTarget.value)}
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
            size="md"
            disabled={!workDone.trim() || durationInvalid}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mt.save}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
