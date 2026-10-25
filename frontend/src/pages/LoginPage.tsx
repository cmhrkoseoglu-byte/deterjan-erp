import { IconEye, IconEyeOff } from "@tabler/icons-react";
import { memo, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { getErrorCode, getErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { safeAppPath } from "../auth/safePath";
import { LoadingScreen } from "../components/LoadingScreen";
import { InncosLogo } from "../components/brand/InncosLogo";
import { tr } from "../i18n/tr";
import c from "./login/login.module.css";
import { startSlideshow } from "./login/slideshow";

/*
 * Giriş ekranı: PET Üretim Takip projesinin giriş ekranı gibi (templates/registration/login.html).
 * Arka planda ürün fotoğrafları kendiliğinden geçer; kart, yazı, düğme ve alt bant renkleri her
 * fotoğrafın baskın tonlarından hesaplanır (login/slideshow.ts).
 * Slaytlar ve denetimleri betiğe aittir: React onları bir kez çizer, sonra dokunmaz.
 */

/** Arka plan fotoğrafları (public/giris/; ilki betiksiz de görünür, CSS varsayılanları onun paleti). */
const SLIDES = [
  "01-mavi-siseler",
  "02-seftali-bidon",
  "03-tas-bidon",
  "04-deterjan-havlu",
  "05-pompali-siseler",
  "07-krem-pompa",
].map((name) => `/giris/${name}.webp`);

/** "Beni hatırla": yalnızca kullanıcı adı bu tarayıcıda saklanır; şifre asla saklanmaz. */
const REMEMBER_KEY = "inncosKullaniciAdi";

function readRemembered(): string {
  try {
    return window.localStorage.getItem(REMEMBER_KEY) ?? "";
  } catch {
    return ""; // gizli pencere ya da kapalı site verisi
  }
}

function writeRemembered(value: string) {
  try {
    if (value) window.localStorage.setItem(REMEMBER_KEY, value);
    else window.localStorage.removeItem(REMEMBER_KEY);
  } catch {
    // saklanamazsa yalnızca hatırlanmaz
  }
}

const cx = (...names: (string | false | undefined)[]) => names.filter(Boolean).join(" ");

/** Yalnızca uygulama içi yollara dönüş (açık yönlendirmeyi önler); geçersiz adreste ana sayfa. */
function safeNext(next: string | null): string {
  return safeAppPath(next) ?? "/";
}

/** Slayt katmanları: süs, ekran okuyucudan gizli. Betik sınıf ve renklerini değiştirir. */
const Slides = memo(function Slides() {
  return (
    <>
      <div className={c.slides} aria-hidden="true">
        {SLIDES.map((src, i) => (
          <div key={src} className={cx(c.slide, i === 0 && c["is-active"])}>
            <img className={c["slide-image"]} src={src} alt="" decoding="async" />
          </div>
        ))}
      </div>
      <div className={c["slide-curtain"]} aria-hidden="true" />
    </>
  );
});

/** Otomatik geçen arka plan için duraklatma zorunludur (WCAG 2.2.2); noktaları betik ekler. */
const SlideControls = memo(function SlideControls() {
  return (
    <div className={c["slide-controls"]} hidden>
      <button
        type="button"
        className={c["slide-toggle"]}
        aria-pressed="false"
        aria-label={tr.auth.slidePause}
        title={tr.auth.slidePause}
      >
        <svg
          className={c["icon-pause"]}
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <rect x="6" y="4" width="4" height="16" rx="1" />
          <rect x="14" y="4" width="4" height="16" rx="1" />
        </svg>
        <svg
          className={c["icon-play"]}
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z" />
        </svg>
      </button>
      <div className={c["slide-dots"]} role="group" aria-label={tr.auth.slideImages} />
    </div>
  );
});

function LoginScreen({ next, expired }: { next: string; expired: boolean }) {
  const { login } = useAuth();
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const [remembered] = useState(readRemembered);
  const [username, setUsername] = useState(remembered);
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(Boolean(remembered));
  const [showPassword, setShowPassword] = useState(false);
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

  useEffect(() => (rootRef.current ? startSlideshow(rootRef.current) : undefined), []);

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
    writeRemembered(remember ? username.trim() : "");
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

  const submitButton = (label: string) => (
    <button
      type="submit"
      className={cx(c["submit-button"], submitting && c["is-loading"])}
      disabled={submitting}
    >
      <span className={c.spinner} aria-hidden="true" />
      <span className={c["submit-label"]}>{submitting ? tr.auth.submitting : label}</span>
    </button>
  );

  return (
    <div ref={rootRef} className={cx(c["login-page"], c["has-slides"])}>
      <h1 className={c["login-sr-only"]}>{tr.auth.pageTitle}</h1>
      <Slides />
      <div className={c.brand} aria-hidden="true">
        {/* Inncos logosu; rengi fotoğrafa göre: açık zeminde lacivert, koyuda beyaz (--lp-brand). */}
        <InncosLogo part="mark" className={c["brand-mark"]} />
        <span className={c["brand-name"]}>
          <InncosLogo part="wordmark" className={c["brand-word"]} />
          <span className={c["brand-tag"]}>{tr.brand.tag}</span>
        </span>
      </div>

      <div className={c["page-wrap"]}>
        <main className={c.stage}>
          <div className={c.card}>
            <div className={c["form-panel"]}>
              <div className={c["form-head"]}>
                <h2 className={c["form-title"]}>
                  {otpStep ? tr.auth.otpTitle : tr.auth.loginTitle}
                </h2>
                <p className={c["form-subtitle"]}>
                  {otpStep ? tr.auth.otpIntro : tr.auth.loginSubtitle}
                </p>
              </div>

              {expired && !error && !otpStep && (
                <div className={cx(c.notice, c["is-info"])} role="status">
                  {tr.auth.sessionExpired}
                </div>
              )}
              {error && (
                <div className={cx(c.notice, c["is-error"])} role="alert">
                  {error}
                </div>
              )}

              <form onSubmit={handleSubmit} noValidate>
                {otpStep ? (
                  <>
                    <div className={c.field}>
                      <label className={c["field-label"]} htmlFor="login-otp">
                        {tr.auth.otpCode}
                      </label>
                      <div className={c["field-wrap"]}>
                        <input
                          id="login-otp"
                          className={cx(c["field-input"], c["is-code"])}
                          value={otpCode}
                          onChange={(e) => setOtpCode(e.currentTarget.value)}
                          inputMode="numeric"
                          autoComplete="one-time-code"
                          autoCapitalize="none"
                          maxLength={16}
                          autoFocus
                          aria-invalid={fieldErrors.otp ? true : undefined}
                          aria-describedby={fieldErrors.otp ? "login-otp-error" : undefined}
                        />
                      </div>
                      {fieldErrors.otp && (
                        <p id="login-otp-error" className={c["field-error"]}>
                          {fieldErrors.otp}
                        </p>
                      )}
                      <p className={cx(c["field-hint"], c["is-secondary"])}>
                        {tr.auth.otpRecoveryHint}
                      </p>
                    </div>
                    {submitButton(tr.auth.otpSubmit)}
                    <button
                      type="button"
                      className={c["back-button"]}
                      onClick={backToPassword}
                      disabled={submitting}
                    >
                      {tr.auth.otpBack}
                    </button>
                  </>
                ) : (
                  <>
                    <div className={c.field}>
                      <label className={c["field-label"]} htmlFor="login-username">
                        {tr.auth.username}
                      </label>
                      <div className={c["field-wrap"]}>
                        <input
                          id="login-username"
                          className={c["field-input"]}
                          type="text"
                          value={username}
                          onChange={(e) => setUsername(e.currentTarget.value)}
                          maxLength={150}
                          autoComplete="username"
                          autoCapitalize="none"
                          spellCheck={false}
                          placeholder={tr.auth.usernamePlaceholder}
                          autoFocus={!remembered}
                          aria-invalid={fieldErrors.username ? true : undefined}
                          aria-describedby={
                            fieldErrors.username ? "login-username-error" : undefined
                          }
                        />
                      </div>
                      {fieldErrors.username && (
                        <p id="login-username-error" className={c["field-error"]}>
                          {fieldErrors.username}
                        </p>
                      )}
                    </div>

                    <div className={c.field}>
                      <label className={c["field-label"]} htmlFor="login-password">
                        {tr.auth.password}
                      </label>
                      <div className={c["field-wrap"]}>
                        <input
                          ref={passwordRef}
                          id="login-password"
                          className={cx(c["field-input"], c["with-button"])}
                          type={showPassword ? "text" : "password"}
                          value={password}
                          onChange={(e) => setPassword(e.currentTarget.value)}
                          onKeyDown={trackCapsLock}
                          onKeyUp={trackCapsLock}
                          onBlur={() => setCapsLock(false)}
                          autoComplete="current-password"
                          placeholder="••••••••"
                          autoFocus={Boolean(remembered)}
                          aria-invalid={fieldErrors.password ? true : undefined}
                          aria-describedby={
                            fieldErrors.password ? "login-password-error" : undefined
                          }
                        />
                        <button
                          type="button"
                          className={c["reveal-button"]}
                          aria-label={showPassword ? tr.auth.hidePassword : tr.auth.showPassword}
                          aria-pressed={showPassword}
                          title={showPassword ? tr.auth.hidePassword : tr.auth.showPassword}
                          onClick={() => {
                            setShowPassword((value) => !value);
                            passwordRef.current?.focus();
                          }}
                        >
                          <IconEye className={c["eye-open"]} size={18} aria-hidden="true" />
                          <IconEyeOff className={c["eye-closed"]} size={18} aria-hidden="true" />
                        </button>
                      </div>
                      {fieldErrors.password && (
                        <p id="login-password-error" className={c["field-error"]}>
                          {fieldErrors.password}
                        </p>
                      )}
                      {capsLock && (
                        <p className={c["field-hint"]} role="status">
                          {tr.auth.capsLock}
                        </p>
                      )}
                    </div>

                    <div className={c["field-row"]}>
                      {/* Yalnızca kullanıcı adı bu tarayıcıda saklanır; ortak tablette işaretlemeyin. */}
                      <label className={c.remember}>
                        <input
                          type="checkbox"
                          checked={remember}
                          onChange={(e) => setRemember(e.currentTarget.checked)}
                        />
                        <span>{tr.auth.rememberMe}</span>
                      </label>
                    </div>

                    {submitButton(tr.auth.submit)}
                  </>
                )}
              </form>

              <p className={c.footnote}>{tr.auth.forgotHint}</p>
            </div>
          </div>
        </main>

        <footer className={c["footer-band"]}>
          <SlideControls />
          <p className={c["footer-text"]}>
            <span>{tr.appName}</span>
            <span className={c["dot-sep"]}>&middot;</span>
            <span>{tr.auth.brandFoot}</span>
            <span className={c["dot-sep"]}>&middot;</span>
            <span>&copy; {new Date().getFullYear()}</span>
          </p>
        </footer>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { user, isLoading } = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const expired = params.get("reason") === "expired";

  if (isLoading) return <LoadingScreen />;
  if (user) return <Navigate to={next} replace />;
  return <LoginScreen next={next} expired={expired} />;
}
