import { Alert, Button, Group, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import {
  IconAlertCircle,
  IconBottle,
  IconClockPause,
  IconFlask2,
  IconLock,
  IconPackageImport,
  IconShieldLock,
  IconTruckDelivery,
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

const CHAIN_ICONS = [IconPackageImport, IconFlask2, IconBottle, IconTruckDelivery];

/** Marka panelindeki köpük kabarcıkları (konum ve boyut, px). */
const BUBBLES = [
  { size: 420, right: -140, top: -120 },
  { size: 220, right: 90, bottom: 60 },
  { size: 90, right: 40, top: 300 },
  { size: 140, left: -50, bottom: -40 },
  { size: 46, right: 200, top: 440 },
];

/** Geniş ekranda soldaki tanıtım paneli; süs olduğu için ekran okuyucudan gizli. */
function BrandPanel() {
  return (
    <aside className={classes.brand} aria-hidden="true">
      {BUBBLES.map(({ size, ...pos }, i) => (
        <span key={i} className={classes.bubble} style={{ width: size, height: size, ...pos }} />
      ))}
      <div className={classes.brandTop}>
        <div className={classes.wordmark}>
          <BrandMark size={40} inverse />
          <span className={classes.wordmarkName}>{tr.brand.name}</span>
          <span className={classes.wordmarkTag}>{tr.brand.tag}</span>
        </div>
        <p className={classes.headline}>{tr.auth.brandHeadline}</p>
        <p className={classes.lead}>{tr.auth.brandLead}</p>
      </div>
      <ol className={classes.chain}>
        {tr.auth.chain.map((step, i) => {
          const Icon = CHAIN_ICONS[i];
          return (
            <li key={step.title} className={classes.step}>
              <span className={classes.stepIcon}>
                <Icon size={22} stroke={1.6} />
              </span>
              <span>
                <span className={classes.stepTitle}>{step.title}</span>
                <span className={classes.stepHint}>{step.hint}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <div className={classes.brandFoot}>
        {tr.appName} · {tr.auth.brandFoot}
      </div>
    </aside>
  );
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
      <BrandPanel />
      <main className={classes.formSide}>
        <div className={classes.formBox}>
          <div className={classes.compactBrand}>
            <BrandMark size={34} />
            <span className={classes.compactName}>{tr.brand.name}</span>
            <span className={classes.compactTag}>{tr.brand.tag}</span>
          </div>
          <form onSubmit={handleSubmit} noValidate>
            <Stack gap="lg">
              {otpStep ? (
                <div>
                  <Group gap="xs" wrap="nowrap" mb={6}>
                    <IconShieldLock size={26} stroke={1.6} />
                    <Title order={1} fz={26}>
                      {tr.auth.otpTitle}
                    </Title>
                  </Group>
                  <Text c="dimmed">{tr.auth.otpIntro}</Text>
                </div>
              ) : (
                <div>
                  <Title order={1} fz={28} mb={6}>
                    {tr.auth.loginTitle}
                  </Title>
                  <Text c="dimmed">{tr.auth.loginSubtitle}</Text>
                </div>
              )}
              {expired && !error && !otpStep && (
                <Alert color="blue" variant="light" icon={<IconClockPause size={18} />}>
                  {tr.auth.sessionExpired}
                </Alert>
              )}
              {error && (
                <Alert
                  color="red"
                  variant="light"
                  icon={<IconAlertCircle size={18} />}
                  role="alert"
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
                    styles={{
                      input: { letterSpacing: "0.2em", fontVariantNumeric: "tabular-nums" },
                    }}
                  />
                  <Text size="sm" c="dimmed">
                    {tr.auth.otpRecoveryHint}
                  </Text>
                  <Button type="submit" size="lg" loading={submitting} fullWidth>
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
                    spellCheck={false}
                    size="lg"
                    leftSection={<IconUser size={18} stroke={1.6} />}
                    autoFocus
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
                    styles={{ description: { color: "var(--mantine-color-orange-filled)" } }}
                  />
                  <Button type="submit" size="lg" loading={submitting} fullWidth mt="xs">
                    {tr.auth.submit}
                  </Button>
                </>
              )}
            </Stack>
          </form>
          <Text size="sm" c="dimmed" className={classes.formFoot}>
            {tr.auth.forgotHint}
          </Text>
        </div>
      </main>
    </div>
  );
}
