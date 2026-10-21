"""Canlı sunucuda ilk yönetici hesabı (kurulum betiği çalıştırır, docs/KURULUM.md).

Şifre `FIRST_ADMIN_PASSWORD` ortam değişkeninden okunur (komut satırında görünmesin diye). Sistemde
zaten bir superuser varsa hiçbir şey yapmaz; böylece betik tekrar çalıştırıldığında şifre değişmez.
İlk girişte iki aşamalı doğrulama kurulumu istenir (`OTP_REQUIRED_ROLES`).
"""

import os
from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.core.management.commands.seed_roles import seed_roles
from apps.core.models import User
from apps.core.roles import ADMIN
from apps.core.services import save_with_audit, set_user_roles


class Command(BaseCommand):
    help = (
        "İlk yönetici hesabını açar (admin rolü + yönetim paneli). Şifre FIRST_ADMIN_PASSWORD "
        "ortam değişkeninden; bir superuser zaten varsa değişiklik yapmaz."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", default="yonetici")
        parser.add_argument("--full-name", default="Sistem Yöneticisi")

    def handle(self, *args: Any, **options: Any) -> None:
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("Yönetici hesabı zaten var; değişiklik yapılmadı.")
            return
        password = os.environ.get("FIRST_ADMIN_PASSWORD", "")
        username = options["username"]
        user = User(username=username, full_name=options["full_name"])
        try:
            password_validation.validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(
                "FIRST_ADMIN_PASSWORD uygun değil: " + " ".join(exc.messages)
            ) from exc

        seed_roles()
        with transaction.atomic():
            user.is_active = True
            user.is_staff = user.is_superuser = True
            user.set_password(password)
            save_with_audit(user, None, note="create_first_admin")
            set_user_roles(user, [ADMIN], None, note="create_first_admin")
        self.stdout.write(self.style.SUCCESS(f"Yönetici hesabı açıldı: {username}"))
