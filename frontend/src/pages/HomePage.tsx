import {
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconArrowRight, IconCheck, IconHandGrab } from "@tabler/icons-react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../api/client";
import { claimTask, completeTask, fetchTasks, type Task, type TaskQuery } from "../api/workflow";
import { useAuth } from "../auth/AuthContext";
import { displayName } from "../auth/roles";
import { formatDate, formatDateTime, formatElapsed } from "../i18n/format";
import { tr } from "../i18n/tr";
import { BreakdownButton } from "../modules/maintenance/BreakdownButton";
import { workflowKeys } from "../workflow/queryKeys";
import { usePollInterval } from "../workflow/realtimeContext";
import { recordPath } from "../workflow/recordLinks";

const PAGE_SIZE = 50;
const PRIORITY_COLORS: Record<number, string> = { 1: "gray", 2: "blue", 3: "orange", 4: "red" };

function personName(user: { full_name: string; username: string } | null): string {
  return user ? user.full_name || user.username : "";
}

function useTaskAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      task,
      action,
      note,
    }: {
      task: Task;
      action: "claim" | "complete";
      note?: string;
    }) => (action === "claim" ? claimTask(task.id) : completeTask(task.id, note)),
    onSuccess: (_, { action }) => {
      notifications.show({
        message: action === "claim" ? tr.tasks.claimed : tr.tasks.completed,
        color: "green",
      });
    },
    onError: (error) => notifications.show({ message: getErrorMessage(error), color: "red" }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: workflowKeys.tasks }),
  });
}

function TaskCard({ task, onComplete }: { task: Task; onComplete: (task: Task) => void }) {
  const action = useTaskAction();
  const path = recordPath(task.related);
  const isOpen = task.status === "OPEN" || task.status === "IN_PROGRESS";
  const busy = action.isPending;

  return (
    <Paper withBorder radius="md" p="md" data-testid="task-card">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={4} style={{ minWidth: 0 }}>
            <Text fw={600} size="lg">
              {task.title}
            </Text>
            {task.description && (
              <Text size="sm" c="dimmed">
                {task.description}
              </Text>
            )}
          </Stack>
          <Badge color={PRIORITY_COLORS[task.priority]} variant="light" style={{ flexShrink: 0 }}>
            {task.priority_label}
          </Badge>
        </Group>
        <Group gap="xs">
          {task.assigned_role && (
            <Badge variant="outline" color="gray">
              {tr.roles[task.assigned_role] ?? task.assigned_role}
            </Badge>
          )}
          {task.assigned_user && (
            <Badge variant="outline" color="grape">
              {tr.tasks.assignedToMe}
            </Badge>
          )}
          <Badge variant="dot" color={task.status === "IN_PROGRESS" ? "teal" : "gray"}>
            {task.status_label}
          </Badge>
          {isOpen ? (
            <Text size="sm" c="dimmed" title={formatDateTime(task.created_at)}>
              {tr.tasks.waiting(formatElapsed(task.created_at))}
            </Text>
          ) : (
            <Text size="sm" c="dimmed">
              {tr.tasks.completedBy(
                personName(task.completed_by) || tr.tasks.autoClosed,
                formatDateTime(task.completed_at),
              )}
            </Text>
          )}
        </Group>
        {task.claimed_by && isOpen && (
          <Text size="sm">{tr.tasks.claimedBy(personName(task.claimed_by))}</Text>
        )}
        {task.completion_note && !isOpen && (
          <Text size="sm" c="dimmed">
            {task.completion_note}
          </Text>
        )}
        <Group gap="sm">
          {path && (
            <Button
              component={Link}
              to={path}
              variant="light"
              size="md"
              rightSection={<IconArrowRight size={18} />}
            >
              {tr.tasks.goToRecord}
            </Button>
          )}
          {task.can_act && task.status === "OPEN" && (
            <Button
              variant="default"
              size="md"
              leftSection={<IconHandGrab size={18} />}
              loading={busy && action.variables?.action === "claim"}
              disabled={busy}
              onClick={() => action.mutate({ task, action: "claim" })}
            >
              {tr.tasks.claim}
            </Button>
          )}
          {task.can_act && (
            <Button
              size="md"
              leftSection={<IconCheck size={18} />}
              disabled={busy}
              onClick={() => onComplete(task)}
            >
              {tr.tasks.complete}
            </Button>
          )}
        </Group>
      </Stack>
    </Paper>
  );
}

function CompleteModal({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const [note, setNote] = useState("");
  const action = useTaskAction();
  const close = () => {
    setNote("");
    onClose();
  };
  return (
    <Modal opened={task !== null} onClose={close} title={tr.tasks.completeTitle} centered>
      <Stack>
        <Text fw={500}>{task?.title}</Text>
        <Textarea
          label={tr.tasks.completeNote}
          value={note}
          onChange={(e) => setNote(e.currentTarget.value)}
          autosize
          minRows={2}
          maxLength={2000}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            {tr.tasks.cancel}
          </Button>
          <Button
            loading={action.isPending}
            onClick={() =>
              task && action.mutate({ task, action: "complete", note }, { onSuccess: close })
            }
          >
            {tr.tasks.complete}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function HomePage() {
  const { user } = useAuth();
  const [view, setView] = useState<"open" | "closed">("open");
  const [completing, setCompleting] = useState<Task | null>(null);
  const pollInterval = usePollInterval();
  const query: TaskQuery =
    view === "open"
      ? { mine: true, open: true, page_size: PAGE_SIZE }
      : { mine: true, open: false, ordering: "-created_at", page_size: PAGE_SIZE };
  const tasks = useInfiniteQuery({
    queryKey: workflowKeys.taskList(query),
    queryFn: ({ pageParam }) => fetchTasks({ ...query, page: pageParam }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
    refetchInterval: view === "open" ? pollInterval : false,
  });
  const items = tasks.data?.pages.flatMap((p) => p.results) ?? [];
  const total = tasks.data?.pages[0]?.count;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={2}>{user ? tr.home.greeting(displayName(user)) : tr.home.tasksTitle}</Title>
          <Text c="dimmed">{formatDate(new Date())}</Text>
        </div>
        {/* Arıza bildirimi her rolde açıktır (backend: tüm roller). */}
        <BreakdownButton />
      </Group>
      <Group justify="space-between">
        <Title order={3}>
          {tr.home.tasksTitle}
          {view === "open" && total ? ` (${total})` : ""}
        </Title>
        <SegmentedControl
          value={view}
          onChange={(value) => setView(value as "open" | "closed")}
          data={[
            { value: "open", label: tr.tasks.open },
            { value: "closed", label: tr.tasks.closed },
          ]}
        />
      </Group>
      {tasks.isPending && <Loader />}
      {tasks.isError && <Text c="red">{getErrorMessage(tasks.error)}</Text>}
      {tasks.isSuccess && items.length === 0 && (
        <Paper withBorder radius="md" p="lg">
          <Text c="dimmed">{view === "open" ? tr.tasks.empty : tr.tasks.emptyClosed}</Text>
        </Paper>
      )}
      {items.map((task) => (
        <TaskCard key={task.id} task={task} onComplete={setCompleting} />
      ))}
      {tasks.hasNextPage && (
        <Button
          variant="subtle"
          onClick={() => tasks.fetchNextPage()}
          loading={tasks.isFetchingNextPage}
        >
          {tr.tasks.loadMore}
        </Button>
      )}
      <CompleteModal task={completing} onClose={() => setCompleting(null)} />
    </Stack>
  );
}
