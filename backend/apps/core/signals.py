"""Django sinyal alıcıları: giriş/çıkış ve şifre değişikliklerini denetim günlüğüne yazar.

Sinyal kullanılmasının nedeni: API girişi, yönetim paneli girişi, panelden şifre değiştirme ve
`changepassword` komutu gibi tüm yollar tek noktadan denetlenir. `CoreConfig.ready()` bağlar.
"""

import time
from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.http import HttpRequest

from apps.core import event_names, events, security
from apps.core.audit import log_change
from apps.core.context import client_ip_from_request, get_current_user
from apps.core.models import AuditLog, User

MASKED = "***"


def _ip(request: HttpRequest | None) -> str | None:
    return client_ip_from_request(request) if request is not None else None


@receiver(user_logged_in, dispatch_uid="core_audit_login")
def audit_login(sender: Any, request: HttpRequest | None, user: Any, **kwargs: Any) -> None:
    if not isinstance(user, User):
        return
    security.reset_failed_logins(user.get_username())
    if request is not None and hasattr(request, "session"):
        # Hareketsizlik süresi girişten başlar (core.middleware).
        request.session["_last_activity"] = time.time()
    log_change(user, user, AuditLog.Action.LOGIN, ip_address=_ip(request))
    events.publish(event_names.USER_LOGGED_IN, {"user_id": user.pk}, user)


@receiver(user_logged_out, dispatch_uid="core_audit_logout")
def audit_logout(sender: Any, request: HttpRequest | None, user: Any, **kwargs: Any) -> None:
    if not isinstance(user, User):
        return  # giriş yapmamış kullanıcının çıkışı
    # Hareketsizlik nedeniyle kapanan oturumda neden not olarak yazılır (core.middleware).
    note = getattr(request, "_logout_reason", "") if request is not None else ""
    log_change(user, user, AuditLog.Action.LOGOUT, note=note, ip_address=_ip(request))
    events.publish(event_names.USER_LOGGED_OUT, {"user_id": user.pk}, user)


@receiver(user_login_failed, dispatch_uid="core_audit_login_failed")
def audit_login_failed(
    sender: Any, credentials: dict[str, Any], request: HttpRequest | None = None, **kwargs: Any
) -> None:
    username = str(credentials.get(User.USERNAME_FIELD, ""))[:150]
    known = User.objects.filter(**{User.USERNAME_FIELD: username}).first() if username else None
    reason = (
        "hatalı doğrulama kodu" if credentials.get("otp") else "hatalı şifre ya da kilitli hesap"
    )
    log_change(
        None,
        known,
        AuditLog.Action.LOGIN_FAILED,
        note=f"Başarısız giriş denemesi ({reason}). Kullanıcı adı: {username}",
        ip_address=_ip(request),
    )
    events.publish(event_names.USER_LOGIN_FAILED, {"username": username})
    security.register_failed_login(username)


@receiver(pre_save, sender=User, dispatch_uid="core_password_change_detect")
def detect_password_change(sender: Any, instance: User, **kwargs: Any) -> None:
    update_fields = kwargs.get("update_fields")
    instance._password_changed = False  # type: ignore[attr-defined]
    if instance._state.adding or (update_fields is not None and "password" not in update_fields):
        return
    old = User._base_manager.filter(pk=instance.pk).values_list("password", flat=True).first()
    instance._password_changed = old is not None and old != instance.password  # type: ignore[attr-defined]


@receiver(post_save, sender=User, dispatch_uid="core_password_change_audit")
def audit_password_change(sender: Any, instance: User, created: bool, **kwargs: Any) -> None:
    if created or not getattr(instance, "_password_changed", False):
        return
    instance._password_changed = False  # type: ignore[attr-defined]
    # Şifre özeti günlüğe yazılmaz; yalnızca değiştiği kaydedilir.
    log_change(
        get_current_user(),
        instance,
        AuditLog.Action.UPDATE,
        {"password": [MASKED, MASKED]},
        "Şifre değiştirildi",
    )
