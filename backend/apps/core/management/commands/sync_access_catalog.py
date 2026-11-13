"""Yetki kataloğunun bu sürümdeki kopyasını saklar (docs/plan/kisi-yetkileri.md §5.2).

Canlıdaki göç servisi `seed_roles`'tan sonra çalıştırır; katalog değişmediyse bir şey yazmaz.
"""

from typing import Any

from django.core.management.base import BaseCommand

from apps.core import services


class Command(BaseCommand):
    help = "Yetki paketleri değiştiyse kataloğun kopyasını saklar ve denetim günlüğüne yazar."

    def handle(self, *args: Any, **options: Any) -> None:
        snapshot, created = services.sync_access_catalog()
        if created:
            self.stdout.write(f"Yetki paketlerinin yeni sürümü kaydedildi ({snapshot}).")
        else:
            self.stdout.write("Yetki paketleri değişmedi.")
