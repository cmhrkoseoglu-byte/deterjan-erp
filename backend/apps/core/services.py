"""Çekirdek servisler: belge numaralama, denetimli kayıt, belge oluşturma, durum geçişi, iptal,
rol atama, giriş/çıkış."""

import mimetypes
import os
import re
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone

from apps.core import attachments, events
from apps.core.audit import EXCLUDED_FIELDS, diff, log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import Attachment, AuditLog, DocumentModel, DocumentSequence, User
from apps.core.roles import ALL_ROLES
from apps.core.state import StateMachine

_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
CANCELLED = "CANCELLED"
# Kaydedilip kaydedilmeyeceğine karar verirken bakılmayan, her kayıtta değişen alanlar.
_AUTO_FIELDS = frozenset({"updated_at", "updated_by"})


def _real_actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def next_document_number(prefix: str, *, year: int | None = None) -> str:
    """Yıl bazında sıfırlanan, çakışmasız belge numarası üretir: `UE-2026-00001`.

    Yıl, Türkiye saatine (`TIME_ZONE`) göre bugünün yılıdır. Sayaç satırı `select_for_update`
    ile kilitlenir. Belgeyi oluşturan transaction'ın içinde çağrılmalıdır: işlem geri alınırsa
    numara da geri alınır (numara atlaması olmaz); kilit, transaction bitene kadar aynı önekteki
    diğer numara isteklerini bekletir.
    """
    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"Geçersiz belge öneki: {prefix!r} (büyük harf/rakam, en fazla 10)")
    if year is None:
        year = timezone.localdate().year
    with transaction.atomic():
        # Satır yoksa çakışmasız oluştur (eşzamanlı ilk çağrılarda IntegrityError olmaz).
        DocumentSequence.objects.bulk_create(
            [DocumentSequence(prefix=prefix, year=year, last_number=0)], ignore_conflicts=True
        )
        sequence = DocumentSequence.objects.select_for_update().get(prefix=prefix, year=year)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
    return f"{prefix}-{year}-{sequence.last_number:05d}"


def _has_field(instance: models.Model, name: str) -> bool:
    return any(f.name == name for f in instance._meta.concrete_fields)


def save_with_audit[M: models.Model](instance: M, actor: User | None, *, note: str = "") -> M:
    """Kaydı oluşturur ya da günceller; `created_by/updated_by` doldurur ve denetim kaydı yazar.

    - Güncellemede değişen alanlar eski → yeni değerleriyle yazılır. Hiçbir alan değişmediyse
      kayıt yapılmaz (ne veritabanına ne günlüğe).
    - Belgeler (`DocumentModel`) bu fonksiyonla oluşturulamaz (`create_document` kullanılır);
      numara, durum ve iptal alanları bu fonksiyonla değiştirilemez (`transition_status`,
      `cancel_document` kullanılır). Bayat bir belge nesnesi kaydedilirse bu alanlar
      veritabanındaki güncel değerleriyle korunur.
    """
    if instance._state.adding and isinstance(instance, DocumentModel):
        raise ValueError("Belgeler create_document ile oluşturulur.")
    return _save_with_audit(instance, actor, note=note)


def _save_with_audit[M: models.Model](instance: M, actor: User | None, *, note: str) -> M:
    actor = _real_actor(actor)
    with transaction.atomic():
        if instance._state.adding:
            if _has_field(instance, "created_by"):
                instance.created_by = actor  # type: ignore[attr-defined]
                instance.updated_by = actor  # type: ignore[attr-defined]
            instance.save()
            log_change(actor, instance, AuditLog.Action.CREATE, diff(None, instance), note)
            _remember_state(instance)
            return instance

        before = type(instance)._base_manager.select_for_update().get(pk=instance.pk)
        exclude = _AUTO_FIELDS
        if isinstance(instance, DocumentModel):
            assert isinstance(before, DocumentModel)
            _guard_document_state(instance, before)
            exclude = exclude | frozenset(DocumentModel.STATE_FIELDS)
        # Şifre gibi günlüğe yazılmayan alanlar da "değişti mi" kararına dahildir.
        changed = diff(before, instance, exclude=exclude)
        if not changed:
            return instance
        if _has_field(instance, "updated_by"):
            instance.updated_by = actor  # type: ignore[attr-defined]
        instance.save()
        changes = {name: values for name, values in changed.items() if name not in EXCLUDED_FIELDS}
        if changes:
            log_change(actor, instance, AuditLog.Action.UPDATE, changes, note)
    return instance


