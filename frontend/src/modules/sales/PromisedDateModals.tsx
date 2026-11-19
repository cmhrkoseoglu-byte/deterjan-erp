import { Alert, Button, Group, Modal, Stack, Text, TextInput, Textarea } from "@mantine/core";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { changePromisedDate, type SalesOrderDetail } from "../../api/sales";
import { ct } from "../common/strings";
import { st } from "./strings";

/** Onay penceresi: termin onayda zorunludur (docs/plan/musteri-siparis-takibi.md §3.1). */
export function ConfirmOrderModal({
  initialDate,
  loading,
  onConfirm,
  onClose,
}: {
  initialDate: string;
  loading: boolean;
  onConfirm: (promisedDate: string) => void;
  onClose: () => void;
}) {
  const [date, setDate] = useState(initialDate);
  return (
    <Modal opened onClose={onClose} title={ct.confirmTitle}>
      <Stack>
        <Text size="sm">{st.confirmQuestion}</Text>
        <TextInput
          label={st.promisedDate}
          description={st.promisedDateHint}
          type="date"
          withAsterisk
          value={date}
          onChange={(event) => setDate(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button color="green" loading={loading} disabled={!date} onClick={() => onConfirm(date)}>
            {st.confirm}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Onaylı siparişin terminini gerekçeyle değiştirir. */
export function ChangePromisedDateModal({
  order,
  onClose,
  onDone,
}: {
  order: SalesOrderDetail;
  onClose: () => void;
  onDone: (saved: SalesOrderDetail) => void;
}) {
  const [date, setDate] = useState(order.promised_date ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const save = useMutation({
    mutationFn: () => changePromisedDate(order.id, date, reason.trim()),
    onSuccess: onDone,
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={st.changePromisedDate}>
      <Stack>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <TextInput
          label={st.promisedDate}
          type="date"
          withAsterisk
          value={date}
          onChange={(event) => setDate(event.currentTarget.value)}
        />
        <Textarea
          label={st.reason}
          description={st.promisedDateReasonHint}
          withAsterisk
          autosize
          minRows={2}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {ct.cancel}
          </Button>
          <Button
            loading={save.isPending}
            disabled={!date || !reason.trim()}
            onClick={() => save.mutate()}
          >
            {st.changePromisedDate}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
