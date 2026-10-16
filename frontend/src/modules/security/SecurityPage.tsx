import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Image,
  List,
  Loader,
  Modal,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconDeviceTablet, IconShieldLock } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import * as authApi from "../../api/auth";
import { getErrorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { groupSecret, svgDataUrl } from "./otp";
import { RecoveryCodesModal } from "./RecoveryCodesModal";
import { idleMinutes, st } from "./strings";

export const SECURITY_QUERY_KEY = ["auth", "security"] as const;

function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert color="red" icon={<IconAlertCircle size={18} />} role="alert">
      <Text size="sm" style={{ whiteSpace: "pre-line" }}>
        {getErrorMessage(error)}
      </Text>
    </Alert>
  );
}

/** Kendi güvenlik ayarlarım: şifre, iki aşamalı doğrulama, oturum bilgisi. */
export function SecurityPage() {
  const { user } = useAuth();
  const query = useQuery({ queryKey: SECURITY_QUERY_KEY, queryFn: authApi.fetchSecurity });
  return (
    <Stack maw={760}>
      <Title order={2}>{st.title}</Title>
      {user?.otp_setup_required && (
        <Alert color="yellow" icon={<IconShieldLock size={18} />} title={st.setupRequiredTitle}>
          {st.setupRequired}
        </Alert>
      )}
      {query.isLoading && <Loader />}
      {query.isError && <ErrorAlert error={query.error} />}
      {query.data && (
        <>
          <OtpCard status={query.data} />
          <PasswordCard help={query.data.password_help} />
          <SessionCard status={query.data} />
        </>
      )}
    </Stack>
  );
}

