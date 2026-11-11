"""Çekirdek modeller: kullanıcı, ortak soyut modeller, denetim günlüğü, belge numara sayaçları.

Bu dosyada iş mantığı yoktur; yazma işlemleri `services.py` ve `audit.py` üzerinden yapılır.
"""

import os
import uuid
from collections.abc import Collection
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Self

from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from apps.core.roles import ADMIN

if TYPE_CHECKING:
    from apps.core.effective_access import EffectiveAccess


class User(AbstractUser):
    """Sistem kullanıcısı. Roller Django `Group` ilişkisiyle tutulur (grup adı = rol kodu)."""

    full_name = models.CharField("ad soyad", max_length=150, blank=True)
    phone = models.CharField("telefon", max_length=32, blank=True)
    must_change_password = models.BooleanField(
        "şifresini değiştirmeli",
        default=False,
        help_text="Şifreyi yönetici verdiyse (yeni kullanıcı, şifre sıfırlama) kullanıcı kendi "
        "şifresini belirleyene kadar sistemde başka işlem yapamaz.",
    )

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"
        ordering = ["username"]

    def __str__(self) -> str:
        return self.full_name or self.username

    @cached_property
    def role_names(self) -> frozenset[str]:
        """Kullanıcının rol kodları (önbellekli; rol değişince `refresh_roles()` çağrılır)."""
        return frozenset(self.groups.values_list("name", flat=True))

    @property
    def roles(self) -> list[str]:
        """Rol kodları, alfabetik sıralı."""
        return sorted(self.role_names)

    def has_role(self, *roles: str) -> bool:
        """Kullanıcı verilen rollerden en az birine sahipse True.

        Yalnızca gerçekten atanmış rollere bakar; admin/superuser ayrıcalığı
        `is_admin` ile ayrıca kontrol edilir (bkz. `core.permissions.HasRole`).
        """
        return bool(self.role_names.intersection(roles))

    @property
    def is_admin(self) -> bool:
        """Superuser ya da `admin` rolündeki kullanıcı: rol korumalı her uç noktaya erişir."""
        return self.is_superuser or self.has_role(ADMIN)

    def refresh_roles(self) -> None:
        """Rol ve yetki önbelleğini temizler (rol ya da kişiye özel yetki değişince)."""
        self.__dict__.pop("role_names", None)
        self.__dict__.pop("access", None)

    refresh_access = refresh_roles

    @cached_property
    def access(self) -> "EffectiveAccess":
        """Geçerli yetki (rol paketleri ve kişiye özel ayarlar; docs/plan/kisi-yetkileri.md §5.3).

        Önbellekli: aynı nesnede bir kez hesaplanır; değişince `refresh_access()` çağrılır.
        """
        from apps.core.effective_access import effective_access

        return effective_access(self)


class Currency(models.TextChoices):
    """Para birimleri (satış siparişi, mal kabul fiyatı)."""

    TRY = "TRY", "TL"
    EUR = "EUR", "Euro"
    USD = "USD", "ABD doları"


