import { Stack, Text, Title } from "@mantine/core";
import { useAuth } from "../../auth/AuthContext";
import { displayName } from "../../auth/roles";
import { formatDate } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { Dashboard } from "./ReportingPage";
import { rt } from "./strings";

/** Yönetim panosu (`/pano`): yönetim rolünün açılış ekranı. Aynı pano Panolar sekmesinde de var. */
export function ManagementHomePage() {
  const { user } = useAuth();
  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>{rt.managementTitle}</Title>
        <Text c="dimmed">
          {user ? `${tr.home.greeting(displayName(user))} · ` : ""}
          {formatDate(new Date())}
        </Text>
      </div>
      <Dashboard code="management" />
    </Stack>
  );
}
