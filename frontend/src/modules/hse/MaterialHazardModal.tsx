import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  MultiSelect,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  getMaterialHazard,
  listStatements,
  saveMaterialHazard,
  type MaterialHazard,
  type SignalWord,
} from "../../api/hse";
import { useAuth } from "../../auth/AuthContext";
import { hasAnyRole } from "../../auth/roles";
import { HAZARD_CLASSES, HAZARD_ROLES } from "./config";
import { ErrorAlert, PictogramBadges, SignalWordBadge } from "./shared";
import { hs } from "./strings";

function useStatementOptions(enabled: boolean) {
  return useQuery({
    queryKey: ["hse", "statements", "options"],
    staleTime: 60_000,
    enabled,
    queryFn: async () => (await listStatements({ is_active: true, page_size: 500 })).results,
  });
}

/** Malzemenin tehlike bilgisi (salt okunur görünüm). */
export function HazardSummary({ hazard }: { hazard: MaterialHazard }) {
  if (hazard.pictograms.length === 0 && hazard.statement_rows.length === 0 && !hazard.signal_word)
    return (
      <Text size="sm" c="dimmed">
        {hs.noHazard}
      </Text>
    );
  return (
    <Stack gap="sm" data-testid="hazard-summary">
      <Group gap="sm">
        <PictogramBadges codes={hazard.pictograms} />
        <SignalWordBadge word={hazard.signal_word} />
      </Group>
      {hazard.pictogram_labels.length > 0 && (
        <Text size="sm">{hazard.pictogram_labels.join(", ")}</Text>
      )}
      {hazard.statement_rows.length > 0 && (
        <Table fz="sm" withRowBorders={false}>
          <Table.Tbody>
            {hazard.statement_rows.map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td w={80} fw={600}>
                  {row.code}
                </Table.Td>
                <Table.Td>{row.text}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
      {hazard.note && (
        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
          {hazard.note}
        </Text>
      )}
    </Stack>
  );
}

function HazardForm({
  hazard,
  onCancel,
  onSaved,
}: {
  hazard: MaterialHazard;
  onCancel: () => void;
  onSaved: (saved: MaterialHazard) => void;
}) {
  const statements = useStatementOptions(true);
  const [pictograms, setPictograms] = useState<string[]>(hazard.pictograms);
  const [signalWord, setSignalWord] = useState<string>(hazard.signal_word);
  const [selected, setSelected] = useState<string[]>(hazard.statements.map(String));
  const [note, setNote] = useState(hazard.note);
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      saveMaterialHazard(hazard.material, {
        pictograms: HAZARD_CLASSES.filter((code) => pictograms.includes(code)),
        signal_word: signalWord as SignalWord | "",
        statements: selected.map(Number),
        note: note.trim(),
      }),
    onSuccess: (saved) => {
      notifications.show({ color: "green", message: hs.hazardSaved });
      onSaved(saved);
    },
    onError: (err) => setError(getErrorMessage(err)),
  });
  // Pasif ifade seçiliyse de görünsün diye mevcut satırlar seçeneklere eklenir.
  const options = new Map<string, string>();
  for (const row of hazard.statement_rows) options.set(String(row.id), `${row.code} ${row.text}`);
  for (const row of statements.data ?? []) options.set(String(row.id), `${row.code} ${row.text}`);
  return (
    <Stack>
      <Checkbox.Group label={hs.pictograms} value={pictograms} onChange={setPictograms}>
        <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }} mt="xs">
          {HAZARD_CLASSES.map((code) => (
            <Checkbox key={code} value={code} label={`${code} ${hs.hazardClass[code]}`} />
          ))}
        </SimpleGrid>
      </Checkbox.Group>
      <Select
        label={hs.signalWordLabel}
        data={[
          { value: "", label: hs.noSignalWord },
          { value: "DANGER", label: hs.signalWord.DANGER },
          { value: "WARNING", label: hs.signalWord.WARNING },
        ]}
        allowDeselect={false}
        value={signalWord}
        onChange={(value) => setSignalWord(value ?? "")}
        w={240}
      />
      <MultiSelect
        label={hs.statements}
        description={hs.statementsHint}
        searchable
        data={[...options].map(([value, label]) => ({ value, label }))}
        value={selected}
        onChange={setSelected}
        nothingFoundMessage={hs.notFound}
      />
      <Textarea
        label={hs.note}
        autosize
        minRows={2}
        value={note}
        onChange={(event) => setNote(event.currentTarget.value)}
      />
      <ErrorAlert error={error} />
      <Group justify="flex-end">
        <Button variant="default" onClick={onCancel}>
          {hs.cancel}
        </Button>
        <Button loading={mutation.isPending} onClick={() => mutation.mutate()}>
          {hs.save}
        </Button>
      </Group>
    </Stack>
  );
}

/** Malzeme kartının "Tehlike" bilgisi: herkes görür; yönetim ve laboratuvar düzenler. */
export function MaterialHazardModal({
  materialId,
  title,
  onClose,
}: {
  materialId: number;
  title: string;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const writer = hasAnyRole(user, HAZARD_ROLES);
  const [editing, setEditing] = useState(false);
  const key = ["hse", "material-hazard", materialId];
  const query = useQuery({ queryKey: key, queryFn: () => getMaterialHazard(materialId) });
  return (
    <Modal opened onClose={onClose} title={hs.hazardTitle(title)} size="lg">
      {query.isLoading ? (
        <Loader />
      ) : query.error || !query.data ? (
        <ErrorAlert error={query.error} />
      ) : editing ? (
        <HazardForm
          hazard={query.data}
          onCancel={() => setEditing(false)}
          onSaved={(saved) => {
            queryClient.setQueryData(key, saved);
            void queryClient.invalidateQueries({ queryKey: ["hse"] });
            void queryClient.invalidateQueries({ queryKey: ["masterdata"] });
            setEditing(false);
          }}
        />
      ) : (
        <Stack>
          <Text size="xs" c="dimmed">
            {hs.hazardIntro}
          </Text>
          <HazardSummary hazard={query.data} />
          {!writer && (
            <Alert color="gray" variant="light">
              {hs.readOnly}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {hs.close}
            </Button>
            {writer && <Button onClick={() => setEditing(true)}>{hs.edit}</Button>}
          </Group>
        </Stack>
      )}
    </Modal>
  );
}

/** Ana veriler → malzemeler satırındaki "Tehlike bilgisi" düğmesi. */
export function MaterialHazardAction({ row }: { row: { id: number; code: string } }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Tooltip label={hs.hazardAction}>
        <ActionIcon
          variant="subtle"
          color="orange"
          aria-label={`${hs.hazardAction}: ${row.code}`}
          onClick={() => setOpen(true)}
        >
          <IconAlertTriangle size={16} />
        </ActionIcon>
      </Tooltip>
      {open && (
        <MaterialHazardModal materialId={row.id} title={row.code} onClose={() => setOpen(false)} />
      )}
    </>
  );
}