class BaseModel(models.Model):
    """Tüm iş modellerinin atası: oluşturma/güncelleme zamanı ve kullanıcısı."""

    created_at = models.DateTimeField("oluşturulma zamanı", auto_now_add=True)
    updated_at = models.DateTimeField("güncellenme zamanı", auto_now=True)
    # null=True: sistem işlemleri (komutlar, arka plan işleri) için.
    created_by = models.ForeignKey(
        User,
        verbose_name="oluşturan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    updated_by = models.ForeignKey(
        User,
        verbose_name="güncelleyen",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True


class MasterDataModel(BaseModel):
    """Ana veriler için: silinmez, `is_active=False` ile pasife alınır."""

    is_active = models.BooleanField("aktif", default=True, db_index=True)

    class Meta:
        abstract = True


class DocumentModel(BaseModel):
    """Durumlu belgeler için. Durum yalnızca `core.services.transition_status` ile değişir."""

    number = models.CharField("belge no", max_length=32, unique=True, editable=False)
    status = models.CharField("durum", max_length=32, db_index=True, editable=False)
    cancelled_at = models.DateTimeField("iptal zamanı", null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(
        User,
        verbose_name="iptal eden",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )
    cancel_reason = models.TextField("iptal nedeni", blank=True, editable=False)

    # Yalnızca core.services (create_document, transition_status, cancel_document) yazar.
    STATE_FIELDS: ClassVar[tuple[str, ...]] = (
        "number",
        "status",
        "cancelled_at",
        "cancelled_by",
        "cancel_reason",
    )

    # Durum alanlarının veritabanından yüklendiği/son kaydedildiği andaki değerleri (alan değil).
    _loaded_state: dict[str, Any]

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.number

    @classmethod
    def from_db(
        cls,
        db: str | None,
        field_names: Collection[str],
        values: Collection[Any],
        *args: Any,
        **kwargs: Any,
    ) -> Self:
        instance = super().from_db(db, field_names, values, *args, **kwargs)
        # Doğrudan atamayı yakalamak için (bkz. core.services.save_with_audit).
        instance._loaded_state = instance.state_values()
        return instance

    def state_values(self) -> dict[str, Any]:
        """Durum alanlarının bellekteki değerleri (FK için kimlik). Yüklenmemiş (deferred)
        alanlar dahil edilmez."""
        values = {}
        for name in self.STATE_FIELDS:
            attname = self._meta.get_field(name).attname  # type: ignore[union-attr]
            if attname in self.__dict__:
                values[name] = self.__dict__[attname]
        return values


class AuditLog(models.Model):
    """Denetim günlüğü. Kayıtlar değiştirilemez ve silinemez."""

    class Action(models.TextChoices):
        CREATE = "create", "Oluşturma"
        UPDATE = "update", "Güncelleme"
        STATUS_CHANGE = "status_change", "Durum değişikliği"
        CANCEL = "cancel", "İptal"
        LOGIN = "login", "Giriş"
        LOGOUT = "logout", "Çıkış"
        LOGIN_FAILED = "login_failed", "Başarısız giriş"
        CUSTOM = "custom", "Diğer"

    timestamp = models.DateTimeField("zaman", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        User,
        verbose_name="kullanıcı",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField("işlem", max_length=32, choices=Action.choices, db_index=True)
    content_type = models.ForeignKey(
        ContentType,
        verbose_name="kayıt türü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    object_id = models.BigIntegerField("kayıt no", null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField("kayıt", max_length=255, blank=True)
    # {"alan": [eski, yeni]}
    changes = models.JSONField("değişiklikler", default=dict, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField("IP adresi", null=True, blank=True)
    note = models.TextField("not", blank=True)

    class Meta:
        verbose_name = "denetim kaydı"
        verbose_name_plural = "denetim günlüğü"
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return f"{self.timestamp:%d.%m.%Y %H:%M} {self.get_action_display()} {self.object_repr}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValueError("Denetim kayıtları değiştirilemez.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Denetim kayıtları silinemez.")


class DocumentSequence(models.Model):
    """Belge numarası sayacı: önek + yıl başına son verilen numara."""

    prefix = models.CharField("önek", max_length=10)
    year = models.PositiveSmallIntegerField("yıl")
    last_number = models.PositiveIntegerField("son numara", default=0)

    class Meta:
        verbose_name = "belge numara sayacı"
        verbose_name_plural = "belge numara sayaçları"
        constraints = [
            models.UniqueConstraint(fields=["prefix", "year"], name="core_docseq_prefix_year_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.prefix}-{self.year}: {self.last_number}"


# --- kodlama sistematiği (docs/plan/kodlama-sistematigi.md) --------------------------------------


class ImmutableModel(models.Model):
    """Satır bir kez yazılır; değiştirilemez ve silinemez (denetim günlüğü gibi)."""

    immutable_message: ClassVar[str] = "Bu kayıt değiştirilemez."

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValueError(self.immutable_message)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError(self.immutable_message)


class CodeScheme(BaseModel):
    """Bir kod türünün (ana veri kodu, belge numarası, lot numarası) ayarlanmış biçimi.

    Satır yoksa türün kayıttaki (`core.coding.registry`) varsayılanı geçerlidir. Yalnızca
    `core.coding.services.update_scheme` yazar; her değişiklik `CodeSchemeRevision` olarak saklanır.
    """

    class Kind(models.TextChoices):
        MASTER = "master", "Ana veri kodu"
        DOCUMENT = "document", "Belge numarası"
        LOT = "lot", "Lot numarası"

    key = models.CharField("kod türü", max_length=64, unique=True)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    prefix = models.CharField("önek", max_length=16, blank=True)
    # Ana veride kaydın türüne göre önek (ekipman: {"MIXING_TANK": "TANK", ...}).
    type_prefixes = models.JSONField("türe göre önekler", default=dict, blank=True)
    width = models.PositiveSmallIntegerField("sıra hanesi")
    year_format = models.CharField("yıl biçimi", max_length=8, blank=True)
    date_format = models.CharField("tarih biçimi", max_length=8, blank=True)
    # Ana veri: etkinse yeni kayıtta kod önerilir ve biçim zorunludur.
    is_active = models.BooleanField("etkin", default=False)
    revision = models.PositiveIntegerField("revizyon", default=0)

    class Meta:
        verbose_name = "kod biçimi"
        verbose_name_plural = "kod biçimleri"
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key


class CodeSchemeRevision(ImmutableModel):
    """Kod biçimi değişikliğinin değiştirilemez kopyası (değişiklik notu zorunlu)."""

    immutable_message = "Kod biçimi revizyonları değiştirilemez."

    scheme = models.ForeignKey(
        CodeScheme, verbose_name="kod biçimi", on_delete=models.PROTECT, related_name="revisions"
    )
    revision = models.PositiveIntegerField("revizyon")
    prefix = models.CharField("önek", max_length=16, blank=True)
    type_prefixes = models.JSONField("türe göre önekler", default=dict, blank=True)
    width = models.PositiveSmallIntegerField("sıra hanesi")
    year_format = models.CharField("yıl biçimi", max_length=8, blank=True)
    date_format = models.CharField("tarih biçimi", max_length=8, blank=True)
    is_active = models.BooleanField("etkin", default=False)
    # Ana veride admin'in düzelttiği sayaçlar: {"MLZ": 25} (sıradaki numara).
    counters = models.JSONField("sayaç düzeltmesi", default=dict, blank=True)
    note = models.TextField("değişiklik notu")
    changed_at = models.DateTimeField("zaman", auto_now_add=True)
    changed_by = models.ForeignKey(
        User,
        verbose_name="değiştiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "kod biçimi revizyonu"
        verbose_name_plural = "kod biçimi revizyonları"
        ordering = ["-changed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["scheme", "revision"], name="core_codeschemerev_scheme_rev_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.scheme.key} rev. {self.revision}"


class CodeSequence(models.Model):
    """Ana veri kodu sayacı: kod türü + önek başına verilen son sıra no (`MLZ-` → 24)."""

    key = models.CharField("kod türü", max_length=64)
    stem = models.CharField("önek", max_length=32)
    last_number = models.PositiveBigIntegerField("son numara", default=0)

    class Meta:
        verbose_name = "kod sayacı"
        verbose_name_plural = "kod sayaçları"
        constraints = [
            models.UniqueConstraint(fields=["key", "stem"], name="core_codesequence_key_stem_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.key} {self.stem}: {self.last_number}"


class CodeHistory(ImmutableModel):
    """Bir kaydın eski kodu ve o kodun geçerli olduğu aralık (`valid_from` ≤ t < `valid_to`).

    Kullanılmış kod aynı türde başka bir kayda verilmez; eski kod aramada, okutmada ve içe
    aktarmada tanınır. Satırlar değiştirilemez ve silinemez.
    """

    immutable_message = "Eski kod kayıtları değiştirilemez."

    class Reason(models.TextChoices):
        CHANGE = "change", "Kod değişikliği"
        MIGRATION = "migration", "Kod göçü"
        REVERT = "revert", "Geri alma"

    content_type = models.ForeignKey(
        ContentType, verbose_name="kayıt türü", on_delete=models.PROTECT, related_name="+"
    )
    object_id = models.BigIntegerField("kayıt no")
    field = models.CharField("alan", max_length=32, default="code")
    code = models.CharField("eski kod", max_length=64)
    valid_from = models.DateTimeField("geçerlilik başlangıcı")
    valid_to = models.DateTimeField("geçerlilik sonu")
    reason = models.CharField("neden", max_length=16, choices=Reason.choices)
    note = models.CharField("not", max_length=255, blank=True)
    run = models.ForeignKey(
        "CodeMigrationRun",
        verbose_name="kod göçü",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="history",
    )
    created_at = models.DateTimeField("kayıt zamanı", auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="değiştiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "eski kod"
        verbose_name_plural = "eski kodlar"
        ordering = ["-valid_to", "-id"]
        indexes = [
            models.Index(fields=["content_type", "field", "code"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return self.code


class CodeMigrationRun(ImmutableModel):
    """Uygulanan bir kod göçü ya da geri alması: hangi kaydın kodu neyden neye değişti.

    `mapping` satırları `{"id": 5, "label": "...", "old": "DENEME", "new": "REC-0000004"}`. Geri
    alma kendi satırıyla tutulur (`reverts`). Satırlar değiştirilemez ve silinemez.
    """

    immutable_message = "Kod göçü kayıtları değiştirilemez."

    class Kind(models.TextChoices):
        APPLY = "apply", "Göç"
        REVERT = "revert", "Geri alma"

    key = models.CharField("kod türü", max_length=64)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices)
    mapping = models.JSONField("eşleme", default=list)
    note = models.TextField("not")
    reverts = models.ForeignKey(
        "self",
        verbose_name="geri alınan göç",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reverted_by",
    )
    created_at = models.DateTimeField("zaman", auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="uygulayan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "kod göçü"
        verbose_name_plural = "kod göçleri"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Kod göçü #{self.pk}"


class OutputDocument(BaseModel):
    """Basılı çıktının doküman kontrol bilgisi (ISO 9001 md. 7.5): doküman no, ilk yayın tarihi,
    revizyonlar. `is_active` açıksa bugünkü çıktıya alt bilgi bandı basılır; belge kendi
    tarihindeki bant durumuyla (`OutputBandChange`) ve revizyonun saklanan doküman no ve ilk yayın
    tarihiyle basılır. İlk revizyondan sonra doküman no ve ilk yayın tarihi yalnız yeni revizyonla
    değişir. Yalnızca `core.coding.outputs` yazar; çıktı türleri
    `core.coding.registry.register_output` ile kayıtlı.
    """

    key = models.CharField("çıktı", max_length=64, unique=True)
    doc_code = models.CharField("doküman no", max_length=32, blank=True)
    first_issue_date = models.DateField("ilk yayın tarihi", null=True, blank=True)
    is_active = models.BooleanField("çıktıya basılsın", default=False)

    class Meta:
        verbose_name = "çıktı dokümanı"
        verbose_name_plural = "çıktı dokümanları"
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(
                fields=["doc_code"],
                condition=~models.Q(doc_code=""),
                name="core_outputdocument_code_uniq",
                violation_error_message="Bu doküman numarası başka bir çıktıda kullanılıyor.",
            )
        ]

    def __str__(self) -> str:
        return self.doc_code or self.key


class OutputDocumentRevision(ImmutableModel):
    """Çıktı dokümanının revizyonu (değiştirilemez): yürürlük tarihi, değişiklik açıklaması,
    onaylayan. Belge, tarihinde yürürlükte olan ve o güne kadar girilmiş (`created_at`) revizyonla
    basılır; bantta revizyonun saklanan doküman no ve ilk yayın tarihi yazar (yeniden basım ilk
    basımdaki gibidir)."""

    immutable_message = "Doküman revizyonları değiştirilemez."

    output = models.ForeignKey(
        OutputDocument,
        verbose_name="çıktı dokümanı",
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    revision_no = models.PositiveSmallIntegerField("revizyon no")
    revision_date = models.DateField("revizyon (yürürlük) tarihi")
    # Revizyon girildiğinde çıktının doküman no ve ilk yayın tarihi.
    doc_code = models.CharField("doküman no", max_length=32, blank=True, default="")
    first_issue_date = models.DateField("ilk yayın tarihi", null=True, blank=True)
    change_note = models.TextField("değişiklik açıklaması")
    approved_by_name = models.CharField("onaylayan", max_length=150)
    approved_on = models.DateField("onay tarihi")
    # Revizyon girildiğinde çıktının şablon sürümü (kayıttaki sürüm büyükse ekran uyarır).
    template_version = models.PositiveIntegerField("şablon sürümü", default=1)
    created_at = models.DateTimeField("kayıt zamanı", auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="giren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "doküman revizyonu"
        verbose_name_plural = "doküman revizyonları"
        ordering = ["output", "-revision_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["output", "revision_no"], name="core_outputdocrev_output_no_uniq"
            )
        ]

    def __str__(self) -> str:
        return f"{self.output} Rev.{self.revision_no:02d}"


class OutputBandChange(ImmutableModel):
    """Çıktı bandının açılması ya da kapanması (değiştirilemez). Belge kendi tarihindeki bant
    durumuyla basılır: bant açılmadan önceki tarihli belge bantsız, bant kapatılsa da açıkken
    tarihlenen belge bantlı basılır."""

    immutable_message = "Bant değişiklikleri değiştirilemez."

    output = models.ForeignKey(
        OutputDocument,
        verbose_name="çıktı dokümanı",
        on_delete=models.PROTECT,
        related_name="band_changes",
    )
    is_active = models.BooleanField("çıktıya basılsın")
    effective_date = models.DateField("geçerlilik tarihi")
    created_at = models.DateTimeField("kayıt zamanı", auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="değiştiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "bant değişikliği"
        verbose_name_plural = "bant değişiklikleri"
        ordering = ["output", "-effective_date", "-id"]

    def __str__(self) -> str:
        state = "açık" if self.is_active else "kapalı"
        return f"{self.output} bant {state} ({self.effective_date:%d.%m.%Y})"


def attachment_upload_to(instance: "Attachment", filename: str) -> str:
    """Dosya adı tahmin edilemez olsun diye rastgele; özgün ad `original_name`'de tutulur."""
    extension = os.path.splitext(filename)[1].lower()[:10]
    return f"attachments/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


class Attachment(BaseModel):
    """Bir kayda (lot, numune, mal kabul, yorum) bağlı dosya ya da fotoğraf. Silinmez;
    kaldırılınca `is_active=False` olur ve denetim günlüğüne yazılır."""

    class Kind(models.TextChoices):
        SUPPLIER_COA = "SUPPLIER_COA", "Tedarikçi analiz sertifikası"
        PHOTO = "PHOTO", "Fotoğraf"
        DELIVERY_NOTE = "DELIVERY_NOTE", "İrsaliye"
        DOCUMENT = "DOCUMENT", "Belge"
        OTHER = "OTHER", "Diğer"

    content_type = models.ForeignKey(
        ContentType, verbose_name="kayıt türü", on_delete=models.PROTECT, related_name="+"
    )
    object_id = models.BigIntegerField("kayıt no")
    related_object = GenericForeignKey("content_type", "object_id")
    file = models.FileField("dosya", upload_to=attachment_upload_to, max_length=255)
    kind = models.CharField("tür", max_length=16, choices=Kind.choices, default=Kind.OTHER)
    original_name = models.CharField("dosya adı", max_length=255)
    size = models.PositiveBigIntegerField("boyut (bayt)")
    mime_type = models.CharField("içerik türü", max_length=100, blank=True)
    note = models.CharField("not", max_length=500, blank=True)
    is_active = models.BooleanField("aktif", default=True, db_index=True)
    removed_at = models.DateTimeField("kaldırılma zamanı", null=True, blank=True)
    removed_by = models.ForeignKey(
        User,
        verbose_name="kaldıran",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    removal_reason = models.CharField("kaldırma nedeni", max_length=500, blank=True)

    class Meta:
        verbose_name = "ek"
        verbose_name_plural = "ekler"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self) -> str:
        return self.original_name

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Ekler silinemez; kaldırılır.")


# --- giriş güvenliği (Faz 5, Adım 5.5) ------------------------------------------------------------


class LoginLockout(models.Model):
    """Kullanıcı adı başına hatalı giriş sayacı ve kilit (`core.security`).

    Kullanıcı adına göre tutulur (var olmayan adlar da sayılır); böylece kilit mesajı kullanıcı
    adının var olup olmadığını belli etmez. Önbellekten bağımsızdır, Redis yokken de çalışır.
    """

    username = models.CharField("kullanıcı adı", max_length=150, unique=True)
    failed_count = models.PositiveIntegerField("hatalı deneme", default=0)
    window_started_at = models.DateTimeField("ilk hatalı deneme", null=True, blank=True)
    locked_until = models.DateTimeField("kilit bitişi", null=True, blank=True)
    updated_at = models.DateTimeField("güncellenme", auto_now=True)

    class Meta:
        verbose_name = "giriş kilidi"
        verbose_name_plural = "giriş kilitleri"
        ordering = ["username"]

    def __str__(self) -> str:
        return self.username

    def is_locked(self, now: Any = None) -> bool:
        now = now or timezone.now()
        return self.locked_until is not None and self.locked_until > now


class TOTPDevice(models.Model):
    """Kullanıcının doğrulayıcı uygulaması (TOTP, RFC 6238). `confirmed_at` boşsa kurulum yarım."""

    user = models.OneToOneField(
        User, verbose_name="kullanıcı", on_delete=models.CASCADE, related_name="totp_device"
    )
    secret = models.CharField("gizli anahtar", max_length=64)
    confirmed_at = models.DateTimeField("kurulum zamanı", null=True, blank=True)
    # Aynı kodun ikinci kez kullanılmaması için son kabul edilen zaman adımı.
    last_used_step = models.BigIntegerField("son kullanılan adım", default=0)
    created_at = models.DateTimeField("oluşturulma", auto_now_add=True)

    class Meta:
        verbose_name = "doğrulayıcı uygulama"
        verbose_name_plural = "doğrulayıcı uygulamalar"

    def __str__(self) -> str:
        return f"{self.user} (2FA)"

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


class RecoveryCode(models.Model):
    """Telefon kaybolursa kullanılan tek kullanımlık kurtarma kodu (yalnızca özeti saklanır)."""

    user = models.ForeignKey(
        User, verbose_name="kullanıcı", on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_hash = models.CharField("kod özeti", max_length=128)
    used_at = models.DateTimeField("kullanılma", null=True, blank=True)

    class Meta:
        verbose_name = "kurtarma kodu"
        verbose_name_plural = "kurtarma kodları"

    def __str__(self) -> str:
        return f"{self.user} kurtarma kodu"


# --- kişiye özel yetkiler (docs/plan/kisi-yetkileri.md §5.2) ----------------------------------


class AccessOverride(models.Model):
    """Kişiye özel yetki dönemi: rol paketine ekleme ya da paketten kaldırma.

    Satır silinmez; bitmiş satır değişmez (yalnız bitiş alanları bir kez yazılır). Kişi, bölüm ve
    düzey başına en çok bir etkin satır olur. `key` yetki kataloğundaki bölüm anahtarıdır
    (`apps/<modül>/access.py`); veritabanı bunu bilmez, geçerli yetki hesabı tanımsız anahtarı yok
    sayar. Yalnız `core.services` yazar.
    """

    class Level(models.TextChoices):
        VIEW = "view", "Görür"
        CHANGE = "change", "Değiştirir"
        APPROVE = "approve", "Onaylar"
        READ = "read", "Kayıtları okur"

    class Effect(models.TextChoices):
        GRANT = "grant", "Eklendi"
        REVOKE = "revoke", "Kaldırıldı"

    class EndReason(models.TextChoices):
        RESET = "reset", "Rol varsayılanına döndü"
        REPLACED = "replaced", "Yeni kayıtla değişti"
        INEFFECTIVE = "ineffective", "Etkisiz kaldı"
        ROLE_REMOVED = "role_removed", "Gerekli rol kaldırıldı"
        ADMIN = "admin", "Sistem yöneticisi oldu"
        RETIRED = "retired", "Yetki tanımı kaldırıldı"

    END_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"ended_at", "ended_by", "end_reason", "end_note"}
    )

    user = models.ForeignKey(
        User,
        verbose_name="kullanıcı",
        on_delete=models.PROTECT,
        related_name="access_overrides",
    )
    key = models.CharField("yetki", max_length=64)
    level = models.CharField("düzey", max_length=8, choices=Level.choices)
    effect = models.CharField("değişiklik", max_length=8, choices=Effect.choices)
    note = models.TextField("gerekçe")
    created_at = models.DateTimeField("başlangıç", auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        verbose_name="değiştiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    ended_at = models.DateTimeField("bitiş", null=True, blank=True)
    ended_by = models.ForeignKey(
        User,
        verbose_name="bitiren",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    end_reason = models.CharField(
        "bitiş nedeni", max_length=16, choices=EndReason.choices, blank=True
    )
    end_note = models.TextField("bitiş notu", blank=True)

    class Meta:
        verbose_name = "kişiye özel yetki"
        verbose_name_plural = "kişiye özel yetkiler"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key", "level"],
                condition=models.Q(ended_at__isnull=True),
                name="core_accessoverride_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(ended_at__isnull=True, end_reason="", ended_by__isnull=True)
                    | (models.Q(ended_at__isnull=False) & ~models.Q(end_reason=""))
                ),
                name="core_accessoverride_end_consistent",
            ),
            models.CheckConstraint(
                condition=~models.Q(level="read", effect="grant"),
                name="core_accessoverride_read_revoke_only",
            ),
        ]
        indexes = [models.Index(fields=["user", "ended_at"])]

    def __str__(self) -> str:
        return f"{self.user} {self.key} {self.get_level_display()} {self.get_effect_display()}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            fields = kwargs.get("update_fields")
            if fields is None or not set(fields) <= self.END_FIELDS:
                raise ValueError("Kişiye özel yetki kaydı değiştirilemez; yalnız bitirilebilir.")
            stored = type(self)._base_manager.filter(pk=self.pk).values_list("ended_at", flat=True)
            if stored.first() is not None:
                raise ValueError("Bitmiş kişiye özel yetki kaydı değiştirilemez.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("Yetki geçmişi silinemez.")

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class AccessCatalogSnapshot(ImmutableModel):
    """Yetki kataloğunun (bölümler ve rol paketleri) bir sürümdeki kopyası.

    `sync_access_catalog` komutu, katalog değişince bir satır yazar. Geçmiş bir tarihteki yetkiler
    bu kopyadan, rol değişikliklerinden ve kişiye özel yetki dönemlerinden yeniden kurulur.
    """

    immutable_message = "Yetki paketi sürümü değiştirilemez."

    catalog_hash = models.CharField("özet", max_length=64, db_index=True)
    catalog = models.JSONField("katalog", encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField("kayıt zamanı", auto_now_add=True)

    class Meta:
        verbose_name = "yetki paketi sürümü"
        verbose_name_plural = "yetki paketi sürümleri"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.catalog_hash[:12]}"