def _remember_state(instance: models.Model) -> None:
    if isinstance(instance, DocumentModel):
        instance._loaded_state = instance.state_values()  # type: ignore[attr-defined]


def _guard_document_state(instance: DocumentModel, before: DocumentModel) -> None:
    """Durum alanlarına doğrudan atamayı reddeder; bayat nesnede bu alanları tazeler."""
    current = instance.state_values()
    loaded = getattr(instance, "_loaded_state", None)
    if loaded is None:  # veritabanından yüklenmemiş, elle kurulmuş nesne
        loaded = before.state_values()
    if any(current[name] != loaded[name] for name in loaded if name in current):
        raise ValueError(
            "Belge numarası, durumu ve iptal bilgileri doğrudan değiştirilemez; "
            "transition_status / cancel_document kullanın."
        )
    # Başka bir işlem durumu değiştirmiş olabilir: güncel değerin üzerine yazma.
    for name, value in before.state_values().items():
        setattr(instance, before._meta.get_field(name).attname, value)  # type: ignore[union-attr]
    _remember_state(instance)


def create_document[D: DocumentModel](
    instance: D,
    actor: User | None,
    *,
    prefix: str,
    machine: StateMachine,
    note: str = "",
    event_payload: dict[str, Any] | None = None,
) -> D:
    """Yeni belgeyi numara (`next_document_number(prefix)`) ve başlangıç durumuyla oluşturur.

    Denetim kaydı (`create`) yazılır ve commit sonrası `<makine_adı>.created` olayı yayınlanır.
    `event_payload` olayın standart alanlarına eklenir.
    """
    if not instance._state.adding:
        raise ValueError("create_document yalnızca yeni belge için kullanılır.")
    assert machine.initial is not None
    with transaction.atomic():
        instance.number = next_document_number(prefix)
        instance.status = machine.initial
        _save_with_audit(instance, actor, note=note)
        events.publish(
            machine.event_name("created"),
            {
                "model": instance._meta.label_lower,
                "id": instance.pk,
                "number": instance.number,
                "status": instance.status,
                **(event_payload or {}),
            },
            _real_actor(actor),
        )
    return instance


def transition_status[D: DocumentModel](
    instance: D,
    to_status: str,
    actor: User | None,
    *,
    machine: StateMachine,
    note: str = "",
    event_payload: dict[str, Any] | None = None,
) -> D:
    """Belgeyi durum makinesine göre yeni duruma geçirir.

    İzinsiz geçişte `BusinessRuleError("invalid_transition")`. Başarılı geçişte denetim kaydı
    (`status_change`) yazılır ve commit sonrası `<makine_adı>.<yeni_durum>` olayı yayınlanır.
    `event_payload` olayın standart alanlarına eklenir (ör. mal kabulde oluşan lotlar).
    İptal için `cancel_document` kullanılır.
    """
    if to_status == CANCELLED:
        raise ValueError("İptal için cancel_document kullanın.")
    return _apply_transition(
        instance,
        to_status,
        actor,
        machine=machine,
        note=note,
        action=AuditLog.Action.STATUS_CHANGE,
        event_payload=event_payload,
    )


