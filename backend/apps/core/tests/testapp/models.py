"""Yalnızca testlerde kullanılan modeller (config.settings.test içinde yüklenir)."""

from django.db import models

from apps.core.models import DocumentModel, MasterDataModel


class Widget(MasterDataModel):
    name = models.CharField("ad", max_length=100)
    code = models.CharField("kod", max_length=20, blank=True)
    quantity = models.DecimalField("miktar", max_digits=18, decimal_places=4, default=0)
    owner = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    def __str__(self) -> str:
        return self.name


class SampleDocument(DocumentModel):
    title = models.CharField("başlık", max_length=100)


class TypedWidget(MasterDataModel):
    """Kodlama testleri: kodun öneki kaydın türünden gelir (ekipman türü gibi)."""

    class Kind(models.TextChoices):
        ALPHA = "ALPHA", "Alfa"
        BETA = "BETA", "Beta"

    code = models.CharField("kod", max_length=32, unique=True)
    name = models.CharField("ad", max_length=100)
    kind = models.CharField("tür", max_length=8, choices=Kind.choices)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
