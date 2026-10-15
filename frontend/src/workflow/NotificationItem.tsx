import { ActionIcon, Badge, Group, Stack, Text, Tooltip, UnstyledButton } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import type { AppNotification } from "../api/workflow";
import { formatDateTime, formatElapsed } from "../i18n/format";
import { tr } from "../i18n/tr";
import { useMarkRead } from "./notificationActions";

const LEVEL_COLORS = { INFO: "blue", WARNING: "orange", CRITICAL: "red" } as const;

interface Props {
  notification: AppNotification;
  onOpen: (notification: AppNotification) => void;
  compact?: boolean;
}

export function NotificationItem({ notification: n, onOpen, compact }: Props) {
  const markRead = useMarkRead();
  return (
    <Group
      wrap="nowrap"
      align="flex-start"
      gap="xs"
      px="md"
      py="sm"
      bg={n.is_read ? undefined : "var(--mantine-color-blue-light)"}
      style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}
    >
      <UnstyledButton style={{ flex: 1, minWidth: 0 }} onClick={() => onOpen(n)}>
        <Stack gap={2}>
          <Group gap={6} wrap="nowrap">
            {n.level !== "INFO" && (
              <Badge size="xs" color={LEVEL_COLORS[n.level]} variant="filled">
                {tr.notifications.level[n.level]}
              </Badge>
            )}
            <Text fw={n.is_read ? 400 : 600} size="sm" truncate>
              {n.title}
            </Text>
          </Group>
          {n.body && (
            <Text
              size="sm"
              c="dimmed"
              lineClamp={compact ? 2 : undefined}
              style={{ whiteSpace: "pre-line" }}
            >
              {n.body}
            </Text>
          )}
          <Text size="xs" c="dimmed" title={formatDateTime(n.created_at)}>
            {formatElapsed(n.created_at)}
          </Text>
        </Stack>
      </UnstyledButton>
      {!n.is_read && (
        <Tooltip label={tr.notifications.markRead}>
          <ActionIcon
            variant="subtle"
            size="lg"
            aria-label={tr.notifications.markRead}
            onClick={() => markRead.mutate([n.id])}
          >
            <IconCheck size={18} />
          </ActionIcon>
        </Tooltip>
      )}
    </Group>
  );
}
