// Gerekçeyle kaldırma penceresi (bordro kalemi, devir, mali müşavir rakamı): kayıt silinmez,
// kaldırılır; neden zorunludur ve kayda geçer. İstek sürerken pencere kapanmaz.
import { Button, Group, Modal, Stack, Text, Textarea } from "@mantine/core";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorAlert } from "../costing/ReportTable";
import { pn } from "./strings";

export function ReasonModal({
  title,
  intro,
  confirmLabel,
  onConfirm,
  onDone,
  onClose,
}: {
  title: string;
  intro: string;
  confirmLabel: string;
  onConfirm: (reason: string) => Promise<unknown>;
  /** Başarıdan sonra (bildirim, yenileme); pencere ardından kapanır. */
  onDone: () => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const remove = useMutation({ mutationFn: () => onConfirm(reason.trim()) });
  const close = () => {
    if (!remove.isPending) onClose();
  };
  return (
    <Modal
      opened
      onClose={close}
      title={title}
      closeOnClickOutside={false}
      closeOnEscape={!remove.isPending}
      withCloseButton={!remove.isPending}
    >
      <Stack>
        <Text size="sm">{intro}</Text>
        <Textarea
          label={pn.removeReason}
          withAsterisk
          autosize
          minRows={2}
          maxLength={500}
          value={reason}
          disabled={remove.isPending}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        {remove.isError && <ErrorAlert error={remove.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close} disabled={remove.isPending}>
            {pn.cancel}
          </Button>
          <Button
            color="red"
            loading={remove.isPending}
            disabled={!reason.trim()}
            onClick={() =>
              remove.mutate(undefined, {
                onSuccess: () => {
                  onDone();
                  onClose();
                },
              })
            }
          >
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
