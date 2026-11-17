import { Alert, Group, Loader, Pagination, Paper, Stack, Text } from "@mantine/core";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchUserAccessHistory,
  HISTORY_PAGE_SIZE,
  type AccessHistoryLine,
} from "../../../api/access";
import { accessKeys } from "../../../api/accessKeys";
import { getErrorMessage } from "../../../api/client";
import type { Role } from "../../../api/types";
import { describeAccess } from "../../../auth/access";
import { formatDateTime } from "../../../i18n/format";
import { tr } from "../../../i18n/tr";
import { END_REASONS, ua } from "./strings";

function rolesText(roles: readonly Role[]): string {
  return roles.length > 0 ? roles.map((role) => tr.roles[role] ?? role).join(", ") : ua.noRoles;
}

function lineText(line: AccessHistoryLine): string {
  const text = describeAccess(line) ?? `${line.key} (${line.level})`;
  if (line.kind === "granted") return ua.historyGranted(text);
  if (line.kind === "revoked") return ua.historyRevoked(text);
  const reason = line.reason_label || (line.reason ? END_REASONS[line.reason] : "") || "";
  return ua.historyEnded(reason, text);
}

/** Geçmiş sekmesi: tarih, değiştiren, gerekçe; eklenen, kaldırılan ve biten ayarlar (plan §6.1). */
export function AccessHistory({ userId }: { userId: number }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: accessKeys.history(userId, page),
    queryFn: () => fetchUserAccessHistory(userId, page),
    placeholderData: keepPreviousData,
  });
  if (query.isLoading) return <Loader />;
  if (query.isError)
    return (
      <Alert color="red" variant="light">
        {getErrorMessage(query.error)}
      </Alert>
    );
  const entries = query.data?.results ?? [];
  const pages = Math.ceil((query.data?.count ?? 0) / HISTORY_PAGE_SIZE);
  if (entries.length === 0) return <Text c="dimmed">{ua.historyEmpty}</Text>;
  return (
    <Stack>
      {entries.map((entry) => (
        <Paper key={entry.id} withBorder radius="md" p="sm" data-testid="history-entry">
          <Stack gap={4}>
            <Group gap="xs">
              <Text size="sm" fw={600}>
                {formatDateTime(entry.timestamp)}
              </Text>
              <Text size="sm" c="dimmed">
                · {entry.actor_name ?? ua.system}
              </Text>
            </Group>
            {entry.note && (
              <Text size="sm" fs="italic">
                “{entry.note}”
              </Text>
            )}
            {entry.roles && (
              <Text size="sm">
                {ua.historyRoles(rolesText(entry.roles.before), rolesText(entry.roles.after))}
              </Text>
            )}
            {entry.lines.map((line) => (
              <Text size="sm" key={`${line.kind}:${line.key}:${line.level}`}>
                {lineText(line)}
              </Text>
            ))}
          </Stack>
        </Paper>
      ))}
      {pages > 1 && <Pagination total={pages} value={page} onChange={setPage} />}
    </Stack>
  );
}
