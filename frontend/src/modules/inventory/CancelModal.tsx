import { Alert, Button, Group, Modal, Stack, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { ct } from "../common/strings";
import { it } from "./strings";

interface Props<T> {
  opened: boolean;
  cancel: (reason: string) => Promise<T>;
  onClose: () => void;
  onDone: (result: T) => void;
}

/** Taslak belgeyi nedeniyle iptal eder (belge silinmez, CLAUDE.md kural 6). */
export function CancelModal<T>({ opened, cancel, onClose, onDone }: Props<T>) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => cancel(reason.trim()),
    onSuccess: (result) => {
      notifications.show({ color: "green", message: it.cancelled });
      setReason("");
      setError("");
      onDone(result);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened={opened} onClose={onClose} title={it.cancelTitle}>
      <Stack>
        <Textarea
          label={it.cancelReason}
          withAsterisk
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
            color="red"
            disabled={!reason.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {it.cancelDoc}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
