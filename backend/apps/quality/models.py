"""Kalite kontrol: test tanımı, sürümlü spesifikasyon, numune, test sonucu ve kalite kararı.

Bu dosyada iş mantığı yoktur. Yazma işlemleri `services.py` üzerinden yapılır; numune ve
spesifikasyon durumu `state.py`'deki izin tablosuna göre değişir. Lot durumu yalnızca kalite
kararıyla (`services.decide`) değişir (Faz 2, Adım 2.1).
"""

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, MasterDataModel, User
from apps.inventory.models import Lot
from apps.masterdata.fields import CodeField
from apps.masterdata.models import Location, Material


class SampleStage(models.TextChoices):
    INCOMING = "INCOMING", "Giriş"
    IN_PROCESS = "IN_PROCESS", "Şarj sırasında"
    FINAL = "FINAL", "Son kontrol"
    RETURN = "RETURN", "İade"


class TestDefinition(MasterDataModel):
    """Laboratuvar testi (pH, viskozite, …). Sonuç türü girişin biçimini belirler."""

    __test__ = False  # pytest bu sınıfı test sınıfı sanmasın

    class ResultType(models.TextChoices):
        NUMERIC = "NUMERIC", "Sayısal"
        PASS_FAIL = "PASS_FAIL", "Uygun / uygun değil"
        TEXT = "TEXT", "Metin"

    code = CodeField("kod", unique=True)
    name = models.CharField("ad", max_length=200)
    result_type = models.CharField("sonuç türü", max_length=16, choices=ResultType.choices)
    unit = models.CharField("birim", max_length=32, blank=True, help_text="ör. cP, g/ml, %")
    method = models.TextField("yöntem", blank=True)
    decimal_places = models.PositiveSmallIntegerField("ondalık hane", default=2)

    class Meta:
        verbose_name = "test tanımı"
        verbose_name_plural = "test tanımları"
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(decimal_places__lte=4),
                name="quality_test_decimal_places_max",
                violation_error_message="Ondalık hane en çok 4 olabilir.",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Specification(BaseModel):
    """Malzeme + numune aşaması için sürümlü spesifikasyon (reçete gibi):
    taslak → onaylı → geçersiz. Aynı malzeme ve aşamada tek onaylı sürüm olur."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        APPROVED = "APPROVED", "Onaylı"
        OBSOLETE = "OBSOLETE", "Geçersiz"

    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="specifications"
    )
    sample_stage = models.CharField("numune aşaması", max_length=16, choices=SampleStage.choices)
    version_no = models.PositiveIntegerField("sürüm no", editable=False)
    status = models.CharField(
        "durum",
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        editable=False,
    )
    change_note = models.TextField("değişiklik notu", blank=True)
    copied_from = models.ForeignKey(
        "self",
        verbose_name="kopyalandığı sürüm",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    approved_by = models.ForeignKey(
        User,
        verbose_name="onaylayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    approved_at = models.DateTimeField("onay zamanı", null=True, blank=True, editable=False)
    obsoleted_at = models.DateTimeField(
        "geçersiz olma zamanı", null=True, blank=True, editable=False
    )

    class Meta:
        verbose_name = "spesifikasyon"
        verbose_name_plural = "spesifikasyonlar"
        ordering = ["material__code", "sample_stage", "-version_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["material", "sample_stage", "version_no"],
                name="quality_spec_version_no_uniq",
                violation_error_message="Bu sürüm numarası zaten var.",
            ),
            models.UniqueConstraint(
                fields=["material", "sample_stage"],
                condition=Q(status="APPROVED"),
                name="quality_spec_single_approved",
                violation_error_message="Bu malzeme ve aşamada zaten onaylı bir sürüm var.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.material.code} {self.get_sample_stage_display()} v{self.version_no}"


class SpecificationLine(BaseModel):
    """Spesifikasyon satırı: test ve kabul sınırları. Sayısal testte alt/üst sınır (boşsa açık),
    uygun/uygun değil ve metin testinde beklenen değer."""

    specification = models.ForeignKey(
        Specification, verbose_name="spesifikasyon", on_delete=models.PROTECT, related_name="lines"
    )
    sequence = models.PositiveIntegerField("sıra")
    test = models.ForeignKey(
        TestDefinition, verbose_name="test", on_delete=models.PROTECT, related_name="+"
    )
    min_value = models.DecimalField(
        "alt sınır", max_digits=18, decimal_places=4, null=True, blank=True
    )
    max_value = models.DecimalField(
        "üst sınır", max_digits=18, decimal_places=4, null=True, blank=True
    )
    target_value = models.DecimalField(
        "hedef değer", max_digits=18, decimal_places=4, null=True, blank=True
    )
    text_expected = models.CharField("beklenen", max_length=200, blank=True)
    is_mandatory = models.BooleanField("zorunlu", default=True)

    class Meta:
        verbose_name = "spesifikasyon satırı"
        verbose_name_plural = "spesifikasyon satırları"
        ordering = ["specification", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["specification", "sequence"],
                name="quality_spec_line_sequence_uniq",
                violation_error_message="Bu sıra numarası sürümde zaten kullanılıyor.",
            ),
            models.UniqueConstraint(
                fields=["specification", "test"],
                name="quality_spec_line_test_uniq",
                violation_error_message="Bu test sürümde zaten var.",
            ),
            models.CheckConstraint(
                condition=Q(min_value__isnull=True)
                | Q(max_value__isnull=True)
                | Q(min_value__lte=models.F("max_value")),
                name="quality_spec_line_min_lte_max",
                violation_error_message="Alt sınır üst sınırdan büyük olamaz.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.specification} #{self.sequence} {self.test.code}"


class Sample(DocumentModel):
    """Numune (`NM-`). Spesifikasyon açılışta o anki onaylı sürüme sabitlenir; onaylı sürüm yoksa
    laboratuvar karar vermeden önce atar."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Bekliyor"
        IN_TEST = "IN_TEST", "Testte"
        AWAITING_APPROVAL = "AWAITING_APPROVAL", "Şartlı kabul onayı bekliyor"
        DECIDED = "DECIDED", "Karar verildi"
        CANCELLED = "CANCELLED", "İptal"

    class Origin(models.TextChoices):
        GOODS_RECEIPT = "GOODS_RECEIPT", "Mal kabul"
        PRODUCTION = "PRODUCTION", "Şarj bitişi"
        FILLING = "FILLING", "Dolum"
        RETURN = "RETURN", "Müşteri iadesi"
        MANUAL = "MANUAL", "Elle"

    lot = models.ForeignKey(
        Lot, verbose_name="lot", on_delete=models.PROTECT, related_name="samples"
    )
    stage = models.CharField("aşama", max_length=16, choices=SampleStage.choices)
    origin = models.CharField(
        "kaynak", max_length=16, choices=Origin.choices, default=Origin.MANUAL, editable=False
    )
    specification = models.ForeignKey(
        Specification,
        verbose_name="spesifikasyon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="samples",
    )
    taken_by = models.ForeignKey(
        User,
        verbose_name="numuneyi alan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    taken_at = models.DateTimeField("numune alma zamanı", null=True, blank=True)
    retain_location = models.ForeignKey(
        Location,
        verbose_name="şahit numune yeri",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.TextField("not", blank=True)
    decided_at = models.DateTimeField("karar zamanı", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "numune"
        verbose_name_plural = "numuneler"
        ordering = ["-created_at", "-id"]

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.PENDING, self.Status.IN_TEST)


class TestResult(BaseModel):
    """Test sonucu. Düzeltme yeni kayıtla yapılır; eski kayıt `superseded_by` ile yenisine bağlanır
    ve silinmez. Geçerli sonuç `superseded_by` boş olandır."""

    __test__ = False  # pytest bu sınıfı test sınıfı sanmasın

    sample = models.ForeignKey(
        Sample, verbose_name="numune", on_delete=models.PROTECT, related_name="results"
    )
    spec_line = models.ForeignKey(
        SpecificationLine,
        verbose_name="spesifikasyon satırı",
        on_delete=models.PROTECT,
        related_name="+",
    )
    numeric_value = models.DecimalField(
        "sayısal sonuç", max_digits=18, decimal_places=4, null=True, blank=True
    )
    text_value = models.CharField("metin sonuç", max_length=500, blank=True)
    passed = models.BooleanField("uygun", null=True, blank=True)
    is_within_spec = models.BooleanField("spesifikasyona uygun", editable=False)
    measured_by = models.ForeignKey(
        User, verbose_name="ölçen", on_delete=models.PROTECT, null=True, related_name="+"
    )
    measured_at = models.DateTimeField("ölçüm zamanı")
    instrument = models.CharField("cihaz", max_length=100, blank=True)
    note = models.TextField("not", blank=True)
    # Geçici olarak kendisine bağlanabildiği için (bkz. services._supersede) OneToOne değil.
    superseded_by = models.ForeignKey(
        "self",
        verbose_name="yerine geçen sonuç",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supersedes",
        editable=False,
    )

    class Meta:
        verbose_name = "test sonucu"
        verbose_name_plural = "test sonuçları"
        ordering = ["sample", "spec_line__sequence", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "spec_line"],
                condition=Q(superseded_by__isnull=True),
                name="quality_result_single_current",
                violation_error_message="Bu test için geçerli bir sonuç zaten var.",
            )
        ]

    def __str__(self) -> str:
        return f"{self.sample_id} {self.spec_line_id}"


