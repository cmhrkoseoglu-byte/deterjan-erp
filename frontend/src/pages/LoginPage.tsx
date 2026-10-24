import { Alert, Button, Group, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import {
  IconAlertCircle,
  IconClockPause,
  IconLock,
  IconShieldLock,
  IconUser,
} from "@tabler/icons-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { getErrorCode, getErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/brand/BrandMark";
import { LoadingScreen } from "../components/LoadingScreen";
import { tr } from "../i18n/tr";
import classes from "./LoginPage.module.css";

/** Yalnızca uygulama içi yollara dönüş (açık yönlendirmeyi önler). */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

/** Zeminde süzülen zincir sözcüklerinin yerleri (%), DentMesher girişindeki sözcükler gibi. */
const FLOATING = [
  { left: "6%", top: "18%" },
  { left: "72%", top: "9%" },
  { left: "80%", top: "58%" },
  { left: "10%", top: "70%" },
  { left: "44%", top: "88%" },
];

/** Alanlar ve düğmeler gece paletinde: giriş, temadan bağımsız olarak hep koyu kahve zemindedir. */
const FIELD = {
  root: classes.field,
  label: classes.fieldLabel,
  input: classes.fieldInput,
  section: classes.fieldSection,
  error: classes.fieldError,
  description: classes.fieldHint,
  innerInput: classes.fieldInner,
  visibilityToggle: classes.fieldToggle,
};

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
  const [capsLock, setCapsLock] = useState(false);

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

  /** Şifre alanında Caps Lock durumunu izler; açıkken alanın altında uyarı çıkar. */
  function trackCapsLock(event: KeyboardEvent<HTMLInputElement>) {
    setCapsLock(event.getModifierState?.("CapsLock") ?? false);
  }

  return (
    <div className={classes.root}>
      {/* Zemin süsü: ana zincirin sözcükleri yavaşça süzülür; ekran okuyucudan gizli. */}
      <div className={classes.scene} aria-hidden="true">
        {tr.auth.chain.map((word, i) => (
          <span key={word} className={classes.floating} style={FLOATING[i]}>
            {word}
          </span>
        ))}
      </div>
      <header className={classes.top}>
        <BrandMark size={30} inverse />
        <span className={classes.wordmark}>{tr.brand.wordmark}</span>
        <span className={classes.tag}>{tr.brand.tag}</span>
      </header>
      <main className={classes.center}>
        <div className={classes.card}>
          <form onSubmit={handleSubmit} noValidate>
            <Stack gap="lg">
              {otpStep ? (
                <div>
                  <Group gap="xs" wrap="nowrap" mb={6}>
                    <IconShieldLock size={26} stroke={1.6} className={classes.titleIcon} />
                    <Title order={1} className={classes.title}>
                      {tr.auth.otpTitle}
                    </Title>
                  </Group>
                  <Text className={classes.subtitle}>{tr.auth.otpIntro}</Text>
                </div>
              ) : (
                <div>
                  <Title order={1} className={classes.title} mb={6}>
                    {tr.auth.loginTitle}
                  </Title>
                  <Text className={classes.subtitle}>{tr.auth.loginSubtitle}</Text>
                </div>
              )}
              {expired && !error && !otpStep && (
                <Alert
                  variant="light"
                  icon={<IconClockPause size={18} />}
                  classNames={{ root: classes.notice, icon: classes.noticeIcon }}
                >
                  {tr.auth.sessionExpired}
                </Alert>
              )}
              {error && (
                <Alert
                  variant="light"
                  icon={<IconAlertCircle size={18} />}
                  role="alert"
                  classNames={{ root: classes.danger, icon: classes.dangerIcon }}
                >
                  {error}
                </Alert>
              )}
              {otpStep ? (
                <>
                  <TextInput
                    label={tr.auth.otpCode}
                    value={otpCode}
                    onChange={(e) => setOtpCode(e.currentTarget.value)}
                    error={fieldErrors.otp}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoCapitalize="none"
                    maxLength={16}
                    size="lg"
                    autoFocus
                    classNames={FIELD}
                    styles={{
                      input: { letterSpacing: "0.2em", fontVariantNumeric: "tabular-nums" },
                    }}
                  />
                  <Text size="sm" className={classes.subtitle}>
                    {tr.auth.otpRecoveryHint}
                  </Text>
                  <Button
                    type="submit"
                    size="lg"
                    loading={submitting}
                    fullWidth
                    className={classes.submit}
                  >
                    {tr.auth.otpSubmit}
                  </Button>
                  <Button
                    variant="subtle"
                    onClick={backToPassword}
                    disabled={submitting}
                    className={classes.back}
                  >
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
                    spellCheck={false}
                    size="lg"
                    leftSection={<IconUser size={18} stroke={1.6} />}
                    autoFocus
                    classNames={FIELD}
                  />
                  <PasswordInput
                    label={tr.auth.password}
                    value={password}
                    onChange={(e) => setPassword(e.currentTarget.value)}
                    onKeyDown={trackCapsLock}
                    onKeyUp={trackCapsLock}
                    onBlur={() => setCapsLock(false)}
                    error={fieldErrors.password}
                    description={capsLock ? tr.auth.capsLock : undefined}
                    inputWrapperOrder={["label", "input", "description", "error"]}
                    autoComplete="current-password"
                    size="lg"
                    leftSection={<IconLock size={18} stroke={1.6} />}
                    classNames={FIELD}
                  />
                  <Button
                    type="submit"
                    size="lg"
                    loading={submitting}
                    fullWidth
                    mt="xs"
                    className={classes.submit}
                  >
                    {tr.auth.submit}
                  </Button>
                </>
              )}
            </Stack>
          </form>
          <Text size="sm" className={classes.hint}>
            {tr.auth.forgotHint}
          </Text>
        </div>
      </main>
      <footer className={classes.foot}>
        {tr.appName} · {tr.auth.brandFoot}
      </footer>
    </div>
  );
}
