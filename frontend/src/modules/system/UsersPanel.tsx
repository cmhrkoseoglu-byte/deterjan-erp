import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  Menu,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
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
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getErrorMessage } from "../../api/client";
import { ROLES, type Role } from "../../api/types";
import {
  listUsers,
  resetUserOtp,
  resetUserPassword,
  setUserActive,
  unlockUser,
  type IssuedPassword,
  type UserFilters,
  type UserRecord,
} from "../../api/users";
import { useAuth } from "../../auth/AuthContext";
import { userAccessPath } from "../../auth/paths";
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

const STATE_PARAM = { etkin: "true", pasif: "false" } as const;

/** Adresteki süzgeçler (`ara`, `rol`, `durum`, `ozel`; plan §6.3 "adreste saklanır"). */
function filtersFrom(params: URLSearchParams): Required<UserFilters> {
  const role = params.get("rol") ?? "";
  const state = params.get("durum") ?? "";
  return {
    search: params.get("ara") ?? "",
    role: (ROLES as readonly string[]).includes(role) ? (role as Role) : "",
    active: state in STATE_PARAM ? STATE_PARAM[state as keyof typeof STATE_PARAM] : "",
    personal: params.get("ozel") === "1",
  };
}

function PersonalBadge({ user }: { user: UserRecord }) {
  const counts = user.personal_counts ?? { granted: 0, revoked: 0 };
  const total = counts.granted + counts.revoked;
  if (total === 0) return null;
  return (
    <Tooltip label={sy.personalTooltip(counts.granted, counts.revoked)}>
      <Badge size="sm" color="teal" variant="light">
        {sy.personalBadge(total)}
      </Badge>
    </Tooltip>
  );
}

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
 * Kullanıcı yönetimi: yeni kullanıcı (geçici şifreyle), bilgi düzenleme, şifre sıfırlama, pasife
 * alma / etkinleştirme, kilit açma ve 2FA sıfırlama. Roller ve kişiye özel yetkiler kişinin Yetkiler
 * sayfasında değişir (plan §6.3).
 */
export function UsersPanel() {
  const queryClient = useQueryClient();
  const { user: me } = useAuth();
  const [params, setParams] = useSearchParams();
  const filters = filtersFrom(params);
  const [search, setSearch] = useState(filters.search);
  const [debounced] = useDebouncedValue(search.trim(), 300);
  const [action, setAction] = useState<Action | null>(null);
  // `null` yeni kullanıcı, kayıt düzenleme; `undefined` form kapalı.
  const [editing, setEditing] = useState<UserRecord | null | undefined>(undefined);
  const [issued, setIssued] = useState<IssuedPassword | null>(null);
  const wanted: UserFilters = { ...filters, search: debounced };
  const query = useQuery({
    queryKey: [...USERS_KEY, "list", wanted],
    queryFn: () => listUsers(wanted),
    placeholderData: keepPreviousData,
  });

  function setParam(name: string, value: string) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set(name, value);
        else next.delete(name);
        return next;
      },
      { replace: true },
    );
  }

  // Arama metni gecikmeyle adrese yazılır; Yetkiler sayfasından dönünce liste aynı kalır.
  const searchInUrl = params.get("ara") ?? "";
  useEffect(() => {
    if (debounced !== searchInUrl) setParam("ara", debounced);
    // Yalnız arama metni değişince yazılır.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

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
      <Group gap="md" align="flex-end" wrap="wrap">
        <Select
          label={sy.filterRole}
          placeholder={sy.stateAll}
          data={ROLES.map((role) => ({ value: role, label: tr.roles[role] }))}
          value={filters.role || null}
          onChange={(value) => setParam("rol", value ?? "")}
          clearable
          maw={220}
        />
        <Select
          label={sy.filterState}
          data={[
            { value: "", label: sy.stateAll },
            { value: "etkin", label: sy.stateActive },
            { value: "pasif", label: sy.stateInactive },
          ]}
          value={params.get("durum") ?? ""}
          onChange={(value) => setParam("durum", value ?? "")}
          allowDeselect={false}
          maw={160}
        />
        <Switch
          label={sy.filterPersonal}
          checked={filters.personal}
          onChange={(event) => setParam("ozel", event.currentTarget.checked ? "1" : "")}
          mb={6}
        />
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
                        <Anchor component={Link} to={userAccessPath(user.id)} size="sm" fw={500}>
                          {nameOf(user)}
                        </Anchor>
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
                        <PersonalBadge user={user} />
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
                        <Button
                          size="xs"
                          variant="light"
                          component={Link}
                          to={userAccessPath(user.id)}
                        >
                          {sy.accessButton}
                        </Button>
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
