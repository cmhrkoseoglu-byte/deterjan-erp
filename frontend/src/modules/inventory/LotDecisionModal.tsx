import { Alert, Button, Group, Modal, Select, Stack, Text, Textarea } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getErrorMessage } from "../../api/client";
import { blockLot, releaseLot, type Lot, type LotDetail } from "../../api/inventory";
import { ct } from "../common/strings";
import { idOrNull, useLocations } from "./options";
import { it } from "./strings";

export type LotDecision = "release" | "block";

interface Props {
  lot: Lot | null;
  decision: LotDecision | null;
  /**
   * Lot karantina lokasyonunda stoklu mu? `true`: hedef lokasyon zorunlu, `false`: sorulmaz,
   * bilinmiyorsa (liste ekranı) sorulur; karantinada stok varsa backend zorunlu tutar.
   */
  needsTarget?: boolean;
  onClose: () => void;
  onDone: (lot: LotDetail) => void;
}

/**
 * Lot durumu, kalite kararı dışında: laboratuvar bloke eder; admin gerekçeyle elle serbest
 * bırakır (Karar D-5, denetim günlüğüne yazılır). Olağan serbest bırakma ve ret numune kararıyla.
 */
export function LotDecisionModal({ lot, decision, needsTarget, onClose, onDone }: Props) {
  const [note, setNote] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState("");
  const locations = useLocations();

  useEffect(() => {
    setNote("");
    setTarget(null);
    setError("");
  }, [lot, decision]);

  const mutation = useMutation({
    mutationFn: () => {
      if (decision === "release") return releaseLot(lot!.id, note, idOrNull(target));
      return blockLot(lot!.id, note);
    },
    onSuccess: (result) => {
      notifications.show({ color: "green", message: it.decided });
      onDone(result);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });

  if (!lot || !decision) return null;
  const title = decision === "release" ? it.releaseTitle(lot.lot_no) : it.blockTitle(lot.lot_no);
  const targets = (locations.data ?? []).filter((option) => option.type !== "QUARANTINE");
  const askTarget = decision === "release" && needsTarget !== false;
  const canSubmit = note.trim() !== "" && (!(askTarget && needsTarget) || Boolean(target));

  return (
    <Modal opened onClose={onClose} title={title}>
      <Stack>
        <Text size="sm">{`${lot.material_code} - ${lot.material_name}`}</Text>
        {decision === "release" && (
          <Alert color="orange" variant="light">
            {it.manualReleaseHint}
          </Alert>
        )}
        {askTarget && (
          <Select
            label={it.releaseTarget}
            description={it.releaseTargetHint}
            withAsterisk={needsTarget === true}
            clearable
            searchable
            data={targets}
            value={target}
            onChange={setTarget}
            nothingFoundMessage="Bulunamadı"
          />
        )}
        <Textarea
          label={it.reasonRequired}
          withAsterisk
          autosize
          minRows={2}
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
            color={decision === "release" ? "green" : "red"}
            disabled={!canSubmit}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {decision === "release" ? it.release : it.block}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
