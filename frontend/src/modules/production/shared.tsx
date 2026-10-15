import { Alert, Badge, Button, Group, Modal, Stack, Text, Textarea } from "@mantine/core";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import type { BatchStatus, LineState, OrderStatus } from "../../api/production";
import { ct } from "../common/strings";
import { BATCH_STATUS_COLOR, LINE_STATE_COLOR, ORDER_STATUS_COLOR } from "./config";
import { pt } from "./strings";

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  return (
    <Badge color={ORDER_STATUS_COLOR[status]} variant="light">
      {pt.orderStatus[status]}
    </Badge>
  );
}

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
  return (
    <Badge color={BATCH_STATUS_COLOR[status]} variant="light">
      {pt.batchStatus[status]}
    </Badge>
  );
}

export function LineStateBadge({ state }: { state: LineState }) {
  return (
    <Badge color={LINE_STATE_COLOR[state]} variant={state === "pending" ? "outline" : "filled"}>
      {pt.lineState[state]}
    </Badge>
  );
}

interface ReasonModalProps<T> {
  opened: boolean;
  title: string;
  hint?: string;
  label: string;
  confirmLabel: string;
  submit: (reason: string) => Promise<T>;
  onClose: () => void;
  onDone: (result: T) => void;
}

/** Nedeni zorunlu işlem (iptal): belge silinmez, neden denetim günlüğüne yazılır. */
export function ReasonModal<T>({
  opened,
  title,
  hint,
  label,
  confirmLabel,
  submit,
  onClose,
  onDone,
}: ReasonModalProps<T>) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => submit(reason.trim()),
    onSuccess: (result) => {
      setReason("");
      setError("");
      onDone(result);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  return (
    <Modal opened={opened} onClose={onClose} title={title}>
      <Stack>
        {hint && (
          <Text size="sm" c="dimmed">
            {hint}
          </Text>
        )}
        <Textarea
          label={label}
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
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