def cancel_document[D: DocumentModel](
    instance: D, actor: User | None, *, reason: str, machine: StateMachine
) -> D:
    """Belgeyi iptal eder (`CANCELLED`). İptal nedeni zorunludur; belge silinmez.

    Denetim kaydı (`cancel`) yazılır ve commit sonrası `<makine_adı>.cancelled` olayı yayınlanır.
    """
    reason = reason.strip()
    if not reason:
        raise BusinessRuleError("cancel_reason_required", "İptal nedeni girilmelidir.")
    actor = _real_actor(actor)
    return _apply_transition(
        instance,
        CANCELLED,
        actor,
        machine=machine,
        note=reason,
        action=AuditLog.Action.CANCEL,
        extra={"cancelled_at": timezone.now(), "cancelled_by": actor, "cancel_reason": reason},
    )


def _apply_transition[D: DocumentModel](
    instance: D,
    to_status: str,
    actor: User | None,
    *,
    machine: StateMachine,
    note: str,
    action: str,
    extra: dict[str, Any] | None = None,
    event_payload: dict[str, Any] | None = None,
) -> D:
    actor = _real_actor(actor)
    extra = extra or {}
    with transaction.atomic():
        # Güncel durum veritabanından kilitlenerek okunur (eşzamanlı iki geçişe karşı).
        current = type(instance)._base_manager.select_for_update().get(pk=instance.pk)
        from_status = current.status
        machine.assert_can_transition(from_status, to_status)
        instance.status = to_status
        instance.updated_by = actor
        for name, value in extra.items():
            setattr(instance, name, value)
        instance.save(update_fields=["status", "updated_by", "updated_at", *extra])
        changes: dict[str, Any] = {"status": [from_status, to_status]}
        if "cancel_reason" in extra:
            changes["cancel_reason"] = [current.cancel_reason, extra["cancel_reason"]]
        log_change(actor, instance, action, changes, note)
        _remember_state(instance)
        events.publish(
            machine.event_name(to_status),
            {
                "model": instance._meta.label_lower,
                "id": instance.pk,
                "number": instance.number,
                "from_status": from_status,
                "to_status": to_status,
                **(event_payload or {}),
            },
            actor,
        )
    return instance


def set_user_roles(user: User, roles: Iterable[str], actor: User | None, *, note: str = "") -> None:
    """Kullanıcının rollerini verilen listeyle değiştirir ve değişikliği denetim günlüğüne yazar.

    Tanımsız rol kodunda `BusinessRuleError("unknown_role")`; rol henüz oluşturulmamışsa
    (`seed_roles` çalışmamış) `BusinessRuleError("role_not_seeded")`.
    """
    wanted = sorted(set(roles))
    unknown = [role for role in wanted if role not in ALL_ROLES]
    if unknown:
        raise BusinessRuleError("unknown_role", f"Tanımsız rol: {', '.join(unknown)}")
    with transaction.atomic():
        groups = list(Group.objects.filter(name__in=wanted))
        if len(groups) != len(wanted):
            raise BusinessRuleError(
                "role_not_seeded", "Roller tanımlı değil; önce seed_roles komutunu çalıştırın."
            )
        before = sorted(user.groups.values_list("name", flat=True))
        if before == wanted:
            return
        user.groups.set(groups)
        user.refresh_roles()
        log_change(
            _real_actor(actor), user, AuditLog.Action.UPDATE, {"roles": [before, wanted]}, note
        )


def login_user(request: HttpRequest, username: str, password: str) -> User:
    """Kullanıcı adı/şifreyi doğrular ve oturum açar.

    Hatalı bilgi ya da pasif kullanıcıda `BusinessRuleError("invalid_credentials")`.
    Başarılı ve başarısız denemeler Django'nun giriş sinyalleriyle denetim günlüğüne yazılır
    (`core.signals`); yönetim paneli girişi de aynı yoldan denetlenir.
    """
    user = auth.authenticate(request, username=username, password=password)
    if not isinstance(user, User):
        raise BusinessRuleError("invalid_credentials", "Kullanıcı adı veya şifre hatalı.")
    auth.login(request, user)
    return user


def logout_user(request: HttpRequest) -> None:
    """Oturumu kapatır. Giriş yapmış kullanıcının çıkışı sinyalle denetim günlüğüne yazılır."""
    auth.logout(request)


# --- ekler ---------------------------------------------------------------------------------------


