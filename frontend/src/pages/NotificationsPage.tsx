import { Button, Group, Paper, SegmentedControl, Stack, Text, Title } from "@mantine/core";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchNotifications } from "../api/workflow";
import { tr } from "../i18n/tr";
import { NotificationItem } from "../workflow/NotificationItem";
import { useMarkRead, useOpenNotification } from "../workflow/notificationActions";
import { workflowKeys } from "../workflow/queryKeys";

const PAGE_SIZE = 50;

export function NotificationsPage() {
  const [filter, setFilter] = useState<"unread" | "all">("all");
  const unread = filter === "unread";
  const list = useInfiniteQuery({
    queryKey: workflowKeys.notificationList(unread),
    queryFn: ({ pageParam }) =>
      fetchNotifications({ unread: unread || undefined, page: pageParam, page_size: PAGE_SIZE }),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => (last.next ? pages.length + 1 : undefined),
  });
  const markRead = useMarkRead();
  const open = useOpenNotification();
  const items = list.data?.pages.flatMap((p) => p.results) ?? [];

  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Title order={2}>{tr.notifications.title}</Title>
        <Button
          variant="light"
          loading={markRead.isPending}
          onClick={() => markRead.mutate(undefined)}
        >
          {tr.notifications.markAllRead}
        </Button>
      </Group>
      <SegmentedControl
        value={filter}
        onChange={(value) => setFilter(value as "unread" | "all")}
        data={[
          { value: "all", label: tr.notifications.all },
          { value: "unread", label: tr.notifications.unreadOnly },
        ]}
        w="fit-content"
      />
      <Paper withBorder radius="md">
        {list.isSuccess && items.length === 0 && (
          <Text c="dimmed" ta="center" py="xl">
            {unread ? tr.notifications.emptyUnread : tr.notifications.empty}
          </Text>
        )}
        {items.map((n) => (
          <NotificationItem key={n.id} notification={n} onOpen={open} />
        ))}
      </Paper>
      {list.hasNextPage && (
        <Button
          variant="subtle"
          onClick={() => list.fetchNextPage()}
          loading={list.isFetchingNextPage}
        >
          {tr.tasks.loadMore}
        </Button>
      )}
    </Stack>
  );
}
