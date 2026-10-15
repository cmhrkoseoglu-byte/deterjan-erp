import {
  Alert,
  Anchor,
  Button,
  Group,
  Modal,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconFlask, IconRecycle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import type { Lot } from "../../api/inventory";
import { createSample, listSamples, type SampleStage } from "../../api/quality";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { formatDateTime } from "../../i18n/format";
import { ct } from "../common/strings";
import { ORDER_ROLES, reworkOrderPath } from "../production/config";
import { LAB_ROLES, OPEN_SAMPLE_STATUSES, samplePath, STAGES } from "./config";
import { SampleStatusBadge } from "./shared";
import { qt } from "./strings";

const SAMPLEABLE = ["QUARANTINE", "BLOCKED"];

/** Lot detayındaki kalite bölümü: lotun numuneleri, numune açma ve yeniden işleme emri. */
export function LotQualitySection({ lot }: { lot: Lot }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [opening, setOpening] = useState(false);
  const samples = useQuery({
    queryKey: ["quality", "samples", { lot: lot.id }],
    queryFn: () => listSamples({ lot: lot.id, page_size: 100 }),
  });
  const rows = samples.data?.results ?? [];
  const hasOpen = rows.some((row) => OPEN_SAMPLE_STATUSES.includes(row.status));
  const canOpen = hasAnyRole(user, LAB_ROLES) && SAMPLEABLE.includes(lot.status) && !hasOpen;
  const canRework =
    hasAnyRole(user, ORDER_ROLES) && lot.status === "BLOCKED" && lot.material_type === "BULK";

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Title order={4}>{qt.lotQc}</Title>
        <Group gap="xs">
          {canRework && (
            <Button
              size="xs"
              variant="light"
              color="orange"
              leftSection={<IconRecycle size={14} />}
              onClick={() => navigate(reworkOrderPath(lot.id))}
            >
              {qt.reworkOrder}
            </Button>
          )}
          {canOpen && (
            <Button
              size="xs"
              variant="light"
              leftSection={<IconFlask size={14} />}
              onClick={() => setOpening(true)}
            >
              {qt.openSample}
            </Button>
          )}
        </Group>
      </Group>
      {rows.length === 0 ? (
        <Text size="sm" c="dimmed">
          {qt.lotNoSamples}
        </Text>
      ) : (
        <Paper withBorder radius="md">
          <Table fz="sm" data-testid="lot-samples">
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={row.id}>
                  <Table.Td>
                    <Anchor component={Link} to={samplePath(row.id)} size="sm">
                      {row.number}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>{qt.stage[row.stage]}</Table.Td>
                  <Table.Td>{row.specification_label ?? "—"}</Table.Td>
                  <Table.Td>{formatDateTime(row.decided_at ?? row.taken_at)}</Table.Td>
                  <Table.Td>
                    <SampleStatusBadge status={row.status} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      {opening && <OpenSampleModal lot={lot} onClose={() => setOpening(false)} />}
    </Stack>
  );
}

function OpenSampleModal({ lot, onClose }: { lot: Lot; onClose: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const raw = lot.material_type === "RAW" || lot.material_type === "PACKAGING";
  const [stage, setStage] = useState<string | null>(raw ? "INCOMING" : "FINAL");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () => createSample({ lot: lot.id, stage: stage as SampleStage, note: note.trim() }),
    onSuccess: (sample) => {
      notifications.show({ color: "green", message: qt.sampleOpened(sample.number) });
      void queryClient.invalidateQueries({ queryKey: ["quality"] });
      navigate(samplePath(sample.id));
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  return (
    <Modal opened onClose={onClose} title={`${qt.openSample}: ${lot.lot_no}`}>
      <Stack>
        <Select
          label={qt.stageLabel}
          data={STAGES.map((value) => ({ value, label: qt.stage[value] }))}
          value={stage}
          allowDeselect={false}
          onChange={setStage}
        />
        <Textarea
          label={qt.note}
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
          <Button loading={mutation.isPending} onClick={() => mutation.mutate()}>
            {qt.openSample}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
