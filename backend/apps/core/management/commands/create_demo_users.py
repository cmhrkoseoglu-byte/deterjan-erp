from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.management.commands.seed_roles import seed_roles
from apps.core.models import User
from apps.core.roles import ADMIN, ALL_ROLES, ROLE_LABELS
from apps.core.services import save_with_audit, set_user_roles


class Command(BaseCommand):
    help = (
        "Her rol için bir demo kullanıcı oluşturur (kullanıcı adı = rol kodu). "
        "Yalnızca geliştirme ortamında (DEBUG=True) çalışır; şifre DEMO_USER_PASSWORD'dan gelir."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError(
                "Demo kullanıcılar yalnızca geliştirme ortamında (DEBUG=True) oluşturulur."
            )
        password = settings.DEMO_USER_PASSWORD
        if not password:
            raise CommandError(".env dosyasında DEMO_USER_PASSWORD tanımlı değil.")

        seed_roles()
        with transaction.atomic():
            for role in ALL_ROLES:
                user = User.objects.filter(username=role).first() or User(username=role)
                user.full_name = f"Demo {ROLE_LABELS[role]}"
                user.email = f"{role}@demo.local"
                user.is_active = True
                # Demo admin Django yönetim paneline de girebilsin.
                user.is_staff = user.is_superuser = role == ADMIN
                user.set_password(password)
                created = user._state.adding
                save_with_audit(user, None, note="create_demo_users")
                set_user_roles(user, [role], None, note="create_demo_users")
                self.stdout.write(f"{'Oluşturuldu' if created else 'Güncellendi'}: {role}")
        self.stdout.write(self.style.SUCCESS(f"{len(ALL_ROLES)} demo kullanıcı hazır."))
