import {
  Alert,
  Button,
  Center,
  Group,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconClockPause, IconShieldLock } from "@tabler/icons-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { getErrorCode, getErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { LoadingScreen } from "../components/LoadingScreen";
import { tr } from "../i18n/tr";

/** Yalnızca uygulama içi yollara dönüş (açık yönlendirmeyi önler). */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

export function LoginPage() {
  const { user, isLoading, login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const expired = params.get("reason") === "expired";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // İki aşamalı doğrulama: şifre doğruysa ve 2FA kuruluysa sunucu otp_required döner.
  const [otpStep, setOtpStep] = useState(false);
  const [otpCode, setOtpCode] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{
    username?: string;
    password?: string;
    otp?: string;
  }>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (isLoading) return <LoadingScreen />;
  if (user) return <Navigate to={next} replace />;

  async function submit(payload: { username: string; password: string; otp_code?: string }) {
    setSubmitting(true);
    setError(null);
    try {
      await login(payload);
      navigate(next, { replace: true });
    } catch (err) {
      const code = getErrorCode(err);
      if (code === "otp_required") {
        setOtpStep(true);
      } else {
        // invalid_otp kod adımında kalır; account_locked ve diğerleri mesajı gösterir.
        setError(getErrorMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (otpStep) {
      const code = otpCode.trim();
      setFieldErrors({ otp: code ? undefined : tr.auth.otpCodeRequired });
      if (!code) return;
      await submit({ username: username.trim(), password, otp_code: code });
      return;
    }
    const errors = {
      username: username.trim() ? undefined : tr.auth.usernameRequired,
      password: password ? undefined : tr.auth.passwordRequired,
    };
    setFieldErrors(errors);
    if (errors.username || errors.password) return;
    await submit({ username: username.trim(), password });
  }

  function backToPassword() {
    setOtpStep(false);
    setOtpCode("");
    setPassword("");
    setError(null);
    setFieldErrors({});
  }

  return (
    <Center mih="100vh" p="md" bg="gray.0">
      <Paper withBorder shadow="sm" radius="md" p="xl" w="100%" maw={420}>
        <form onSubmit={handleSubmit} noValidate>
          <Stack gap="md">
            <div>
              <Title order={2}>{tr.appName}</Title>
              <Text c="dimmed">{tr.auth.loginSubtitle}</Text>
            </div>
            {expired && !error && !otpStep && (
              <Alert color="blue" icon={<IconClockPause size={18} />}>
                {tr.auth.sessionExpired}
              </Alert>
            )}
            {error && (
              <Alert color="red" icon={<IconAlertCircle size={18} />} role="alert">
                {error}
              </Alert>
            )}
            {otpStep ? (
              <>
                <Group gap="xs" wrap="nowrap">
                  <IconShieldLock size={22} />
                  <Text fw={600}>{tr.auth.otpTitle}</Text>
                </Group>
                <Text size="sm">{tr.auth.otpIntro}</Text>
                <TextInput
                  label={tr.auth.otpCode}
                  value={otpCode}
                  onChange={(e) => setOtpCode(e.currentTarget.value)}
                  error={fieldErrors.otp}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoCapitalize="none"
                  maxLength={16}
                  size="md"
                  autoFocus
                />
                <Text size="sm" c="dimmed">
                  {tr.auth.otpRecoveryHint}
                </Text>
                <Button type="submit" size="md" loading={submitting} fullWidth>
                  {tr.auth.otpSubmit}
                </Button>
                <Button variant="subtle" onClick={backToPassword} disabled={submitting}>
                  {tr.auth.otpBack}
                </Button>
              </>
            ) : (
              <>
                <TextInput
                  label={tr.auth.username}
                  value={username}
                  onChange={(e) => setUsername(e.currentTarget.value)}
                  error={fieldErrors.username}
                  autoComplete="username"
                  autoCapitalize="none"
                  size="md"
                  autoFocus
                />
                <PasswordInput
                  label={tr.auth.password}
                  value={password}
                  onChange={(e) => setPassword(e.currentTarget.value)}
                  error={fieldErrors.password}
                  autoComplete="current-password"
                  size="md"
                />
                <Button type="submit" size="md" loading={submitting} fullWidth>
                  {tr.auth.submit}
                </Button>
              </>
            )}
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
