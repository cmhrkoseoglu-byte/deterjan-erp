"""Tedarikçi carilerini 20.11.2026 itibarıyla sıfırlar (DECISIONS 2026-11-20).

Varsayılan kuru çalıştırmadır: kapatılacak bakiyeleri listeler, kayıt yazmaz. `--apply` ile her
tedarikçi ve para birimi için 19.11.2026 tarihli devir sıfırlama kaydı yazılır. Tekrar
çalıştırmak güvenlidir (bakiyesi sıfır olana yazılmaz).
"""

from datetime import date
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.models import User
from apps.ledger import services
from apps.ledger.notices import SUPPLIER_CLOSING_DATE


class Command(BaseCommand):
    help = "Tedarikçi cari bakiyelerini devir sıfırlama kaydıyla kapatır (varsayılan: kuru)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--user", required=True, help="Kaydı yazan kullanıcı adı")
        parser.add_argument(
            "--as-of",
            default=SUPPLIER_CLOSING_DATE.isoformat(),
            help="Kapanış tarihi (YYYY-AA-GG, bu gün dahil bakiye kapatılır)",
        )
        parser.add_argument("--apply", action="store_true", help="Kayıtları yaz")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            actor = User.objects.get(username=options["user"], is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError("Kullanıcı bulunamadı ya da pasif.") from exc
        try:
            as_of = date.fromisoformat(options["as_of"])
        except ValueError as exc:
            raise CommandError("Tarih YYYY-AA-GG biçiminde olmalı.") from exc
        closings = services.supplier_closings(as_of)
        for item in closings:
            side = "borç" if item.direction == services.DEBIT else "alacak"
            self.stdout.write(
                f"{item.supplier.code} {item.supplier.name} {item.currency}: "
                f"bakiye {item.balance} → {side} {abs(item.balance)}"
            )
        if not options["apply"]:
            self.stdout.write(f"Kuru çalıştırma: {len(closings)} kayıt yazılacak (--apply).")
            return
        written = services.close_supplier_balances(actor, as_of=as_of)
        numbers = ", ".join(entry.number for entry in written)
        self.stdout.write(self.style.SUCCESS(f"{len(written)} kayıt yazıldı. {numbers}"))
