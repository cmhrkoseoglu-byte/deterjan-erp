import { Alert, Badge, Card, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { fetchMyAccess, type MyAccess } from "../api/access";
import { accessKeys } from "../api/accessKeys";
import { getErrorMessage } from "../api/client";
import type { Role } from "../api/types";
import { LEVEL_LABELS, MODULES, SECTIONS, type AccessLevel } from "../auth/access.gen";
import { tr } from "../i18n/tr";

type Entry = MyAccess["entries"][number];
type Revoked = MyAccess["revoked"][number];

const LEVELS: readonly AccessLevel[] = ["view", "change", "approve"];

function rolesText(roles: readonly Role[]): string {
  return roles.map((role) => tr.roles[role] ?? role).join(", ");
}

function sourceText(entry: Entry): string {
  switch (entry.source) {
    case "everyone":
      return tr.myAccess.everyone;
    case "any_role":
      return tr.myAccess.anyRole;
    case "granted":
      return tr.myAccess.granted;
    default:
      return tr.myAccess.fromRole(rolesText(entry.roles));
  }
}

function label(key: string): string {
  return (SECTIONS as Readonly<Record<string, { label: string }>>)[key]?.label ?? key;
}

function LevelBadges({
  sectionKey,
  entries,
  revoked,
}: {
  sectionKey: string;
  entries: Entry[];
  revoked: Revoked[];
}) {
  return (
    <Group gap={6}>
      {LEVELS.map((level) => {
        const entry = entries.find((item) => item.key === sectionKey && item.level === level);
        if (entry)
          return (
            <Badge
              key={level}
              variant="light"
              color={entry.source === "granted" ? "green" : "blue"}
              tt="none"
            >
              {LEVEL_LABELS[level]} · {sourceText(entry)}
            </Badge>
          );
        const gone = revoked.find((item) => item.key === sectionKey && item.level === level);
        if (gone)
          return (
            <Badge
              key={level}
              variant="outline"
              color="gray"
              tt="none"
              style={{ textDecoration: "line-through" }}
            >
              {LEVEL_LABELS[level]} · {tr.myAccess.revoked}
            </Badge>
          );
        return null;
      })}
    </Group>
  );
}

/**
 * Yetkilerim (plan §6.4): kişinin rolleri, hassas hakları ve yetkisi olan modüller kaynaklarıyla;
 * kişi için kapatılan açık kayıtlar da görünür. Salt okunurdur; yetki değişince (anlık
 * `access.changed`) kendiliğinden yenilenir.
 */
export function MyAccessPage() {
  const query = useQuery({ queryKey: accessKeys.mine, queryFn: fetchMyAccess });
  const data = query.data;
  return (
    <Stack>
      <Title order={2}>{tr.myAccess.title}</Title>
      <Text c="dimmed">{tr.myAccess.intro}</Text>
      {query.isLoading && <Loader />}
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {data && data.is_admin && (
        <Alert color="grape" variant="light" icon={<IconInfoCircle size={18} />}>
          {tr.myAccess.admin}
        </Alert>
      )}
      {data && !data.is_admin && <Details data={data} />}
    </Stack>
  );
}

function Details({ data }: { data: MyAccess }) {
  const sensitive = MODULES.find((item) => item.key === "sensitive")?.sections ?? [];
  return (
    <Stack>
      <Stack gap={4}>
        <Title order={4}>{tr.myAccess.roles}</Title>
        {data.roles.length > 0 ? (
          <Group gap={4}>
            {data.roles.map((role) => (
              <Badge key={role} variant="light">
                {tr.roles[role] ?? role}
              </Badge>
            ))}
          </Group>
        ) : (
          <Text size="sm">{tr.myAccess.noRole}</Text>
        )}
      </Stack>
      <Card withBorder>
        <Stack gap="xs">
          <Title order={4}>{tr.myAccess.sensitive}</Title>
          {sensitive.map((key) => {
            const has = data.entries.some((item) => item.key === key);
            const gone = data.revoked.some((item) => item.key === key);
            return (
              <Group key={key} gap="xs" justify="space-between">
                <Text size="sm">{label(key)}</Text>
                {has || gone ? (
                  <LevelBadges sectionKey={key} entries={data.entries} revoked={data.revoked} />
                ) : (
                  <Text size="sm" c="dimmed">
                    {tr.myAccess.none}
                  </Text>
                )}
              </Group>
            );
          })}
        </Stack>
      </Card>
      <Title order={4}>{tr.myAccess.modules}</Title>
      {MODULES.filter((item) => item.key !== "sensitive").map((module) => {
        const keys = module.sections.filter(
          (key) =>
            SECTIONS[key].kind !== "open_records" &&
            (data.entries.some((item) => item.key === key) ||
              data.revoked.some((item) => item.key === key && item.level !== "read")),
        );
        const closed = data.revoked.some(
          (item) =>
            item.level === "read" &&
            SECTIONS[item.key as keyof typeof SECTIONS]?.module === module.key,
        );
        if (keys.length === 0 && !closed) return null;
        return (
          <Card key={module.key} withBorder role="region" aria-label={module.label}>
            <Stack gap="xs">
              <Text fw={600}>{module.label}</Text>
              {closed && (
                <Text size="sm" c="red">
                  {tr.myAccess.closed(module.label)}
                </Text>
              )}
              {keys.map((key) => (
                <Group key={key} gap="xs" justify="space-between" wrap="wrap">
                  <Text size="sm">{label(key)}</Text>
                  <LevelBadges sectionKey={key} entries={data.entries} revoked={data.revoked} />
                </Group>
              ))}
            </Stack>
          </Card>
        );
      })}
    </Stack>
  );
}
