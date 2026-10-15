from typing import Any

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.roles import ALL_ROLES


def seed_roles() -> list[str]:
    """CLAUDE.md §5'teki rolleri `Group` olarak oluşturur (idempotent); yenileri döner."""
    created = []
    for role in ALL_ROLES:
        _, was_created = Group.objects.get_or_create(name=role)
        if was_created:
            created.append(role)
    return created


class Command(BaseCommand):
    help = "Sistem rollerini (Django Group) oluşturur. Tekrar çalıştırmak güvenlidir."

    def handle(self, *args: Any, **options: Any) -> None:
        created = seed_roles()
        existing = len(ALL_ROLES) - len(created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Roller hazır: {len(created)} yeni, {existing} zaten vardı."
                + (f" Yeni: {', '.join(created)}" if created else "")
            )
        )
