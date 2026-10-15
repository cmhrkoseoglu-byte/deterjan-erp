import {
  ActionIcon,
  Anchor,
  Button,
  Divider,
  Group,
  Indicator,
  Popover,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconBell, IconWifiOff } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fetchNotifications, fetchUnreadCount } from "../api/workflow";
import { tr } from "../i18n/tr";
import { NotificationItem } from "./NotificationItem";
import { useMarkRead, useOpenNotification } from "./notificationActions";
import { workflowKeys } from "./queryKeys";
import { usePollInterval, useRealtimeConnected } from "./realtimeContext";

const PREVIEW_SIZE = 8;

export function NotificationBell() {
  const [opened, setOpened] = useState(false);
  const connected = useRealtimeConnected();
  const pollInterval = usePollInterval();
  const unread = useQuery({
    queryKey: workflowKeys.unreadCount,
    queryFn: fetchUnreadCount,
    refetchInterval: pollInterval,
  });
  const recent = useQuery({
    queryKey: workflowKeys.notificationPreview,
    queryFn: () => fetchNotifications({ page_size: PREVIEW_SIZE }),
    enabled: opened,
  });
  const markRead = useMarkRead();
  const open = useOpenNotification(() => setOpened(false));
  const count = unread.data ?? 0;

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-end" width={360} shadow="md">
      <Popover.Target>
        <Indicator
          inline
          disabled={count === 0}
          label={count > 99 ? "99+" : count}
          size={18}
          color="red"
          offset={6}
        >
          <ActionIcon
            variant="subtle"
            color="gray"
            size="xl"
            radius="xl"
            aria-label={count ? tr.notifications.unreadCount(count) : tr.layout.notifications}
            onClick={() => setOpened((o) => !o)}
          >
            <IconBell size={24} />
          </ActionIcon>
        </Indicator>
      </Popover.Target>
      <Popover.Dropdown p={0}>
        <Group justify="space-between" px="md" py="sm" wrap="nowrap">
          <Group gap={6} wrap="nowrap">
            <Text fw={600}>{tr.notifications.title}</Text>
            {!connected && (
              <Tooltip label={tr.layout.liveOffline} multiline w={220}>
                <IconWifiOff size={16} color="gray" aria-label={tr.layout.liveOffline} />
              </Tooltip>
            )}
          </Group>
          <Button
            variant="subtle"
            size="compact-sm"
            disabled={count === 0}
            loading={markRead.isPending}
            onClick={() => markRead.mutate(undefined)}
          >
            {tr.notifications.markAllRead}
          </Button>
        </Group>
        <Divider />
        <ScrollArea.Autosize mah={420}>
          {recent.data?.results.length === 0 && (
            <Text c="dimmed" ta="center" py="lg">
              {tr.notifications.empty}
            </Text>
          )}
          <Stack gap={0}>
            {recent.data?.results.map((n) => (
              <NotificationItem key={n.id} notification={n} compact onOpen={open} />
            ))}
          </Stack>
        </ScrollArea.Autosize>
        <Divider />
        <Anchor
          component={Link}
          to="/bildirimler"
          display="block"
          ta="center"
          py="sm"
          onClick={() => setOpened(false)}
        >
          {tr.notifications.seeAll}
        </Anchor>
      </Popover.Dropdown>
    </Popover>
  );
}
