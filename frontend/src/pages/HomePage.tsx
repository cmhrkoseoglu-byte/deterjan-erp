import { Paper, Stack, Text, Title } from "@mantine/core";
import { useAuth } from "../auth/AuthContext";
import { displayName } from "../auth/roles";
import { formatDate } from "../i18n/format";
import { tr } from "../i18n/tr";

export function HomePage() {
  const { user } = useAuth();
  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>{user ? tr.home.greeting(displayName(user)) : tr.home.tasksTitle}</Title>
        <Text c="dimmed">{formatDate(new Date())}</Text>
      </div>
      <Paper withBorder radius="md" p="lg">
        <Title order={3} mb="xs">
          {tr.home.tasksTitle}
        </Title>
        <Text c="dimmed">{tr.home.tasksEmpty}</Text>
      </Paper>
    </Stack>
  );
}
