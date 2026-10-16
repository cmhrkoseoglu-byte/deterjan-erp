import { Alert, Card, Group, Stack, Switch, Text, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconDeviceTablet } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { setFieldDevice } from "../../api/auth";
import { getErrorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { idleMinutes } from "../security/strings";
import { sy } from "./strings";

/** Sunucudaki saha tableti hareketsizlik süresinin varsayılanı (FIELD_DEVICE_IDLE_TIMEOUT_MINUTES).
 * Tarayıcı saha tableti değilken sunucu bu süreyi bildirmez. */
const DEFAULT_FIELD_MINUTES = 10;

/** Bu tarayıcıyı saha tableti olarak işaretleme (yalnızca admin). */
export function DevicePanel() {
  const { user, refresh } = useAuth();
  const isField = Boolean(user?.field_device);
  const currentMinutes = idleMinutes(user?.idle_timeout_seconds ?? 0);
  const fieldMinutes = isField ? currentMinutes : DEFAULT_FIELD_MINUTES;
  const mutation = useMutation({
    mutationFn: (enabled: boolean) => setFieldDevice(enabled),
    onSuccess: async (data) => {
      notifications.show({
        color: "green",
        message: data.enabled ? sy.deviceMarked : sy.deviceUnmarked,
      });
      await refresh();
    },
  });
  return (
    <Card withBorder maw={720}>
      <Stack>
        <Group gap="xs">
          <IconDeviceTablet size={22} />
          <Title order={4}>{sy.deviceTitle}</Title>
        </Group>
        <Text fw={500}>{isField ? sy.deviceIsField : sy.deviceNotField}</Text>
        <Text size="sm">{sy.deviceHelp(fieldMinutes)}</Text>
        {mutation.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(mutation.error)}
          </Alert>
        )}
        <Switch
          size="md"
          label={sy.deviceSwitch}
          checked={isField}
          disabled={mutation.isPending}
          onChange={(e) => mutation.mutate(e.currentTarget.checked)}
        />
        <Text size="sm" c="dimmed">
          {sy.deviceCurrentIdle(currentMinutes)}
        </Text>
      </Stack>
    </Card>
  );
}
