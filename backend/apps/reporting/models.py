"""Raporlama: arka planda hazırlanan rapor dosyaları (Faz 4, Adım 4.3).

Panolar ve raporlar diğer modüllerin verisini yalnızca okur; bu uygulamanın tek tablosu büyük
Excel/PDF çıktıları için açılan iştir. Durum yalnızca `services` içinden, `state.py`'deki izin
tablosuna göre değişir.
"""

from django.db import models

from apps.core.models import BaseModel


class ReportJob(BaseModel):
    """Arka planda hazırlanan rapor dosyası. `created_by` raporu isteyen kişidir; dosyayı yalnızca
    o (ve admin) indirir. Dosya `EXPIRY_DAYS` gün sonra silinir, kayıt kalır (EXPIRED)."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Sırada"
        RUNNING = "RUNNING", "Hazırlanıyor"
        DONE = "DONE", "Hazır"
        FAILED = "FAILED", "Hata"
        EXPIRED = "EXPIRED", "Süresi doldu"

    class Format(models.TextChoices):
        XLSX = "xlsx", "Excel"
        PDF = "pdf", "PDF"

    report_code = models.CharField("rapor", max_length=64, db_index=True)
    title = models.CharField("başlık", max_length=200)
    file_format = models.CharField("biçim", max_length=8, choices=Format.choices)
    params = models.JSONField("filtreler", default=dict, blank=True)
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
        editable=False,
    )
    file = models.FileField("dosya", upload_to="reports/%Y/%m/", blank=True, editable=False)
    file_name = models.CharField("dosya adı", max_length=200, blank=True, editable=False)
    row_count = models.PositiveIntegerField("satır sayısı", null=True, blank=True, editable=False)
    error = models.TextField("hata", blank=True, editable=False)
    started_at = models.DateTimeField("başlama zamanı", null=True, blank=True, editable=False)
    finished_at = models.DateTimeField("bitiş zamanı", null=True, blank=True, editable=False)
    expires_at = models.DateTimeField("silinme zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "rapor dosyası"
        verbose_name_plural = "rapor dosyaları"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["created_by", "status"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_file_format_display()})"
