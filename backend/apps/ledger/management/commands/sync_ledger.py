"""Sevk edilmiş sevkiyatları ve kaydedilmiş mal kabulleri cariye yazar ya da düzeltir.

Canlıya alışta geçmiş belgeler için bir kez çalıştırılır; tekrar çalıştırmak güvenlidir
(idempotent: belgenin bugünkü tutarı defterdekiyle aynıysa kayıt yazılmaz).
"""

from typing import Any

from django.core.management.base import BaseCommand

from apps.ledger import services


class Command(BaseCommand):
    help = "Sevkiyat ve mal kabulleri cari hesaplara eşitler (idempotent)."

    def handle(self, *args: Any, **options: Any) -> None:
        written = services.sync_all()
        self.stdout.write(self.style.SUCCESS(f"Cari eşitleme tamam: {written} kayıt yazıldı."))
