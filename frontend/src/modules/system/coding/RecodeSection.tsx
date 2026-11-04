import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconInfoCircle } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../../api/client";
import {
  applyRecode,
  listRecodeRuns,
  previewRecode,
  previewRevert,
  revertRecode,
  type CodeMigrationRun,
  type CodeTypeRow,
} from "../../../api/coding";
import { formatDateTime } from "../../../i18n/format";
import { ConfirmModal } from "../../common/ConfirmModal";
import { cs } from "./strings";

const ACTION_COLORS = {
  keep: "gray",
  change: "blue",
  problem: "red",
  revert: "blue",
  skip: "gray",
};

/** Kod göçü: türü seç, önizle, notla uygula; uygulanan göçleri geri al. */
export function RecodeSection({ types }: { types: CodeTypeRow[] }) {
  const queryClient = useQueryClient();
  const options = types
    .filter((row) => row.kind === "master" && !row.free)
    .map((row) => ({ value: row.key, label: row.label }));
  const [key, setKey] = useState<string | null>(null);
  const [onlyChanges, setOnlyChanges] = useState(true);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [reverting, setReverting] = useState<CodeMigrationRun | null>(null);

  const preview = useQuery({
    queryKey: ["system", "coding", "recode", key],
    queryFn: () => previewRecode(key!),
    enabled: Boolean(key),
    staleTime: 0,
  });
  const runs = useQuery({
    queryKey: ["system", "coding", "runs"],
    queryFn: () => listRecodeRuns(),
  });

  const apply = useMutation({
    mutationFn: () => applyRecode(key!, preview.data!.checksum, note),
    onSuccess: (run) => {
      notifications.show({ color: "green", message: cs.migrationDone(run.count) });
      setConfirming(false);
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["system", "coding"] });
    },
    onError: (error) => {
      setConfirming(false);
      notifications.show({ color: "red", message: getErrorMessage(error) });
      void preview.refetch();
    },
  });

  const plan = preview.data;
  const rows = plan ? plan.rows.filter((row) => !onlyChanges || row.action !== "keep") : [];
  const label = options.find((option) => option.value === key)?.label ?? "";

  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{cs.migrationIntro}</Text>
      </Alert>
      <Group align="flex-end">
        <Select
          label={cs.migrationType}
          data={options}
          value={key}
          onChange={setKey}
          w={280}
          searchable
        />
        <Switch
          label={cs.onlyChanges}
          checked={onlyChanges}
          onChange={(event) => setOnlyChanges(event.currentTarget.checked)}
        />
      </Group>
      {preview.isFetching && <Loader size="sm" />}
      {preview.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(preview.error)}
        </Alert>
      )}
      {plan && !preview.isFetching && (
        <Stack gap="xs">
          <Text size="sm" fw={500}>
            {cs.migrationSummary(plan.change_count, plan.keep_count)}
          </Text>
          {!plan.active && (
            <Text size="sm" c="dimmed">
              {cs.migrationInactiveScheme}
            </Text>
          )}
          <Table.ScrollContainer minWidth={560}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{cs.colRecord}</Table.Th>
                  <Table.Th>{cs.colOld}</Table.Th>
                  <Table.Th>{cs.colNew}</Table.Th>
                  <Table.Th>{cs.colAction}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row) => (
                  <Table.Tr key={row.id}>
                    <Table.Td>
                      {row.label}
                      {!row.is_active && (
                        <Text span size="xs" c="dimmed">
                          {" "}
                          ({cs.inactiveRecord})
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ff="monospace">{row.old}</Table.Td>
                    <Table.Td ff="monospace">{row.new}</Table.Td>
                    <Table.Td>
                      <Badge color={ACTION_COLORS[row.action]} variant="light">
                        {cs.action[row.action]}
                      </Badge>
                      {row.problem && (
                        <Text size="xs" c="red">
                          {row.problem}
                        </Text>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {plan.change_count === 0 ? (
            <Text size="sm" c="dimmed">
              {cs.migrationNothing}
            </Text>
          ) : (
            <Stack gap="xs">
              <Alert color="orange" variant="light" icon={<IconAlertTriangle size={18} />}>
                <Text size="sm">{cs.migrationBackup}</Text>
              </Alert>
              <Textarea
                label={cs.migrationNote}
                withAsterisk
                autosize
                minRows={2}
                value={note}
                onChange={(event) => setNote(event.currentTarget.value)}
              />
              <Group justify="flex-end">
                <Button
                  disabled={!note.trim() || plan.problem_count > 0}
                  onClick={() => setConfirming(true)}
                >
                  {cs.migrationApply(plan.change_count)}
                </Button>
              </Group>
            </Stack>
          )}
        </Stack>
      )}

      <Title order={4} mt="md">
        {cs.runs}
      </Title>
      <RunsTable runs={runs.data?.results ?? []} loading={runs.isLoading} onRevert={setReverting} />

      <ConfirmModal
        opened={confirming}
        message={plan ? cs.migrationConfirm(plan.change_count, label) : ""}
        confirmLabel={plan ? cs.migrationApply(plan.change_count) : ""}
        loading={apply.isPending}
        onConfirm={() => apply.mutate()}
        onClose={() => setConfirming(false)}
      />
      <RevertModal run={reverting} onClose={() => setReverting(null)} />
    </Stack>
  );
}

function RunsTable({
  runs,
  loading,
  onRevert,
}: {
  runs: CodeMigrationRun[];
  loading: boolean;
  onRevert: (run: CodeMigrationRun) => void;
}) {
  if (loading) return <Loader size="sm" />;
  if (!runs.length) return <Text c="dimmed">{cs.runsEmpty}</Text>;
  return (
    <Table.ScrollContainer minWidth={640}>
      <Table striped>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{cs.colWhen}</Table.Th>
            <Table.Th>{cs.colType}</Table.Th>
            <Table.Th>{cs.colAction}</Table.Th>
            <Table.Th>{cs.colWho}</Table.Th>
            <Table.Th>{cs.colNote}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {runs.map((run) => (
            <Table.Tr key={run.id}>
              <Table.Td>{formatDateTime(run.created_at)}</Table.Td>
              <Table.Td>
                {run.label} ({cs.runTitle(run.id)})
              </Table.Td>
              <Table.Td>
                {cs.runKind[run.kind]} · {cs.runCount(run.count)}
                {run.reverted && (
                  <Badge ml="xs" color="gray" variant="light">
                    {cs.reverted}
                  </Badge>
                )}
              </Table.Td>
              <Table.Td>{run.created_by_name}</Table.Td>
              <Table.Td>
                <Text size="sm">{run.note}</Text>
              </Table.Td>
              <Table.Td>
                {run.kind === "apply" && !run.reverted && (
                  <Button size="xs" variant="light" color="orange" onClick={() => onRevert(run)}>
                    {cs.revert}
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function RevertModal({ run, onClose }: { run: CodeMigrationRun | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const preview = useQuery({
    queryKey: ["system", "coding", "revert", run?.id],
    queryFn: () => previewRevert(run!.id),
    enabled: Boolean(run),
    staleTime: 0,
  });
  const mutation = useMutation({
    mutationFn: () => revertRecode(run!.id, note),
    onSuccess: (revert) => {
      notifications.show({ color: "green", message: cs.revertDone(revert.count) });
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["system", "coding"] });
      onClose();
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });
  if (!run) return null;
  const data = preview.data;
  return (
    <Modal opened onClose={onClose} title={cs.revertTitle(run.id)} size="lg">
      <Stack>
        <Text size="sm">{cs.revertIntro}</Text>
        {preview.isLoading && <Loader size="sm" />}
        {data && (
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{cs.colRecord}</Table.Th>
                <Table.Th>{cs.colOld}</Table.Th>
                <Table.Th>{cs.colNew}</Table.Th>
                <Table.Th>{cs.colAction}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.rows.map((row) => (
                <Table.Tr key={row.id}>
                  <Table.Td>{row.label}</Table.Td>
                  <Table.Td ff="monospace">{row.old}</Table.Td>
                  <Table.Td ff="monospace">{row.current}</Table.Td>
                  <Table.Td>
                    <Badge color={ACTION_COLORS[row.action]} variant="light">
                      {cs.action[row.action]}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <Textarea
          label={cs.revertNote}
          withAsterisk
          autosize
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {cs.cancel}
          </Button>
          <Button
            color="orange"
            disabled={!note.trim() || !data?.revert_count}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {cs.revertApply(data?.revert_count ?? 0)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
