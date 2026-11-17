import { Checkbox, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { ROLES, type Role } from "../../../api/types";
import { tr } from "../../../i18n/tr";
import { ua } from "./strings";

interface Props {
  roles: Role[];
  savedRoles: Role[];
  isSelf: boolean;
  /** Kaydedince biten kişiye özel ayar sayısı (admin rolü verilirse). */
  activeOverrides: number;
  /** Kayıtlı KVKK eklemesi var mı (yönetim rolü kaldırılırsa kaydedince biter)? */
  kvkkGrants: boolean;
  onChange: (roles: Role[]) => void;
}

/** Kişinin rolleri: aynı taslakta, aynı kayıtla değişir (plan §5.10, §6.1). */
export function RolesSection({
  roles,
  savedRoles,
  isSelf,
  activeOverrides,
  kvkkGrants,
  onChange,
}: Props) {
  const ownAdmin = isSelf && savedRoles.includes("admin");
  const becomesAdmin = roles.includes("admin") && !savedRoles.includes("admin");
  const losesManagement = savedRoles.includes("yonetim") && !roles.includes("yonetim");
  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="xs">
        <Title order={4}>{ua.roles}</Title>
        <Checkbox.Group
          aria-label={ua.roles}
          description={ua.rolesHelp}
          value={roles}
          onChange={(value) =>
            // Sunucudaki gibi alfabetik (rol sırası farkı değişiklik sayılmaz).
            onChange(ROLES.filter((role) => (value as string[]).includes(role)).sort())
          }
        >
          <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }} mt="xs" spacing="xs">
            {ROLES.map((role) => (
              <Checkbox
                key={role}
                value={role}
                label={tr.roles[role]}
                disabled={ownAdmin && role === "admin"}
              />
            ))}
          </SimpleGrid>
        </Checkbox.Group>
        {ownAdmin && (
          <Text size="sm" c="dimmed">
            {ua.ownAdminLocked}
          </Text>
        )}
        {becomesAdmin && activeOverrides > 0 && (
          <Text size="sm" c="orange">
            {ua.adminWillEnd(activeOverrides)}
          </Text>
        )}
        {losesManagement && kvkkGrants && (
          <Text size="sm" c="orange">
            {ua.kvkkWillEnd}
          </Text>
        )}
      </Stack>
    </Paper>
  );
}
