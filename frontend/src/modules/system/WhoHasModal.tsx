import {
  Alert,
  Anchor,
  Badge,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { fetchAccessHolders, type AccessHolder } from "../../api/access";
import { accessKeys } from "../../api/accessKeys";
import { getErrorMessage } from "../../api/client";
import { ROLES } from "../../api/types";
import { describeAccess } from "../../auth/access";
import { userAccessPath } from "../../auth/paths";
import { tr } from "../../i18n/tr";
import type { WhoHasTarget } from "./RoleAccessPanel";
import { sy } from "./strings";

function sourceText(holder: AccessHolder): string {
  if (holder.source === "role")
    return sy.fromRoleSource(holder.roles.map((role) => tr.roles[role] ?? role).join(", "));
  return sy.sources[holder.source] ?? holder.source;
}

/**
 * "Kimde var?" (plan §6.2, "Kim neyi görür" raporu): yetkiyi etkin olarak taşıyan kişiler
 * kaynaklarıyla; rolde olup kişiden kaldırılanlar soluk ve üstü çizili. Görev ayrılığı uyarısı
 * rozetle gösterilir (plan §5.11).
 */
export function WhoHasModal({ target, onClose }: { target: WhoHasTarget; onClose: () => void }) {
  const [role, setRole] = useState<string | null>(
    ROLES.includes(target.holder as (typeof ROLES)[number]) ? target.holder : null,
  );
  const query = useQuery({
    queryKey: accessKeys.holders(target.key, target.level),
    queryFn: () => fetchAccessHolders(target.key, target.level),
  });
  const holders = (query.data?.holders ?? []).filter(
    (holder) => !role || (holder.user.roles as string[]).includes(role),
  );
  const title = describeAccess(target) ?? target.key;
  return (
    <Modal opened onClose={onClose} title={sy.whoHasTitle(title)} size="xl">
      <Stack>
        <Select
          label={sy.filterRole}
          placeholder={sy.allRoles}
          data={ROLES.filter((item) => item !== "admin").map((item) => ({
            value: item,
            label: tr.roles[item],
          }))}
          value={role}
          onChange={setRole}
          clearable
          clearButtonProps={{ "aria-label": sy.clearRoleFilter }}
          maw={240}
        />
        {query.isLoading && <Loader />}
        {query.isError && (
          <Alert color="red" variant="light">
            {getErrorMessage(query.error)}
          </Alert>
        )}
        {query.data && holders.length === 0 && <Text c="dimmed">{sy.whoHasEmpty}</Text>}
        {holders.length > 0 && (
          <Table.ScrollContainer minWidth={560}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{sy.holderColumn}</Table.Th>
                  <Table.Th>{sy.sourceColumn}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {holders.map((holder) => {
                  const revoked = holder.source === "revoked";
                  return (
                    <Table.Tr
                      key={holder.user.id}
                      style={revoked ? { opacity: 0.6, textDecoration: "line-through" } : undefined}
                    >
                      <Table.Td>
                        <Anchor component={Link} to={userAccessPath(holder.user.id)} size="sm">
                          {holder.user.full_name.trim() || holder.user.username}
                        </Anchor>
                        <Text size="xs" c="dimmed">
                          {holder.user.username}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs">
                          <Text size="sm">{sourceText(holder)}</Text>
                          {holder.segregation.length > 0 && (
                            <Badge color="orange" variant="light" size="sm">
                              {sy.segregation}
                            </Badge>
                          )}
                        </Group>
                        {holder.segregation.map((text) => (
                          <Text key={text} size="xs" c="orange">
                            {text}
                          </Text>
                        ))}
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
    </Modal>
  );
}
