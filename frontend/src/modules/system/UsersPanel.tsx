import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import { listUsers, resetUserOtp, unlockUser, type UserRecord } from "../../api/users";
import { formatDateTime } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { ConfirmModal } from "../common/ConfirmModal";
import { sy } from "./strings";

type Action = { kind: "unlock" | "resetOtp"; user: UserRecord };

const USERS_KEY = ["system", "users"] as const;

function nameOf(user: UserRecord): string {
  return user.full_name.trim() || user.username;
}

/** Kullanıcı listesi: kilit ve 2FA durumu; kilit açma ve 2FA sıfırlama. */
export function UsersPanel() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [action, setAction] = useState<Action | null>(null);
  const query = useQuery({
    queryKey: [...USERS_KEY, debounced],
    queryFn: () => listUsers(debounced),
    placeholderData: keepPreviousData,
  });
  const mutation = useMutation({
    mutationFn: (a: Action) =>
      a.kind === "unlock" ? unlockUser(a.user.id) : resetUserOtp(a.user.id),
    onSuccess: (_data, a) => {
      notifications.show({
        color: "green",
        message: a.kind === "unlock" ? sy.unlocked(nameOf(a.user)) : sy.otpReset(nameOf(a.user)),
      });
      setAction(null);
      queryClient.invalidateQueries({ queryKey: USERS_KEY });
    },
    onError: (error) => notifications.show({ color: "red", message: getErrorMessage(error) }),
  });

  function close() {
    setAction(null);
    mutation.reset();
  }

  const users = query.data?.results ?? [];
  return (
    <Stack>
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={18} />}>
        <Text size="sm">{sy.usersNote}</Text>
        <Anchor href="/admin/core/user/" size="sm">
          {sy.usersAdminLink}
        </Anchor>
      </Alert>
      <TextInput
        placeholder={sy.search}
        aria-label={sy.search}
        leftSection={<IconSearch size={16} />}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        maw={360}
      />
      {query.isError && (
        <Alert color="red" variant="light">
          {getErrorMessage(query.error)}
        </Alert>
      )}
      {query.isLoading ? (
        <Loader />
      ) : users.length === 0 ? (
        <Text c="dimmed">{sy.noUsers}</Text>
      ) : (
        <Table.ScrollContainer minWidth={820}>
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{sy.user}</Table.Th>
                <Table.Th>{sy.roles}</Table.Th>
                <Table.Th>{sy.state}</Table.Th>
                <Table.Th>{sy.lastLogin}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {users.map((user) => (
                <Table.Tr key={user.id}>
                  <Table.Td>
                    <Text size="sm" fw={500}>
                      {nameOf(user)}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {user.username}
                      {user.email ? ` · ${user.email}` : ""}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {user.is_superuser && (
                        <Badge size="sm" color="grape" variant="light">
                          {sy.superuser}
                        </Badge>
                      )}
                      {user.roles.map((role) => (
                        <Badge key={role} size="sm" variant="light">
                          {tr.roles[role] ?? role}
                        </Badge>
                      ))}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4}>
                      {!user.is_active && (
                        <Badge size="sm" color="gray">
                          {sy.inactive}
                        </Badge>
                      )}
                      {user.is_locked && (
                        <Badge size="sm" color="red">
                          {sy.locked}
                        </Badge>
                      )}
                      <Badge
                        size="sm"
                        variant="outline"
                        color={user.otp_enabled ? "green" : "gray"}
                      >
                        {user.otp_enabled ? sy.otpOn : sy.otpOff}
                      </Badge>
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {user.last_login ? formatDateTime(user.last_login) : sy.never}
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end" wrap="nowrap">
                      {user.is_locked && (
                        <Button
                          size="xs"
                          variant="light"
                          color="red"
                          onClick={() => setAction({ kind: "unlock", user })}
                        >
                          {sy.unlock}
                        </Button>
                      )}
                      {user.otp_enabled && (
                        <Button
                          size="xs"
                          variant="light"
                          onClick={() => setAction({ kind: "resetOtp", user })}
                        >
                          {sy.resetOtp}
                        </Button>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <ConfirmModal
        opened={action !== null}
        message={
          action
            ? (action.kind === "unlock" ? sy.confirmUnlock : sy.confirmResetOtp)(
                nameOf(action.user),
              )
            : ""
        }
        confirmLabel={action?.kind === "unlock" ? sy.unlock : sy.resetOtp}
        danger
        loading={mutation.isPending}
        onConfirm={() => action && mutation.mutate(action)}
        onClose={close}
      />
    </Stack>
  );
}
