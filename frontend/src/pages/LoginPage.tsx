import {
  Alert,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { getErrorMessage } from "../api/client";
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

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (isLoading) return <LoadingScreen />;
  if (user) return <Navigate to={next} replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const errors = {
      username: username.trim() ? undefined : tr.auth.usernameRequired,
      password: password ? undefined : tr.auth.passwordRequired,
    };
    setFieldErrors(errors);
    if (errors.username || errors.password) return;

    setSubmitting(true);
    setError(null);
    try {
      await login({ username: username.trim(), password });
      navigate(next, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
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
            {error && (
              <Alert color="red" icon={<IconAlertCircle size={18} />} role="alert">
                {error}
              </Alert>
            )}
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
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