def attachment_target(label: str, object_id: int) -> tuple[ContentType, models.Model]:
    """`"app_label.model"` + kimlik → (ContentType, kayıt). Ek alamayan tür ya da olmayan kayıtta
    `BusinessRuleError`."""
    label = (label or "").strip().lower()
    if not attachments.is_attachment_target(label):
        raise BusinessRuleError("invalid_record_type", "Bu kayıt türüne dosya eklenemez.")
    app_label, _, model = label.partition(".")
    try:
        content_type = ContentType.objects.get_by_natural_key(app_label, model)
    except ContentType.DoesNotExist:
        raise BusinessRuleError("invalid_record_type", "Geçersiz kayıt türü.") from None
    model_class = content_type.model_class()
    assert model_class is not None
    target = model_class._base_manager.filter(pk=object_id).first()
    if target is None:
        raise BusinessRuleError("record_not_found", "Dosya eklenecek kayıt bulunamadı.")
    return content_type, target


@transaction.atomic
def add_attachment(
    actor: User,
    *,
    target_type: str,
    object_id: int,
    file: UploadedFile,
    kind: str = Attachment.Kind.OTHER,
    note: str = "",
) -> Attachment:
    """Kayda dosya ekler. Uzantı izinli listede ve boyut sınırın altında olmalı; yorum gibi
    bazı türlere yalnızca sahibi ekleyebilir (`core.attachments`)."""
    content_type, target = attachment_target(target_type, object_id)
    if not attachments.can_add_attachment(actor, target_type, target):
        raise BusinessRuleError("attachment_forbidden", "Bu kayda dosya ekleme yetkiniz yok.")
    name = os.path.basename(file.name or "dosya")[:255]
    extension = os.path.splitext(name)[1].lower()
    if extension not in attachments.ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(e.lstrip(".") for e in attachments.ALLOWED_EXTENSIONS))
        raise BusinessRuleError(
            "file_type_not_allowed", f"Bu dosya türü eklenemez. İzinli türler: {allowed}."
        )
    max_bytes = int(getattr(settings, "ATTACHMENT_MAX_BYTES", attachments.DEFAULT_MAX_BYTES))
    size = file.size or 0
    if size == 0:
        raise BusinessRuleError("file_empty", "Dosya boş.")
    if size > max_bytes:
        raise BusinessRuleError(
            "file_too_large", f"Dosya en çok {max_bytes // (1024 * 1024)} MB olabilir."
        )
    if kind not in Attachment.Kind.values:
        raise BusinessRuleError("invalid_kind", "Geçersiz ek türü.")
    mime_type = (getattr(file, "content_type", "") or "").split(";")[0][:100]
    if not mime_type:
        mime_type = mimetypes.guess_type(name)[0] or ""
    attachment = Attachment(
        content_type=content_type,
        object_id=target.pk,
        file=file,
        kind=kind,
        original_name=name,
        size=size,
        mime_type=mime_type,
        note=note.strip()[:500],
    )
    save_with_audit(attachment, actor)
    log_change(actor, target, AuditLog.Action.CUSTOM, {}, f"Dosya eklendi: {name}")
    return attachment


@transaction.atomic
def remove_attachment(actor: User, attachment: Attachment, reason: str = "") -> Attachment:
    """Eki kaldırır (silinmez, pasife alınır). Yalnızca yükleyen ya da admin kaldırabilir."""
    locked = Attachment.objects.select_for_update().get(pk=attachment.pk)
    if not locked.is_active:
        raise BusinessRuleError("already_removed", "Ek zaten kaldırılmış.")
    if not actor.is_admin and locked.created_by_id != actor.pk:
        raise BusinessRuleError(
            "attachment_forbidden", "Eki yalnızca yükleyen kişi ya da admin kaldırabilir."
        )
    locked.is_active = False
    locked.removed_at = timezone.now()
    locked.removed_by = actor
    locked.removal_reason = reason.strip()[:500]
    return save_with_audit(locked, actor, note="Ek kaldırıldı")
