import {
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { getErrorMessage } from "../../api/client";
import { ROLES, type Role } from "../../api/types";
import { createUser, updateUser, type IssuedPassword, type UserRecord } from "../../api/users";
import { tr } from "../../i18n/tr";
import { sy } from "./strings";
import { normalizeUsernameInput, suggestUsername, USERNAME_RE } from "./usernames";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface Props {
  /** Düzenlenecek kullanıcı; `null` ise yeni kullanıcı açılır. */
  user: UserRecord | null;
  /** Giriş yapmış yöneticinin kimliği: kendi `admin` rolünü kaldıramaz. */
  selfId: number | undefined;
  onClose: () => void;
  onCreated: (issued: IssuedPassword) => void;
  onSaved: (user: UserRecord) => void;
}

type Errors = Partial<Record<"username" | "fullName" | "email", string>>;

/** Yeni kullanıcı ya da kullanıcı bilgisi / rol düzenleme penceresi (yalnızca admin). */
export function UserFormModal({ user, selfId, onClose, onCreated, onSaved }: Props) {
  const isNew = user === null;
  const isSelf = user !== null && user.id === selfId;
  const [username, setUsername] = useState(user?.username ?? "");
  const [usernameTouched, setUsernameTouched] = useState(false);
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [roles, setRoles] = useState<Role[]>(user?.roles ?? []);
  const [errors, setErrors] = useState<Errors>({});

  const mutation = useMutation({
    mutationFn: async (): Promise<void> => {
      const fields = {
        full_name: fullName.trim(),
        phone: phone.trim(),
        email: email.trim(),
        roles,
      };
      if (user === null) onCreated(await createUser({ username, ...fields }));
      else onSaved(await updateUser(user.id, fields));
    },
  });

  function changeFullName(value: string) {
    setFullName(value);
    if (isNew && !usernameTouched) setUsername(suggestUsername(value));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next: Errors = {
      fullName: fullName.trim() ? undefined : sy.required,
      username: !isNew || USERNAME_RE.test(username) ? undefined : sy.usernameInvalid,
      email: !email.trim() || EMAIL_RE.test(email.trim()) ? undefined : sy.emailInvalid,
    };
    setErrors(next);
    if (next.fullName || next.username || next.email) return;
    mutation.mutate();
  }

  const name = user ? user.full_name.trim() || user.username : "";
  return (
    <Modal
      opened
      onClose={onClose}
      title={isNew ? sy.formNewTitle : sy.formEditTitle(name)}
      size="lg"
      closeOnClickOutside={false}
    >
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          {mutation.isError && (
            <Alert color="red" variant="light" icon={<IconAlertCircle size={18} />} role="alert">
              {getErrorMessage(mutation.error)}
            </Alert>
          )}
          <TextInput
            label={sy.fullName}
            value={fullName}
            onChange={(e) => changeFullName(e.currentTarget.value)}
            error={errors.fullName}
            required
            autoComplete="off"
            data-autofocus
          />
          {user === null ? (
            <TextInput
              label={sy.username}
              description={sy.usernameHelp}
              value={username}
              onChange={(e) => {
                setUsername(normalizeUsernameInput(e.currentTarget.value));
                setUsernameTouched(true);
              }}
              error={errors.username}
              required
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
            />
          ) : (
            <div>
              <Text size="sm" fw={500}>
                {sy.username}
              </Text>
              <Text ff="monospace">{user.username}</Text>
            </div>
          )}
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              label={sy.phone}
              value={phone}
              onChange={(e) => setPhone(e.currentTarget.value)}
              inputMode="tel"
              autoComplete="off"
            />
            <TextInput
              label={sy.email}
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              error={errors.email}
              inputMode="email"
              autoComplete="off"
            />
          </SimpleGrid>
          <Checkbox.Group
            label={sy.roleField}
            description={sy.rolesHelp}
            value={roles}
            onChange={(value) => setRoles(value as Role[])}
          >
            <SimpleGrid cols={{ base: 1, xs: 2, sm: 3 }} mt="xs" spacing="xs">
              {ROLES.map((role) => (
                <Checkbox
                  key={role}
                  value={role}
                  label={tr.roles[role]}
                  disabled={isSelf && role === "admin" && roles.includes("admin")}
                />
              ))}
            </SimpleGrid>
          </Checkbox.Group>
          {isSelf && roles.includes("admin") && (
            <Text size="sm" c="dimmed">
              {sy.ownAdminLocked}
            </Text>
          )}
          {roles.length === 0 && (
            <Text size="sm" c="orange">
              {sy.noRoleWarning}
            </Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose} disabled={mutation.isPending}>
              {sy.cancel}
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {isNew ? sy.createAccount : sy.save}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
