import {
  Alert,
  Anchor,
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
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
import { fetchSystemStatus } from "../../../api/ops";
import { formatDateTime } from "../../../i18n/format";
import { ConfirmModal } from "../../common/ConfirmModal";
import { SYSTEM_BASE, TABS } from "../config";
import { cs } from "./strings";

const ACTION_COLORS = {
  keep: "gray",
  change: "blue",
  problem: "red",
  revert: "blue",
  skip: "gray",
};
const RUNS_KEY = ["system", "coding", "runs"] as const;
/** Göçten önce aranan başarılı yedeğin en büyük yaşı (24 saat). */
const BACKUP_MAX_AGE_MS = 24 * 60 * 60 * 1000;

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
          onChange={(value) => {
            // Not türe aittir; tür değişince yeniden yazılır.
            setKey(value);
            setNote("");
          }}
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
      {plan &&
        !preview.isFetching &&
        (plan.change_count === 0 && rows.length === 0 ? (
          <Text size="sm" c="dimmed">
            {cs.migrationNothing}
          </Text>
        ) : (
          <Stack gap="xs">
            <Text size="sm" fw={500}>
              {cs.migrationSummary(plan.change_count, plan.keep_count)}
            </Text>
            {!plan.active && (
              <Text size="sm" c="dimmed">
                {cs.migrationInactiveScheme}
              </Text>
            )}
            {rows.length > 0 && (
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
            )}
            {plan.change_count === 0 ? (
              <Text size="sm" c={plan.problem_count > 0 ? "red" : "dimmed"}>
                {plan.problem_count > 0 ? cs.migrationProblem : cs.migrationNothing}
              </Text>
            ) : (
              <Stack gap="xs">
                <BackupNotice />
                <Textarea
                  size="md"
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
        ))}

      <Title order={4} mt="md">
        {cs.runs}
      </Title>
      <MigrationRuns onRevert={setReverting} />

      <ConfirmModal
        opened={confirming}
        message={plan ? cs.migrationConfirm(plan.change_count, label) : ""}
        confirmLabel={plan ? cs.migrationApply(plan.change_count) : ""}
        loading={apply.isPending}
        onConfirm={() => apply.mutate()}
        onClose={() => setConfirming(false)}
      />
      {/* Her göç için yeni pencere: önceki göçe yazılıp vazgeçilen not taşınmaz. */}
      <RevertModal
        key={reverting?.id ?? "none"}
        run={reverting}
        onClose={() => setReverting(null)}
      />
    </Stack>
  );
}

/** Göçü uygulamadan önce son yedeğin zamanı ve durumu (Sistem durumu); son 24 saatte başarılı
 * yedek yoksa uyarı. Uygulamayı engellemez. */
function BackupNotice() {
  const status = useQuery({
    queryKey: ["ops", "status"],
    queryFn: fetchSystemStatus,
    staleTime: 60_000,
  });
  // Kayıtlar en yeniden eskiye gelir.
  const backups = (status.data?.runs ?? []).filter((run) => run.kind === "backup");
  const latest = backups[0];
  const recent = backups.some(
    (run) =>
      run.status === "ok" && Date.now() - new Date(run.finished_at).getTime() <= BACKUP_MAX_AGE_MS,
  );
  const stale = status.isSuccess && !recent;
  return (
    <Alert
      color={stale ? "red" : "orange"}
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      data-testid="migration-backup"
    >
      <Stack gap={4}>
        <Text size="sm">{cs.migrationBackup}</Text>
        {status.isLoading && <Loader size="xs" />}
        {status.isError && <Text size="sm">{cs.backupError(getErrorMessage(status.error))}</Text>}
        {status.isSuccess && (
          <Text size="sm">
            {latest
              ? cs.lastBackup(formatDateTime(latest.finished_at), latest.status_display)
              : cs.noBackup}
          </Text>
        )}
        {stale && (
          <Text size="sm" fw={600}>
            {cs.backupStale}
          </Text>
        )}
        <Anchor component={Link} to={`${SYSTEM_BASE}/${TABS.status}`} size="sm">
          {cs.backupLink}
        </Anchor>
      </Stack>
    </Alert>
  );
}

/** Uygulanan göçler ve geri almalar (Kod göçü ve Geçmiş). `onRevert` verilirse geri alınmamış
 * göçte "Geri al" düğmesi çıkar. */
export function MigrationRuns({ onRevert }: { onRevert?: (run: CodeMigrationRun) => void }) {
  const runs = useQuery({ queryKey: RUNS_KEY, queryFn: () => listRecodeRuns() });
  if (runs.isLoading) return <Loader size="sm" />;
  if (runs.isError) {
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(runs.error)}
      </Alert>
    );
  }
  const rows = runs.data?.results ?? [];
  if (!rows.length) return <Text c="dimmed">{cs.runsEmpty}</Text>;
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
            {onRevert && <Table.Th />}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((run) => (
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
              {onRevert && (
                <Table.Td>
                  {run.kind === "apply" && !run.reverted && (
                    <Button size="xs" variant="light" color="orange" onClick={() => onRevert(run)}>
                      {cs.revert}
                    </Button>
                  )}
                </Table.Td>
              )}
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
  const reverted = preview.data?.already_reverted ?? false;
  // Başka biri geri aldıysa liste de yenilenir ("Geri alındı" görünür).
  useEffect(() => {
    if (reverted) void queryClient.invalidateQueries({ queryKey: RUNS_KEY });
  }, [reverted, queryClient]);
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
        {preview.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(preview.error)}
          </Alert>
        )}
        {reverted && (
          <Alert color="gray" variant="light" icon={<IconInfoCircle size={18} />}>
            {cs.alreadyReverted}
          </Alert>
        )}
        {data && data.rows.length > 0 && (
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
        {!reverted && (
          <Textarea
            size="md"
            label={cs.revertNote}
            withAsterisk
            autosize
            minRows={2}
            value={note}
            onChange={(event) => setNote(event.currentTarget.value)}
          />
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {cs.cancel}
          </Button>
          <Button
            color="orange"
            disabled={reverted || !note.trim() || !data?.revert_count}
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
