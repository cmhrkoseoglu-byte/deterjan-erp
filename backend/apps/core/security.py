"""Giriş güvenliği (Faz 5, Adım 5.5): hesap kilitleme, iki aşamalı doğrulama (TOTP), kurtarma
kodları, şifre değiştirme, saha tableti işareti ve hareketsizlik süresi.

Kurallar docs/DECISIONS.md "Giriş güvenliği" bölümündedir. Yazma işlemleri burada yapılır ve
denetim günlüğüne yazılır.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote, urlencode

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import password_validation
from django.contrib.auth.signals import user_login_failed
from django.db import transaction
from django.http import HttpRequest, HttpResponseBase
from django.utils import timezone

from apps.core import event_names, events
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, LoginLockout, RecoveryCode, TOTPDevice, User

TOTP_DIGITS = 6
TOTP_PERIOD = 30
# Saat kaymasına karşı bir önceki ve bir sonraki 30 saniyelik adım da kabul edilir.
TOTP_DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
FIELD_DEVICE_SALT = "core.field-device"


# --- hesap kilitleme ----------------------------------------------------------------------------


def _normalize(username: str) -> str:
    return (username or "").strip()[:150]


def lockout_minutes() -> int:
    return int(settings.LOGIN_LOCKOUT_MINUTES)


def is_locked(username: str) -> bool:
    """Kullanıcı adı şu an kilitli mi? (Var olmayan kullanıcı adları da kilitlenebilir.)"""
    username = _normalize(username)
    if not username:
        return False
    return LoginLockout.objects.filter(username=username, locked_until__gt=timezone.now()).exists()


def register_failed_login(username: str) -> LoginLockout | None:
    """Hatalı denemeyi sayar. `LOGIN_LOCKOUT_WINDOW_MINUTES` içinde `LOGIN_LOCKOUT_THRESHOLD`
    hataya ulaşılırsa hesap `LOGIN_LOCKOUT_MINUTES` kilitlenir; kilit denetim günlüğüne yazılır ve
    kullanıcı varsa `user.locked` olayı yayınlanır (admin'e bildirim). Kilitliyken gelen denemeler
    kilidi uzatmaz."""
    username = _normalize(username)
    if not username:
        return None
    now = timezone.now()
    window = timedelta(minutes=int(settings.LOGIN_LOCKOUT_WINDOW_MINUTES))
    with transaction.atomic():
        lockout, _ = LoginLockout.objects.select_for_update().get_or_create(username=username)
        if lockout.is_locked(now):
            return lockout
        if lockout.window_started_at is None or now - lockout.window_started_at > window:
            lockout.window_started_at = now
            lockout.failed_count = 0
        lockout.failed_count += 1
        newly_locked = lockout.failed_count >= int(settings.LOGIN_LOCKOUT_THRESHOLD)
        if newly_locked:
            lockout.locked_until = now + timedelta(minutes=lockout_minutes())
            lockout.failed_count = 0
            lockout.window_started_at = None
        lockout.save()
        if newly_locked and lockout.locked_until is not None:
            user = User.objects.filter(**{User.USERNAME_FIELD: username}).first()
            log_change(
                None,
                user,
                AuditLog.Action.CUSTOM,
                {"locked_until": [None, lockout.locked_until.isoformat()]},
                f"Hesap kilitlendi: {settings.LOGIN_LOCKOUT_THRESHOLD} hatalı giriş denemesi. "
                f"Kullanıcı adı: {username}",
            )
            if user is not None:
                events.publish(
                    event_names.USER_LOCKED,
                    {
                        "model": "core.user",
                        "id": user.pk,
                        "repr": str(user),
                        "user_id": user.pk,
                        "username": username,
                        "minutes": lockout_minutes(),
                        "locked_until": timezone.localtime(lockout.locked_until).strftime(
                            "%d.%m.%Y %H:%M"
                        ),
                    },
                )
    return lockout


def reset_failed_logins(username: str) -> None:
    """Başarılı girişte sayaç sıfırlanır."""
    LoginLockout.objects.filter(username=_normalize(username)).delete()


def unlock_user(actor: User, user: User) -> None:
    """Admin kilidi elle açar (denetimli)."""
    deleted, _ = LoginLockout.objects.filter(username=user.get_username()).delete()
    if not deleted:
        raise BusinessRuleError("not_locked", "Bu kullanıcının hesabı kilitli değil.")
    log_change(actor, user, AuditLog.Action.CUSTOM, note="Hesap kilidi elle açıldı")


def locked_usernames() -> set[str]:
    return set(
        LoginLockout.objects.filter(locked_until__gt=timezone.now()).values_list(
            "username", flat=True
        )
    )


# --- TOTP (RFC 6238) ----------------------------------------------------------------------------


def generate_secret() -> str:
    """160 bit rastgele anahtar, base32 (doğrulayıcı uygulamaların beklediği biçim)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _secret_bytes(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def totp_code(secret: str, step: int) -> str:
    """Verilen zaman adımı için 6 haneli kod (HMAC-SHA1, RFC 4226 kesme)."""
    digest = hmac.new(_secret_bytes(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // TOTP_PERIOD)


def _match_totp(device: TOTPDevice, code: str, at: float | None = None) -> int | None:
    """Kod geçerliyse eşleşen adımı döner; daha önce kullanılmış adım kabul edilmez."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != TOTP_DIGITS:
        return None
    now_step = current_step(at)
    for step in range(now_step - TOTP_DRIFT_STEPS, now_step + TOTP_DRIFT_STEPS + 1):
        if step > device.last_used_step and hmac.compare_digest(
            totp_code(device.secret, step), code
        ):
            return step
    return None


def provisioning_uri(user: User, secret: str) -> str:
    """Doğrulayıcı uygulamanın QR kodundan okuduğu `otpauth://` adresi."""
    issuer = settings.OTP_ISSUER
    label = quote(f"{issuer}:{user.get_username()}")
    query = urlencode(
        {"secret": secret, "issuer": issuer, "digits": TOTP_DIGITS, "period": TOTP_PERIOD}
    )
    return f"otpauth://totp/{label}?{query}"


def qr_svg(data: str) -> str:
    """Verilen metnin QR kodunu SVG olarak üretir (reportlab; ek bağımlılık yok)."""
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    widget = QrCodeWidget(data, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    size = 220
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(widget)
    return str(renderSVG.drawToString(drawing))


# --- iki aşamalı doğrulama ----------------------------------------------------------------------


def otp_required_for(user: User) -> bool:
    """Kullanıcının rolü iki aşamalı doğrulamayı zorunlu kılıyor mu? (`OTP_REQUIRED_ROLES`)"""
    required = set(settings.OTP_REQUIRED_ROLES)
    if not required:
        return False
    if "admin" in required and user.is_superuser:
        return True
    return user.has_role(*required)


def otp_enabled(user: User) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()


def otp_setup_required(user: User) -> bool:
    """Zorunlu olduğu halde kurulmamış: kullanıcı kurulum dışında hiçbir işlem yapamaz."""
    return otp_required_for(user) and not otp_enabled(user)


@dataclass(frozen=True)
class OtpSetup:
    secret: str
    uri: str
    qr_svg: str


@transaction.atomic
def start_otp_setup(actor: User) -> OtpSetup:
    """Yeni bir gizli anahtar üretir (kurulum onaylanana kadar geçersiz). Kurulu bir doğrulama
    varsa önce kapatılmalıdır."""
    device = TOTPDevice.objects.select_for_update().filter(user=actor).first()
    if device is not None and device.is_confirmed:
        raise BusinessRuleError(
            "otp_already_enabled", "İki aşamalı doğrulama zaten açık. Önce kapatmanız gerekir."
        )
    secret = generate_secret()
    if device is None:
        TOTPDevice.objects.create(user=actor, secret=secret)
    else:
        device.secret = secret
        device.last_used_step = 0
        device.save(update_fields=["secret", "last_used_step"])
    uri = provisioning_uri(actor, secret)
    return OtpSetup(secret=secret, uri=uri, qr_svg=qr_svg(uri))


def _hash_recovery_code(code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").lower()
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, normalized.encode(), hashlib.sha256).hexdigest()


def _new_recovery_codes(user: User) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = base64.b32encode(secrets.token_bytes(5)).decode("ascii").lower()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    RecoveryCode.objects.bulk_create(
        RecoveryCode(user=user, code_hash=_hash_recovery_code(code)) for code in codes
    )
    return codes


@transaction.atomic
def confirm_otp_setup(actor: User, code: str) -> list[str]:
    """Uygulamadaki ilk kodla kurulumu onaylar; kurtarma kodlarını (yalnızca bir kez) döner."""
    device = TOTPDevice.objects.select_for_update().filter(user=actor).first()
    if device is None:
        raise BusinessRuleError("otp_setup_not_started", "Önce kurulumu başlatın.")
    if device.is_confirmed:
        raise BusinessRuleError("otp_already_enabled", "İki aşamalı doğrulama zaten açık.")
    step = _match_totp(device, code)
    if step is None:
        raise BusinessRuleError(
            "invalid_otp", "Doğrulama kodu hatalı. Telefonun saatinin doğru olduğundan emin olun."
        )
    device.confirmed_at = timezone.now()
    device.last_used_step = step
    device.save(update_fields=["confirmed_at", "last_used_step"])
    codes = _new_recovery_codes(actor)
    log_change(actor, actor, AuditLog.Action.CUSTOM, note="İki aşamalı doğrulama açıldı")
    return codes


@transaction.atomic
def regenerate_recovery_codes(actor: User, code: str) -> list[str]:
    """Geçerli bir doğrulama koduyla yeni kurtarma kodları üretir (eskileri geçersiz olur)."""
    if not verify_second_factor(actor, code, allow_recovery=False):
        raise BusinessRuleError("invalid_otp", "Doğrulama kodu hatalı.")
    codes = _new_recovery_codes(actor)
    log_change(actor, actor, AuditLog.Action.CUSTOM, note="Kurtarma kodları yenilendi")
    return codes


@transaction.atomic
def disable_otp(actor: User, password: str) -> None:
    """Kullanıcı kendi iki aşamalı doğrulamasını kapatır (şifresiyle). Zorunlu rolde kapatılamaz."""
    if otp_required_for(actor):
        raise BusinessRuleError(
            "otp_required", "Rolünüz için iki aşamalı doğrulama zorunlu; kapatılamaz."
        )
    if not actor.check_password(password):
        raise BusinessRuleError("wrong_password", "Şifre hatalı.")
    deleted, _ = TOTPDevice.objects.filter(user=actor).delete()
    RecoveryCode.objects.filter(user=actor).delete()
    if deleted:
        log_change(actor, actor, AuditLog.Action.CUSTOM, note="İki aşamalı doğrulama kapatıldı")


@transaction.atomic
def reset_otp(actor: User, user: User) -> None:
    """Admin, telefonunu kaybeden kullanıcının doğrulamasını sıfırlar; kullanıcı bir sonraki
    girişte (rolü gerektiriyorsa) yeniden kurar."""
    deleted, _ = TOTPDevice.objects.filter(user=user).delete()
    RecoveryCode.objects.filter(user=user).delete()
    if not deleted:
        raise BusinessRuleError(
            "otp_not_enabled", "Bu kullanıcıda iki aşamalı doğrulama kurulu değil."
        )
    log_change(actor, user, AuditLog.Action.CUSTOM, note="İki aşamalı doğrulama sıfırlandı")


def verify_second_factor(user: User, code: str, *, allow_recovery: bool = True) -> bool:
    """Doğrulayıcı kodunu ya da (izinliyse) kullanılmamış bir kurtarma kodunu doğrular ve
    kullanılmış sayar."""
    code = (code or "").strip()
    if not code:
        return False
    with transaction.atomic():
        device = (
            TOTPDevice.objects.select_for_update()
            .filter(user=user, confirmed_at__isnull=False)
            .first()
        )
        if device is None:
            return False
        step = _match_totp(device, code)
        if step is not None:
            device.last_used_step = step
            device.save(update_fields=["last_used_step"])
            return True
        if not allow_recovery:
            return False
        recovery = (
            RecoveryCode.objects.select_for_update()
            .filter(user=user, used_at__isnull=True, code_hash=_hash_recovery_code(code))
            .first()
        )
        if recovery is None:
            return False
        recovery.used_at = timezone.now()
        recovery.save(update_fields=["used_at"])
        log_change(user, user, AuditLog.Action.CUSTOM, note="Kurtarma koduyla giriş yapıldı")
        return True


def remaining_recovery_codes(user: User) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def report_failed_second_factor(request: HttpRequest | None, username: str) -> None:
    """Hatalı doğrulama kodu başarısız giriş sayılır (denetim + kilit sayacı)."""
    user_login_failed.send(
        sender=__name__, credentials={"username": username, "otp": True}, request=request
    )


# --- şifre --------------------------------------------------------------------------------------


def change_password(
    request: HttpRequest, actor: User, old_password: str, new_password: str
) -> None:
    """Kullanıcı kendi şifresini değiştirir; oturum açık kalır (diğer oturumlar kapanır).
    Şifre politikası `AUTH_PASSWORD_VALIDATORS` ile uygulanır."""
    if not actor.check_password(old_password):
        raise BusinessRuleError("wrong_password", "Mevcut şifre hatalı.")
    try:
        password_validation.validate_password(new_password, actor)
    except Exception as exc:  # django.core.exceptions.ValidationError
        messages = getattr(exc, "messages", [str(exc)])
        raise BusinessRuleError("weak_password", " ".join(messages)) from exc
    actor.set_password(new_password)
    actor.save(update_fields=["password"])  # denetim: core.signals (şifre değişti)
    auth.update_session_auth_hash(request, actor)


# --- saha tableti ve hareketsizlik süresi -------------------------------------------------------


def is_field_device(request: HttpRequest) -> bool:
    """Bu tarayıcı admin tarafından saha tableti olarak işaretlenmiş mi? (imzalı çerez)"""
    value = request.get_signed_cookie(
        settings.FIELD_DEVICE_COOKIE, default=None, salt=FIELD_DEVICE_SALT
    )
    return value == "1"


def set_field_device(actor: User, response: HttpResponseBase, enabled: bool) -> None:
    """Tarayıcıyı saha tableti olarak işaretler ya da işareti kaldırır (yalnızca admin)."""
    if enabled:
        response.set_signed_cookie(
            settings.FIELD_DEVICE_COOKIE,
            "1",
            salt=FIELD_DEVICE_SALT,
            max_age=60 * 60 * 24 * 365 * 5,
            secure=settings.SESSION_COOKIE_SECURE,
            httponly=True,
            samesite="Lax",
        )
    else:
        response.delete_cookie(settings.FIELD_DEVICE_COOKIE, samesite="Lax")
    log_change(
        actor,
        actor,
        AuditLog.Action.CUSTOM,
        note="Cihaz saha tableti olarak işaretlendi"
        if enabled
        else "Saha tableti işareti kaldırıldı",
    )


def idle_timeout_seconds(request: HttpRequest) -> int:
    minutes = (
        settings.FIELD_DEVICE_IDLE_TIMEOUT_MINUTES
        if is_field_device(request)
        else settings.SESSION_IDLE_TIMEOUT_MINUTES
    )
    return int(minutes) * 60
