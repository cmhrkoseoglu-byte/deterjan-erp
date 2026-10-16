"""Sistem izleme modelleri (Faz 5, Adım 5.5): yedek/geri yükleme testi geçmişi, kontrol durumu,
arka plan servislerinin nabzı. İş mantığı `services.py`'dedir."""

from django.db import models


class BackupRun(models.Model):
    """Yedek servisinin (`backup` konteyneri) yazdığı durum dosyasından içe aktarılan çalışma."""

    class Kind(models.TextChoices):
        BACKUP = "backup", "Yedek"
        RESTORE_TEST = "restore_test", "Geri yükleme testi"

    class Status(models.TextChoices):
        OK = "ok", "Başarılı"
        FAILED = "failed", "Başarısız"

    class Offsite(models.TextChoices):
        OK = "ok", "Kopyalandı"
        FAILED = "failed", "Kopyalanamadı"
        DISABLED = "disabled", "Tanımlı değil"

    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    run_id = models.CharField("çalışma", max_length=32)
    source_run_id = models.CharField("test edilen yedek", max_length=32, blank=True)
    started_at = models.DateTimeField("başlangıç")
    finished_at = models.DateTimeField("bitiş")
    status = models.CharField("durum", max_length=8, choices=Status.choices)
    message = models.TextField("mesaj", blank=True)
    database_bytes = models.BigIntegerField("veritabanı boyutu", default=0)
    media_bytes = models.BigIntegerField("ekler boyutu", default=0)
    media_files = models.IntegerField("ek dosya sayısı", default=0)
    tables = models.IntegerField("tablo sayısı", default=0)
    rows = models.BigIntegerField("satır sayısı", default=0)
    offsite = models.CharField(
        "ayrı konum", max_length=8, choices=Offsite.choices, default=Offsite.DISABLED
    )
    offsite_message = models.TextField("ayrı konum mesajı", blank=True)
    mismatches = models.JSONField("uyuşmazlıklar", default=list, blank=True)
    imported_at = models.DateTimeField("içe aktarılma", auto_now_add=True)

    class Meta:
        verbose_name = "yedek çalışması"
        verbose_name_plural = "yedek çalışmaları"
        ordering = ["-finished_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "run_id"], name="ops_backuprun_unique_run")
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.run_id} ({self.get_status_display()})"


class CheckState(models.Model):
    """Bir izleme kontrolünün son durumu; aynı uyarının tekrar tekrar gitmesini önler."""

    code = models.CharField("kontrol", max_length=32, unique=True)
    failing = models.BooleanField("sorunlu", default=False)
    since = models.DateTimeField("durum başlangıcı", null=True, blank=True)
    last_alert_at = models.DateTimeField("son uyarı", null=True, blank=True)
    detail = models.TextField("ayrıntı", blank=True)
    updated_at = models.DateTimeField("güncellenme", auto_now=True)

    class Meta:
        verbose_name = "izleme kontrolü"
        verbose_name_plural = "izleme kontrolleri"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Heartbeat(models.Model):
    """Arka plan servislerinin (Celery worker, beat) son çalıştığı an."""

    name = models.CharField("servis", max_length=16, unique=True)
    beat_at = models.DateTimeField("son nabız")

    class Meta:
        verbose_name = "servis nabzı"
        verbose_name_plural = "servis nabızları"

    def __str__(self) -> str:
        return self.name
