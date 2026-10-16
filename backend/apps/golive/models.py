"""Canlıya geçiş (Faz 5, Adım 5.6): paralel çalışma stok karşılaştırması ve "Sorun bildir".

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` üzerinden yapılır.
"""

from django.db import models

from apps.core.models import BaseModel
from apps.masterdata.models import Location, Material


class StockComparison(BaseModel):
    """Paralel çalışma döneminde Excel stok listesi ile sistem bakiyesinin karşılaştırması (`SK-`).

    Kayıt değişmez; her hafta yeni karşılaştırma açılır.
    """

    class Level(models.TextChoices):
        MATERIAL = "MATERIAL", "Malzeme"
        LOCATION = "LOCATION", "Malzeme + lokasyon"
        LOT = "LOT", "Malzeme + lot"
        LOT_LOCATION = "LOT_LOCATION", "Malzeme + lot + lokasyon"

    number = models.CharField("numara", max_length=32, unique=True, editable=False)
    as_of_date = models.DateField("stok tarihi", help_text="Bu günün sonundaki sistem bakiyesi")
    level = models.CharField("karşılaştırma düzeyi", max_length=16, choices=Level.choices)
    only_file_materials = models.BooleanField(
        "yalnızca dosyadaki malzemeler",
        default=False,
        help_text="Seçilmezse sistemde stoğu olup dosyada olmayan malzemeler de listelenir.",
    )
    file_name = models.CharField("dosya adı", max_length=255)
    note = models.TextField("not", blank=True)
    line_count = models.PositiveIntegerField("satır sayısı", default=0)
    difference_count = models.PositiveIntegerField("farklı satır sayısı", default=0)

    class Meta:
        verbose_name = "stok karşılaştırması"
        verbose_name_plural = "stok karşılaştırmaları"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.number


class StockComparisonLine(models.Model):
    comparison = models.ForeignKey(
        StockComparison,
        verbose_name="karşılaştırma",
        on_delete=models.CASCADE,
        related_name="lines",
    )
    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="+"
    )
    lot_no = models.CharField("lot no", max_length=64, blank=True)
    location = models.ForeignKey(
        Location,
        verbose_name="lokasyon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    file_quantity = models.DecimalField("Excel miktarı", max_digits=18, decimal_places=4)
    system_quantity = models.DecimalField("sistem miktarı", max_digits=18, decimal_places=4)
    difference = models.DecimalField(
        "fark (sistem − Excel)", max_digits=18, decimal_places=4, db_index=True
    )
    in_file = models.BooleanField("dosyada var", default=True)

    class Meta:
        verbose_name = "stok karşılaştırma satırı"
        verbose_name_plural = "stok karşılaştırma satırları"
        ordering = ["material__code", "lot_no", "location__code", "id"]

    def __str__(self) -> str:
        return f"{self.comparison} {self.material.code} {self.difference}"


def problem_screenshot_upload_to(instance: "ProblemReport", filename: str) -> str:
    return f"sorun-bildirimleri/{instance.created_at:%Y/%m}/{filename}"


class ProblemReport(BaseModel):
    """Kullanıcının uygulama içinden bildirdiği sorun (`SB-`); admin rolüne görev açar.

    Ekran görüntüsü yalnızca bildirene ve admin'e gösterilir (ekranda maliyet gibi kısıtlı
    bilgi olabilir), bu yüzden genel ek tablosunda değil burada tutulur.
    """

    number = models.CharField("numara", max_length=32, unique=True, editable=False)
    description = models.TextField("açıklama")
    page_url = models.CharField("sayfa adresi", max_length=500, blank=True)
    page_title = models.CharField("sayfa başlığı", max_length=200, blank=True)
    user_agent = models.CharField("tarayıcı", max_length=500, blank=True)
    screen = models.CharField("ekran boyutu", max_length=32, blank=True)
    screenshot = models.FileField(
        "ekran görüntüsü", upload_to=problem_screenshot_upload_to, max_length=255, blank=True
    )

    class Meta:
        verbose_name = "sorun bildirimi"
        verbose_name_plural = "sorun bildirimleri"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.number
