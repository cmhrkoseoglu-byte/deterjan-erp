import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Menu,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconDots,
  IconInfoCircle,
  IconKey,
  IconSearch,
  IconUserCheck,
  IconUserOff,
  IconUserPlus,
} from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getErrorMessage } from "../../api/client";
import {
  listUsers,
  resetUserOtp,
  resetUserPassword,
  setUserActive,
  unlockUser,
  type IssuedPassword,
  type UserRecord,
} from "../../api/users";
import { useAuth } from "../../auth/AuthContext";
import { formatDateTime } from "../../i18n/format";
import { tr } from "../../i18n/tr";
import { ConfirmModal } from "../common/ConfirmModal";
import { sy } from "./strings";
import { TemporaryPasswordModal } from "./TemporaryPasswordModal";
import { UserFormModal } from "./UserFormModal";

type ActionKind = "unlock" | "resetOtp" | "resetPassword" | "deactivate" | "activate";
type Action = { kind: ActionKind; user: UserRecord };

/** Onaylı işlemler: düğme metni, onay sorusu, sonuç bildirimi. */
const ACTIONS: Record<
  ActionKind,
  { label: string; confirm: (name: string) => string; done: (name: string) => string }
> = {
  unlock: { label: sy.unlock, confirm: sy.confirmUnlock, done: sy.unlocked },
  resetOtp: { label: sy.resetOtp, confirm: sy.confirmResetOtp, done: sy.otpReset },
  resetPassword: {
    label: sy.resetPassword,
    confirm: sy.confirmResetPassword,
    done: sy.passwordReset,
  },
  deactivate: { label: sy.deactivate, confirm: sy.confirmDeactivate, done: sy.deactivated },
  activate: { label: sy.activate, confirm: sy.confirmActivate, done: sy.activated },
};

const USERS_KEY = ["system", "users"] as const;

function nameOf(user: UserRecord): string {
  return user.full_name.trim() || user.username;
}

/** Şifre sıfırlamada geçici şifre döner; diğer işlemler kullanıcı kaydını döner. */
async function run(action: Action): Promise<IssuedPassword | null> {
  const id = action.user.id;
  switch (action.kind) {
    case "unlock":
      await unlockUser(id);
      return null;
    case "resetOtp":
      await resetUserOtp(id);
      return null;
    case "resetPassword":
      return resetUserPassword(id);
    case "deactivate":
      await setUserActive(id, false);
      return null;
    case "activate":
      await setUserActive(id, true);
      return null;
  }
}

/**
 * Kullanıcı yönetimi: yeni kullanıcı (geçici şifreyle), bilgi ve rol düzenleme, şifre sıfırlama,
 * pasife alma / etkinleştirme, kilit açma ve 2FA sıfırlama.
 */
export function UsersPanel() {
  const queryClient = useQueryClient();
  const { user: me } = useAuth();
  const [search, setSearch] = useState("");
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [action, setAction] = useState<Action | null>(null);
  // `null` yeni kullanıcı, kayıt düzenleme; `undefined` form kapalı.
  const [editing, setEditing] = useState<UserRecord | null | undefined>(undefined);
  const [issued, setIssued] = useState<IssuedPassword | null>(null);
  const query = useQuery({
    queryKey: [...USERS_KEY, debounced],
    queryFn: () => listUsers(debounced),
    placeholderData: keepPreviousData,
  });

  function reload() {
    return queryClient.invalidateQueries({ queryKey: USERS_KEY });
  }

  const mutation = useMutation({
    mutationFn: run,
    onSuccess: (result, a) => {
      setAction(null);
      if (result) setIssued(result);
      else notifications.show({ color: "green", message: ACTIONS[a.kind].done(nameOf(a.user)) });
      reload();
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
      </Alert>
      <Group justify="space-between" align="flex-end">
        <TextInput
          placeholder={sy.search}
          aria-label={sy.search}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          maw={360}
          style={{ flex: 1 }}
        />
        <Button leftSection={<IconUserPlus size={18} />} onClick={() => setEditing(null)}>
          {sy.newUser}
        </Button>
      </Group>
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
        <Table.ScrollContainer minWidth={900}>
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
              {users.map((user) => {
                const isSelf = user.id === me?.id;
                return (
                  <Table.Tr key={user.id}>
                    <Table.Td>
                      <Group gap={6} wrap="nowrap">
                        <Text size="sm" fw={500}>
                          {nameOf(user)}
                        </Text>
                        {isSelf && (
                          <Badge size="xs" variant="outline">
                            {sy.you}
                          </Badge>
                        )}
                      </Group>
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
                        {user.must_change_password && user.is_active && (
                          <Badge size="sm" color="yellow">
                            {sy.tempPassword}
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
                        <Button size="xs" variant="default" onClick={() => setEditing(user)}>
                          {sy.edit}
                        </Button>
                        {!isSelf && (
                          <Menu position="bottom-end" withinPortal>
                            <Menu.Target>
                              <ActionIcon
                                variant="subtle"
                                color="gray"
                                size="lg"
                                aria-label={sy.moreActions(nameOf(user))}
                              >
                                <IconDots size={18} />
                              </ActionIcon>
                            </Menu.Target>
                            <Menu.Dropdown>
                              {user.is_active && (
                                <Menu.Item
                                  leftSection={<IconKey size={16} />}
                                  onClick={() => setAction({ kind: "resetPassword", user })}
                                >
                                  {sy.resetPassword}
                                </Menu.Item>
                              )}
                              {user.is_active ? (
                                <Menu.Item
                                  color="red"
                                  leftSection={<IconUserOff size={16} />}
                                  onClick={() => setAction({ kind: "deactivate", user })}
                                >
                                  {sy.deactivate}
                                </Menu.Item>
                              ) : (
                                <Menu.Item
                                  leftSection={<IconUserCheck size={16} />}
                                  onClick={() => setAction({ kind: "activate", user })}
                                >
                                  {sy.activate}
                                </Menu.Item>
                              )}
                            </Menu.Dropdown>
                          </Menu>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <ConfirmModal
        opened={action !== null}
        message={action ? ACTIONS[action.kind].confirm(nameOf(action.user)) : ""}
        confirmLabel={action ? ACTIONS[action.kind].label : ""}
        danger={action?.kind !== "activate"}
        loading={mutation.isPending}
        onConfirm={() => action && mutation.mutate(action)}
        onClose={close}
      />
      {editing !== undefined && (
        <UserFormModal
          user={editing}
          selfId={me?.id}
          onClose={() => setEditing(undefined)}
          onCreated={(result) => {
            setEditing(undefined);
            setIssued(result);
            reload();
          }}
          onSaved={(saved) => {
            setEditing(undefined);
            notifications.show({ color: "green", message: sy.saved(nameOf(saved)) });
            reload();
          }}
        />
      )}
      <TemporaryPasswordModal issued={issued} onClose={() => setIssued(null)} />
    </Stack>
  );
}
