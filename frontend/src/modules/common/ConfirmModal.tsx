import { Button, Group, Modal, Stack, Text } from "@mantine/core";
import { ct } from "./strings";

interface Props {
  opened: boolean;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

/** Geri alınabilir ama dikkat isteyen işlemler için onay penceresi (pasife alma, onay). */
export function ConfirmModal({
  opened,
  message,
  confirmLabel,
  danger,
  loading,
  onConfirm,
  onClose,
}: Props) {
  return (
    <Modal opened={opened} onClose={onClose} title={ct.confirmTitle}>
      <Stack>
        <Text size="sm">{message}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button color={danger ? "red" : undefined} loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
