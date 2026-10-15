import { Alert, Button, Group, Modal, Select, Stack, Textarea, TextInput } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../api/client";
import { transferLot, type LotDetail } from "../../api/inventory";
import { normalizeDecimal } from "../common/forms";
import { ct } from "../common/strings";
import { formatNumber } from "../../i18n/format";
import { idOrNull, useLocations } from "./options";
import { it } from "./strings";

interface Props {
  lot: LotDetail;
  opened: boolean;
  onClose: () => void;
  onDone: () => void;
}

/** Lotu lokasyonlar arasında taşır (depo). Kaynak, lotun stoklu olduğu lokasyonlardır. */
export function TransferModal({ lot, opened, onClose, onDone }: Props) {
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const locations = useLocations();

  useEffect(() => {
    if (!opened) return;
    const only = lot.balances.length === 1 ? lot.balances[0] : null;
    setFrom(only ? String(only.location) : null);
    setQuantity(only ? formatNumber(only.quantity).replace(/\./g, "") : "");
    setTo(null);
    setNote("");
    setError("");
  }, [opened, lot]);

  const mutation = useMutation({
    mutationFn: () =>
      transferLot({
        lot: lot.id,
        from_location: idOrNull(from)!,
        to_location: idOrNull(to)!,
        quantity: normalizeDecimal(quantity),
        note,
      }),
    onSuccess: () => {
      notifications.show({ color: "green", message: it.transferred });
      onDone();
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  const sources = lot.balances.map((row) => ({
    value: String(row.location),
    label: `${row.location_code} (${formatNumber(row.quantity)} ${lot.unit})`,
  }));
  const targets = (locations.data ?? []).filter((option) => option.value !== from);

  return (
    <Modal opened={opened} onClose={onClose} title={it.transferTitle(lot.lot_no)}>
      <Stack>
        <Select
          label={it.fromLocation}
          withAsterisk
          data={sources}
          value={from}
          onChange={setFrom}
        />
        <Select
          label={it.toLocation}
          withAsterisk
          searchable
          data={targets}
          value={to}
          onChange={setTo}
          nothingFoundMessage="Bulunamadı"
        />
        <TextInput
          label={`${it.quantity} (${lot.unit})`}
          withAsterisk
          inputMode="decimal"
          value={quantity}
          onChange={(event) => setQuantity(event.currentTarget.value)}
        />
        <Textarea
          label={it.noteOptional}
          autosize
          minRows={1}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
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
            disabled={!from || !to || !quantity.trim()}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {it.transfer}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
