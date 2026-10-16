"""Kimlik doğrulama arka ucu: kilitli kullanıcı adıyla şifre denenmez (API ve yönetim paneli)."""

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.core import security


class LockoutModelBackend(ModelBackend):
    """`ModelBackend` + hesap kilidi. Kilitliyken doğru şifre de reddedilir; hatalı denemeler
    `user_login_failed` sinyaliyle sayılır (`core.signals`)."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if username is not None and security.is_locked(username):
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)
