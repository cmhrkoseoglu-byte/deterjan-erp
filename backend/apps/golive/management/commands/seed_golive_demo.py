"""Canlıya geçiş demo verisi (Faz 5, Adım 5.6): bugünkü stoktan hazırlanmış, iki satırı bilerek
farklı bir "Excel" stok listesiyle bir paralel çalışma karşılaştırması. `seed_demo` sonunda
çağrılır; bugün için karşılaştırma varsa yenisini açmaz."""

import io
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from openpyxl import Workbook

from apps.core.models import User
from apps.core.roles import DEPO
from apps.golive import selectors, services
from apps.golive.models import StockComparison
from apps.masterdata.models import Material


class Command(BaseCommand):
    help = "Canlıya geçiş demo verisi: örnek stok karşılaştırması."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Demo verisi yalnızca geliştirme ortamında (DEBUG=True) yüklenir.")
        today = timezone.localdate()
        if StockComparison.objects.filter(as_of_date=today).exists():
            self.stdout.write("Bugün için stok karşılaştırması zaten var.")
            return
        stock = selectors.system_stock(services.end_of_day(today), by_lot=False, by_location=False)
        if not stock:
            self.stdout.write("Stok yok; karşılaştırma açılmadı.")
            return
        codes = dict(
            Material.objects.filter(pk__in=[k.material_id for k in stock]).values_list("pk", "code")
        )
        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.append(["Malzeme kodu", "Miktar"])
        rows = sorted(stock.items(), key=lambda item: codes[item[0].material_id])
        for index, (key, quantity) in enumerate(rows):
            # İki satır bilerek farklı: biri eksik sayılmış, biri Excel'e hiç yazılmamış.
            if index == 1:
                continue
            if index == 0:
                quantity = quantity - Decimal("12.5")
            sheet.append([codes[key.material_id], str(quantity)])
        buffer = io.BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        comparison = services.create_stock_comparison(
            User.objects.get(username=DEPO),
            upload=buffer,
            filename="stok-listesi-hafta-1.xlsx",
            note="Paralel çalışma 1. hafta (demo)",
        )
        self.stdout.write(
            f"Stok karşılaştırması {comparison.number}: {comparison.difference_count} fark."
        )
