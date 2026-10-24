import { Alert, Button, CopyButton, Group, Modal, Stack, Text } from "@mantine/core";
import { IconAlertTriangle, IconCheck, IconCopy } from "@tabler/icons-react";
import type { IssuedPassword } from "../../api/users";
import { sy } from "./strings";

/**
 * Yeni kullanıcının ya da şifresi sıfırlanan kullanıcının geçici şifresini yalnızca bir kez
 * gösterir. Dışarı tıklayınca kapanmaz; kapatınca şifre bir daha görülemez.
 */
export function TemporaryPasswordModal({
  issued,
  onClose,
}: {
  issued: IssuedPassword | null;
  onClose: () => void;
}) {
  const user = issued?.user;
  const password = issued?.temporary_password ?? "";
  return (
    <Modal
      opened={issued !== null}
      onClose={onClose}
      title={sy.tempTitle}
      closeOnClickOutside={false}
      size="md"
    >
      {user && (
        <Stack>
          <Text size="sm">
            {sy.tempIntro(user.full_name.trim() || user.username, user.username)}
          </Text>
          <Text
            ff="monospace"
            fz={28}
            fw={600}
            ta="center"
            py="xs"
            data-testid="temporary-password"
          >
            {password}
          </Text>
          <Alert color="yellow" icon={<IconAlertTriangle size={18} />}>
            {sy.tempWarning}
          </Alert>
          <Group justify="space-between">
            <CopyButton value={password}>
              {({ copied, copy }) => (
                <Button
                  variant="light"
                  color={copied ? "green" : undefined}
                  leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                  onClick={copy}
                >
                  {copied ? sy.copied : sy.copy}
                </Button>
              )}
            </CopyButton>
            <Button onClick={onClose}>{sy.tempDone}</Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}
