"""İSG ve çevre (Faz 4, Adım 4.5): GBF arşivi, tehlike sınıfları (GHS piktogramı, H/P ifadeleri),
depolama limitleri, atık kayıtları (`AT-`) ve olay/kaza kayıtları (`OL-`).

Bu dosyada iş mantığı yoktur. Kayıtlar yalnızca `services` içinden değişir; olay ve atık
kayıtlarının durumları `state.py`'deki izin tablosuna göre ilerler.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, DocumentModel, MasterDataModel
from apps.masterdata.fields import CodeField
from apps.masterdata.models import Equipment, Location, Material, Supplier


class HazardClass(models.TextChoices):
    """GHS piktogramları; depolama limitleri de bu sınıflarla tanımlanır."""

    GHS01 = "GHS01", "Patlayıcı"
    GHS02 = "GHS02", "Yanıcı"
    GHS03 = "GHS03", "Oksitleyici"
    GHS04 = "GHS04", "Basınçlı gaz"
    GHS05 = "GHS05", "Aşındırıcı"
    GHS06 = "GHS06", "Akut toksik"
    GHS07 = "GHS07", "Zararlı / tahriş edici"
    GHS08 = "GHS08", "Sağlık tehlikesi"
    GHS09 = "GHS09", "Çevre için tehlikeli"


class SignalWord(models.TextChoices):
    DANGER = "DANGER", "Tehlike"
    WARNING = "WARNING", "Dikkat"


class HseSettings(BaseModel):
    """Tek satırlık ayar."""

    sds_max_age_months = models.PositiveIntegerField(
        "GBF en çok yaşı (ay)",
        default=36,
        help_text="Revizyon tarihi bundan eski GBF raporda 'Revizyonu eski' görünür.",
    )

    class Meta:
        verbose_name = "İSG ayarı"
        verbose_name_plural = "İSG ayarları"

    def __str__(self) -> str:
        return "İSG ayarları"


class HazardStatement(MasterDataModel):
    """H (tehlike), P (önlem) ve EUH (ek) ifadeleri. Sık kullanılanlar migration ile gelir."""

    class Kind(models.TextChoices):
        H = "H", "Tehlike ifadesi"
        P = "P", "Önlem ifadesi"
        EUH = "EUH", "Ek ifade"

    code = CodeField("kod", unique=True)
    kind = models.CharField("tür", max_length=4, choices=Kind.choices)
    text = models.TextField("metin")

    class Meta:
        verbose_name = "tehlike / önlem ifadesi"
        verbose_name_plural = "tehlike / önlem ifadeleri"
        ordering = ["kind", "code"]

    def __str__(self) -> str:
        return self.code


class MaterialHazard(BaseModel):
    """Malzemenin tehlike bilgisi ("Tehlike" sekmesi). Piktogramı olan malzeme tehlikeli madde
    sayılır; `Material.is_hazardous` servisle eşitlenir."""

    material = models.OneToOneField(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="hazard"
    )
    pictograms = ArrayField(
        models.CharField(max_length=8, choices=HazardClass.choices),
        verbose_name="piktogramlar",
        default=list,
        blank=True,
    )
    signal_word = models.CharField(
        "uyarı kelimesi", max_length=8, choices=SignalWord.choices, blank=True
    )
    statements = models.ManyToManyField(
        HazardStatement, verbose_name="ifadeler", blank=True, related_name="+"
    )
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "malzeme tehlike bilgisi"
        verbose_name_plural = "malzeme tehlike bilgileri"
        ordering = ["material__code"]

    def __str__(self) -> str:
        return f"{self.material_id} {','.join(self.pictograms)}"


class SafetyDataSheet(BaseModel):
    """Güvenlik bilgi formu (GBF). PDF'i ek olarak yüklenir. Son revizyon geçerlidir
    (`superseded_at` boş); eskiler arşivde kalır."""

    material = models.ForeignKey(
        Material, verbose_name="malzeme", on_delete=models.PROTECT, related_name="safety_sheets"
    )
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="tedarikçi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    revision_no = models.CharField("revizyon no", max_length=32)
    revision_date = models.DateField("revizyon tarihi")
    valid_until = models.DateField("geçerlilik tarihi", null=True, blank=True)
    language = models.CharField("dil", max_length=8, default="tr")
    note = models.TextField("not", blank=True)
    superseded_at = models.DateTimeField(
        "yerine yenisi geldi", null=True, blank=True, editable=False, db_index=True
    )

    class Meta:
        verbose_name = "güvenlik bilgi formu"
        verbose_name_plural = "güvenlik bilgi formları"
        ordering = ["material__code", "-revision_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["material"],
                condition=Q(superseded_at__isnull=True),
                name="hse_sds_one_current",
                violation_error_message="Malzemenin geçerli bir GBF'si zaten var.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.material_id} rev. {self.revision_no}"

    @property
    def is_current(self) -> bool:
        return self.superseded_at is None


class StorageLimit(MasterDataModel):
    """Lokasyon × tehlike sınıfı için en çok miktar (kg). Aşılırsa işlem durmaz, uyarı gider."""

    location = models.ForeignKey(
        Location, verbose_name="lokasyon", on_delete=models.PROTECT, related_name="+"
    )
    hazard_class = models.CharField("tehlike sınıfı", max_length=8, choices=HazardClass.choices)
    max_kg = models.DecimalField("en çok miktar (kg)", max_digits=18, decimal_places=4)
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "depolama limiti"
        verbose_name_plural = "depolama limitleri"
        ordering = ["location__code", "hazard_class"]
        constraints = [
            models.UniqueConstraint(
                fields=["location", "hazard_class"],
                name="hse_storage_limit_uniq",
                violation_error_message="Bu lokasyon ve tehlike sınıfı için limit zaten var.",
            ),
            models.CheckConstraint(
                condition=Q(max_kg__gt=0),
                name="hse_storage_limit_positive",
                violation_error_message="Limit sıfırdan büyük olmalıdır.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.location_id} {self.hazard_class}"


class WasteContractor(MasterDataModel):
    """Lisanslı atık firması."""

    name = models.CharField("ad", max_length=200)
    license_no = models.CharField("lisans no", max_length=64)
    license_valid_until = models.DateField("lisans geçerlilik tarihi")
    phone = models.CharField("telefon", max_length=32, blank=True)
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "atık firması"
        verbose_name_plural = "atık firmaları"
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return self.name


class WasteRecord(DocumentModel):
    """Atık teslim kaydı (`AT-`). Lisansı geçmiş firmaya teslim kaydedilemez."""

    class Status(models.TextChoices):
        RECORDED = "RECORDED", "Kaydedildi"
        CANCELLED = "CANCELLED", "İptal"

    waste_code = models.CharField("atık kodu", max_length=16, db_index=True)
    description = models.CharField("tanım", max_length=200)
    is_hazardous = models.BooleanField("tehlikeli atık", default=False)
    quantity_kg = models.DecimalField("miktar (kg)", max_digits=18, decimal_places=4)
    contractor = models.ForeignKey(
        WasteContractor, verbose_name="lisanslı firma", on_delete=models.PROTECT, related_name="+"
    )
    delivered_on = models.DateField("teslim tarihi", db_index=True)
    document_no = models.CharField("taşıma formu / belge no", max_length=64, blank=True)
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "atık kaydı"
        verbose_name_plural = "atık kayıtları"
        ordering = ["-delivered_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_kg__gt=0),
                name="hse_waste_quantity_positive",
                violation_error_message="Miktar sıfırdan büyük olmalıdır.",
            ),
        ]


class Incident(DocumentModel):
    """Olay / kaza kaydı (`OL-`). Herkes açar; yönetim inceler ve kapatır."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Açık"
        INVESTIGATING = "INVESTIGATING", "İnceleniyor"
        CLOSED = "CLOSED", "Kapandı"
        CANCELLED = "CANCELLED", "İptal"

    class Type(models.TextChoices):
        WORK_ACCIDENT = "WORK_ACCIDENT", "İş kazası"
        NEAR_MISS = "NEAR_MISS", "Ramak kala"
        ENVIRONMENTAL = "ENVIRONMENTAL", "Çevre olayı"
        FIRE = "FIRE", "Yangın"
        OTHER = "OTHER", "Diğer"

    class Severity(models.TextChoices):
        LOW = "LOW", "Düşük"
        MEDIUM = "MEDIUM", "Orta"
        HIGH = "HIGH", "Yüksek"

    incident_type = models.CharField("tür", max_length=16, choices=Type.choices)
    occurred_at = models.DateTimeField("olay zamanı", db_index=True)
    place = models.CharField("yer", max_length=200)
    location = models.ForeignKey(
        Location,
        verbose_name="lokasyon",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    equipment = models.ForeignKey(
        Equipment,
        verbose_name="ekipman",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    description = models.TextField("anlatım")
    injury = models.BooleanField("yaralanan var", default=False)
    injured_person = models.CharField("yaralanan", max_length=200, blank=True)
    severity = models.CharField(
        "ağırlık", max_length=8, choices=Severity.choices, default=Severity.LOW
    )
    root_cause = models.TextField("kök neden", blank=True)
    corrective_action = models.TextField("düzeltici faaliyet", blank=True)
    action_owner = models.CharField("faaliyet sorumlusu", max_length=200, blank=True)
    action_due = models.DateField("faaliyet termini", null=True, blank=True)
    closed_note = models.TextField("kapanış notu", blank=True)

    class Meta:
        verbose_name = "olay kaydı"
        verbose_name_plural = "olay kayıtları"
        ordering = ["-occurred_at", "-id"]