class QualityDecision(BaseModel):
    """Kalite kararı. Şartlı kabul yönetim onayı ister (`approval_status`)."""

    class Decision(models.TextChoices):
        RELEASE = "RELEASE", "Serbest"
        REJECT = "REJECT", "Ret"
        REWORK = "REWORK", "Yeniden işleme"
        CONDITIONAL_RELEASE = "CONDITIONAL_RELEASE", "Şartlı kabul"

    class Approval(models.TextChoices):
        NOT_REQUIRED = "NOT_REQUIRED", "Gerekmez"
        PENDING = "PENDING", "Onay bekliyor"
        APPROVED = "APPROVED", "Onaylandı"
        REFUSED = "REFUSED", "Reddedildi"

    sample = models.ForeignKey(
        Sample, verbose_name="numune", on_delete=models.PROTECT, related_name="decisions"
    )
    decision = models.CharField("karar", max_length=24, choices=Decision.choices)
    reason = models.TextField("gerekçe", blank=True)
    decided_by = models.ForeignKey(
        User, verbose_name="karar veren", on_delete=models.PROTECT, null=True, related_name="+"
    )
    decided_at = models.DateTimeField("karar zamanı")
    release_location = models.ForeignKey(
        Location,
        verbose_name="serbest bırakılınca taşınacak lokasyon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    approval_status = models.CharField(
        "onay durumu", max_length=16, choices=Approval.choices, default=Approval.NOT_REQUIRED
    )
    approved_by = models.ForeignKey(
        User,
        verbose_name="onaylayan (yönetim)",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField("onay zamanı", null=True, blank=True)
    approval_note = models.TextField("onay notu", blank=True)

    class Meta:
        verbose_name = "kalite kararı"
        verbose_name_plural = "kalite kararları"
        ordering = ["sample", "-decided_at", "-id"]

    def __str__(self) -> str:
        return f"{self.sample_id} {self.get_decision_display()}"

    @property
    def is_effective(self) -> bool:
        """Lotu etkileyen (yürürlükteki) karar mı?"""
        return self.approval_status in (self.Approval.NOT_REQUIRED, self.Approval.APPROVED)
