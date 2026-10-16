"""Şifre politikası doğrulayıcıları (Faz 5, Adım 5.5)."""

from typing import Any

from django.core.exceptions import ValidationError


class LetterAndDigitValidator:
    """Şifre en az bir harf ve en az bir rakam içermeli."""

    def validate(self, password: str, user: Any = None) -> None:
        if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
            raise ValidationError(
                "Şifre en az bir harf ve en az bir rakam içermelidir.", code="password_no_mix"
            )

    def get_help_text(self) -> str:
        return "Şifreniz en az bir harf ve en az bir rakam içermelidir."