function PasswordCard({ help }: { help: string[] }) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ old?: string; new?: string; confirm?: string }>({});
  const mutation = useMutation({
    mutationFn: (payload: { old_password: string; new_password: string }) =>
      authApi.changePassword(payload),
    onSuccess: () => {
      setOldPassword("");
      setNewPassword("");
      setConfirm("");
      notifications.show({ color: "green", message: st.passwordChanged });
    },
  });

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const next = {
      old: oldPassword ? undefined : st.required,
      new: newPassword ? undefined : st.required,
      confirm: confirm === newPassword ? undefined : st.passwordMismatch,
    };
    setErrors(next);
    if (next.old || next.new || next.confirm) return;
    mutation.mutate({ old_password: oldPassword, new_password: newPassword });
  }

  return (
    <Card withBorder>
      <form onSubmit={handleSubmit} noValidate>
        <Stack>
          <Title order={4}>{st.passwordTitle}</Title>
          <ErrorAlert error={mutation.error} />
          {mutation.isSuccess && (
            <Alert color="green" variant="light">
              {st.passwordChanged}
            </Alert>
          )}
          <PasswordInput
            label={st.oldPassword}
            value={oldPassword}
            onChange={(e) => setOldPassword(e.currentTarget.value)}
            error={errors.old}
            autoComplete="current-password"
          />
          <PasswordInput
            label={st.newPassword}
            value={newPassword}
            onChange={(e) => setNewPassword(e.currentTarget.value)}
            error={errors.new}
            autoComplete="new-password"
          />
          <PasswordInput
            label={st.confirmPassword}
            value={confirm}
            onChange={(e) => setConfirm(e.currentTarget.value)}
            error={errors.confirm}
            autoComplete="new-password"
          />
          {help.length > 0 && (
            <div>
              <Text size="sm" fw={500}>
                {st.passwordRules}
              </Text>
              <List size="sm" c="dimmed">
                {help.map((line) => (
                  <List.Item key={line}>{line}</List.Item>
                ))}
              </List>
            </div>
          )}
          <Group justify="flex-end">
            <Button type="submit" loading={mutation.isPending}>
              {st.changePassword}
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function OtpCard({ status }: { status: authApi.SecurityStatus }) {
  const queryClient = useQueryClient();
  const { refresh } = useAuth();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [disableOpen, setDisableOpen] = useState(false);

  async function afterChange() {
    await queryClient.invalidateQueries({ queryKey: SECURITY_QUERY_KEY });
    // otp_setup_required ve otp_enabled `me` içinde: kullanıcı sayfadan çıkabilsin.
    await refresh();
  }

  return (
    <Card withBorder>
      <Stack>
        <Group justify="space-between">
          <Title order={4}>{st.otpTitle}</Title>
          <Badge color={status.otp_enabled ? "green" : "gray"} size="lg">
            {status.otp_enabled ? st.otpOn : st.otpOff}
          </Badge>
        </Group>
        <Text size="sm">{st.otpIntro}</Text>
        {status.otp_enabled ? (
          <>
            <Text size="sm">{st.recoveryRemaining(status.recovery_codes_remaining)}</Text>
            {status.recovery_codes_remaining <= 2 && (
              <Text size="sm" c="orange">
                {st.recoveryLow}
              </Text>
            )}
            <Group>
              <Button variant="light" onClick={() => setRegenerateOpen(true)}>
                {st.newRecoveryCodes}
              </Button>
              {!status.otp_required && (
                <Button variant="light" color="red" onClick={() => setDisableOpen(true)}>
                  {st.disable}
                </Button>
              )}
            </Group>
            {status.otp_required && (
              <Text size="sm" c="dimmed">
                {st.cannotDisable}
              </Text>
            )}
          </>
        ) : (
          <OtpSetup
            onDone={async (recovery) => {
              setCodes(recovery);
              notifications.show({ color: "green", message: st.otpEnabled });
              await afterChange();
            }}
          />
        )}
      </Stack>
      <RegenerateModal
        opened={regenerateOpen}
        onClose={() => setRegenerateOpen(false)}
        onDone={async (recovery) => {
          setRegenerateOpen(false);
          setCodes(recovery);
          await afterChange();
        }}
      />
      <DisableModal
        opened={disableOpen}
        onClose={() => setDisableOpen(false)}
        onDone={async () => {
          setDisableOpen(false);
          notifications.show({ color: "green", message: st.disabled });
          await afterChange();
        }}
      />
      <RecoveryCodesModal codes={codes} onClose={() => setCodes(null)} />
    </Card>
  );
}

function OtpSetup({ onDone }: { onDone: (codes: string[]) => Promise<void> }) {
  const [code, setCode] = useState("");
  const [codeError, setCodeError] = useState<string>();
  const setup = useMutation({ mutationFn: () => authApi.startOtpSetup() });
  const confirm = useMutation({
    mutationFn: (value: string) => authApi.confirmOtpSetup(value),
    onSuccess: async (data) => {
      setCode("");
      setup.reset();
      await onDone(data.recovery_codes);
    },
  });

  if (!setup.data) {
    return (
      <Stack align="flex-start">
        <ErrorAlert error={setup.error} />
        <Button onClick={() => setup.mutate()} loading={setup.isPending}>
          {st.setup}
        </Button>
      </Stack>
    );
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const value = code.replace(/\s+/g, "");
    setCodeError(value ? undefined : st.codeRequired);
    if (value) confirm.mutate(value);
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <Stack>
        <List type="ordered" size="sm">
          {st.setupSteps.map((step) => (
            <List.Item key={step}>{step}</List.Item>
          ))}
        </List>
        <Image src={svgDataUrl(setup.data.qr_svg)} alt={st.qrAlt} w={200} h={200} fit="contain" />
        <div>
          <Text size="sm">{st.manualKey}</Text>
          <Text ff="monospace" fz="lg" data-testid="otp-secret">
            {groupSecret(setup.data.secret)}
          </Text>
        </div>
        <ErrorAlert error={confirm.error} />
        <TextInput
          label={st.code}
          value={code}
          onChange={(e) => setCode(e.currentTarget.value)}
          error={codeError}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={16}
          maw={240}
        />
        <Group>
          <Button type="submit" loading={confirm.isPending}>
            {st.confirm}
          </Button>
          <Button variant="default" onClick={() => setup.reset()} disabled={confirm.isPending}>
            {st.cancel}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

function RegenerateModal({
  opened,
  onClose,
  onDone,
}: {
  opened: boolean;
  onClose: () => void;
  onDone: (codes: string[]) => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const mutation = useMutation({
    mutationFn: (value: string) => authApi.regenerateRecoveryCodes(value),
    onSuccess: async (data) => {
      setCode("");
      await onDone(data.recovery_codes);
    },
  });
  function close() {
    setCode("");
    mutation.reset();
    onClose();
  }
  return (
    <Modal opened={opened} onClose={close} title={st.newRecoveryCodes}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (code.trim()) mutation.mutate(code.trim());
        }}
        noValidate
      >
        <Stack>
          <Text size="sm">{st.newRecoveryIntro}</Text>
          <ErrorAlert error={mutation.error} />
          <TextInput
            label={st.code}
            value={code}
            onChange={(e) => setCode(e.currentTarget.value)}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={16}
            data-autofocus
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              {st.cancel}
            </Button>
            <Button type="submit" loading={mutation.isPending} disabled={!code.trim()}>
              {st.create}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function DisableModal({
  opened,
  onClose,
  onDone,
}: {
  opened: boolean;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: (value: string) => authApi.disableOtp(value),
    onSuccess: async () => {
      setPassword("");
      await onDone();
    },
  });
  function close() {
    setPassword("");
    mutation.reset();
    onClose();
  }
  return (
    <Modal opened={opened} onClose={close} title={st.disableTitle}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (password) mutation.mutate(password);
        }}
        noValidate
      >
        <Stack>
          <Text size="sm">{st.disableIntro}</Text>
          <ErrorAlert error={mutation.error} />
          <PasswordInput
            label={st.password}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            autoComplete="current-password"
            data-autofocus
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              {st.cancel}
            </Button>
            <Button type="submit" color="red" loading={mutation.isPending} disabled={!password}>
              {st.disable}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function SessionCard({ status }: { status: authApi.SecurityStatus }) {
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={4}>{st.sessionTitle}</Title>
        <Text>{st.idleTimeout(idleMinutes(status.idle_timeout_seconds))}</Text>
        <Text size="sm" c="dimmed">
          {st.idleHelp}
        </Text>
        <Group gap="xs">
          <IconDeviceTablet size={18} />
          <Text size="sm">{status.field_device ? st.fieldDevice : st.notFieldDevice}</Text>
        </Group>
      </Stack>
    </Card>
  );
}
