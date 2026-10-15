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
