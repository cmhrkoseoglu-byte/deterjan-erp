import { Alert, Button, CopyButton, Group, Modal, SimpleGrid, Stack, Text } from "@mantine/core";
import { IconAlertTriangle, IconCheck, IconCopy, IconPrinter } from "@tabler/icons-react";
import { st } from "./strings";

/** Kurtarma kodlarını yalnızca bir kez gösterir; kopyalama ve yazdırma seçenekli. */
export function RecoveryCodesModal({
  codes,
  onClose,
}: {
  codes: string[] | null;
  onClose: () => void;
}) {
  return (
    <Modal
      opened={codes !== null}
      onClose={onClose}
      title={st.codesTitle}
      closeOnClickOutside={false}
      size="md"
    >
      <Stack>
        <Alert color="yellow" icon={<IconAlertTriangle size={18} />}>
          {st.codesWarning}
        </Alert>
        <Text size="sm">{st.codesHelp}</Text>
        <SimpleGrid cols={2} spacing="xs" data-testid="recovery-codes">
          {(codes ?? []).map((code) => (
            <Text key={code} ff="monospace" fz="lg" ta="center">
              {code}
            </Text>
          ))}
        </SimpleGrid>
        <Group justify="space-between">
          <Group gap="xs">
            <CopyButton value={(codes ?? []).join("\n")}>
              {({ copied, copy }) => (
                <Button
                  variant="light"
                  color={copied ? "green" : undefined}
                  leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                  onClick={copy}
                >
                  {copied ? st.copied : st.copy}
                </Button>
              )}
            </CopyButton>
            <Button
              variant="light"
              leftSection={<IconPrinter size={16} />}
              onClick={() => window.print()}
            >
              {st.print}
            </Button>
          </Group>
          <Button onClick={onClose}>{st.codesSaved}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
