import { Button, Group, Paper, Text } from "@mantine/core";
import { ua } from "./strings";

interface Props {
  count: number;
  disabled: boolean;
  onDiscard: () => void;
  onSave: () => void;
}

/** Altta yapışkan kaydet çubuğu: yalnız kaydedilmemiş değişiklik varken (plan §6.1). */
export function SaveBar({ count, disabled, onDiscard, onSave }: Props) {
  return (
    <Paper
      withBorder
      shadow="md"
      radius="md"
      p="sm"
      role="region"
      aria-label={ua.unsavedCount(count)}
      style={{ position: "sticky", bottom: 8, zIndex: 20 }}
    >
      <Group justify="space-between" wrap="wrap">
        <Text size="sm" fw={500}>
          {ua.unsavedCount(count)}
        </Text>
        <Group gap="xs">
          <Button variant="default" onClick={onDiscard}>
            {ua.discard}
          </Button>
          <Button onClick={onSave} disabled={disabled}>
            {ua.saveEllipsis}
          </Button>
        </Group>
      </Group>
    </Paper>
  );
}
