"""Çekirdek servisler: belge numaralama, denetimli kayıt, belge oluşturma, durum geçişi, iptal,
rol atama, kullanıcı yönetimi, giriş/çıkış."""

import mimetypes
import os
import re
import secrets
import string
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.contrib import auth
from django.contrib.auth import password_validation
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import connection, models, transaction
from django.db.models import F, Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.core import (
    access,
    attachments,
    event_names,
    events,
    records,
    security,
    user_access,
)
from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.audit import EXCLUDED_FIELDS, diff, log_change
from apps.core.coding import formats as coding_formats
from apps.core.coding import registry as coding_registry
from apps.core.coding import selectors as coding_selectors
from apps.core.exceptions import BusinessRuleError
from apps.core.models import (
    AccessCatalogSnapshot,
    AccessOverride,
    Attachment,
    AuditLog,
    DocumentModel,
    DocumentSequence,
    User,
)
from apps.core.permissions import ACCESS_ADMIN_MESSAGE, require_admin
from apps.core.roles import ADMIN, ALL_ROLES
from apps.core.state import StateMachine
from apps.core.user_access import GRANT, REVOKE, AccessPlan, OverrideSpec

_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
CANCELLED = "CANCELLED"
# Kaydedilip kaydedilmeyeceğine karar verirken bakılmayan, her kayıtta değişen alanlar.
_AUTO_FIELDS = frozenset({"updated_at", "updated_by"})


def _real_actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def next_document_number(prefix: str, *, year: int | None = None) -> str:
    """Yıl bazında sıfırlanan, çakışmasız belge numarası üretir: `UE-2026-00001`.

    `prefix` belge türünün varsayılan önekidir (çağrı yerleri bunu kullanır). Tür kayıtlıysa
    (`core.coding.registry.register_document_type`) önek, yıl biçimi ve sıra hanesi Sistem >
    Kodlama sistematiği ayarından gelir; admin öneki değiştirdiyse sayaç yeni önekte 1'den başlar.
    Kayıtsız önekte (yalnızca testler) bugünkü biçim kullanılır.

    Yıl, Türkiye saatine (`TIME_ZONE`) göre bugünün yılıdır. Sayaç satırı `select_for_update`
    ile kilitlenir. Belgeyi oluşturan transaction'ın içinde çağrılmalıdır: işlem geri alınırsa
    numara da geri alınır (numara atlaması olmaz); kilit, transaction bitene kadar aynı önekteki
    diğer numara isteklerini bekletir.
    """
    if not _PREFIX_RE.match(prefix):
        raise ValueError(f"Geçersiz belge öneki: {prefix!r} (büyük harf/rakam, en fazla 10)")
    if year is None:
        year = timezone.localdate().year
    document_type = coding_registry.document_type(prefix)
    if document_type is not None:
        fmt = coding_selectors.effective_format(document_type)
    else:
        fmt = coding_formats.Format(kind=coding_registry.DOCUMENT, prefix=prefix, width=5)
    with transaction.atomic():
        # Satır yoksa çakışmasız oluştur (eşzamanlı ilk çağrılarda IntegrityError olmaz).
        DocumentSequence.objects.bulk_create(
            [DocumentSequence(prefix=fmt.prefix, year=year, last_number=0)], ignore_conflicts=True
        )
        sequence = DocumentSequence.objects.select_for_update().get(prefix=fmt.prefix, year=year)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
    return coding_formats.document_number(fmt, year, sequence.last_number)


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
    year: int | None = None,
) -> D:
    """Yeni belgeyi numara (`next_document_number(prefix)`) ve başlangıç durumuyla oluşturur.

    Denetim kaydı (`create`) yazılır ve commit sonrası `<makine_adı>.created` olayı yayınlanır.
    `event_payload` olayın standart alanlarına eklenir. `year` verilirse numara o yılın sayacından
    alınır (dönem belgeleri: Aralık bordrosu Ocak'ta açılsa da `BR-<Aralık'ın yılı>`).
    """
    if not instance._state.adding:
        raise ValueError("create_document yalnızca yeni belge için kullanılır.")
    assert machine.initial is not None
    with transaction.atomic():
        instance.number = next_document_number(prefix, year=year)
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
    changes: dict[str, Any] | None = None,
) -> D:
    """Belgeyi durum makinesine göre yeni duruma geçirir.

    İzinsiz geçişte `BusinessRuleError("invalid_transition")`. Başarılı geçişte denetim kaydı
    (`status_change`) yazılır ve commit sonrası `<makine_adı>.<yeni_durum>` olayı yayınlanır.
    `event_payload` olayın standart alanlarına eklenir (ör. mal kabulde oluşan lotlar).
    `changes` aynı denetim kaydına eklenen alan satırlarıdır (`{alan: [eski, yeni]}`; ör. satın
    alma onayında tutar, kur ve limit, docs/plan/kisi-yetkileri.md §8 madde 7).
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
        changes=changes,
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
    changes: dict[str, Any] | None = None,
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
        logged: dict[str, Any] = {"status": [from_status, to_status]}
        if "cancel_reason" in extra:
            logged["cancel_reason"] = [current.cancel_reason, extra["cancel_reason"]]
        logged.update(changes or {})
        log_change(actor, instance, action, logged, note)
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


LAST_ADMIN_ROLE_MESSAGE = "Başka aktif sistem yöneticisi olmadığı için bu rol kaldırılamaz."


def _check_roles(wanted: Iterable[str]) -> None:
    unknown = [role for role in wanted if role not in ALL_ROLES]
    if unknown:
        raise BusinessRuleError("unknown_role", f"Tanımsız rol: {', '.join(unknown)}")


def _role_groups(wanted: list[str]) -> list[Group]:
    """Rollerin grupları; tanımsız rolde `unknown_role`, `seed_roles` çalışmamışsa
    `role_not_seeded`."""
    _check_roles(wanted)
    groups = list(Group.objects.filter(name__in=wanted))
    if len(groups) != len(wanted):
        raise BusinessRuleError(
            "role_not_seeded", "Roller tanımlı değil; önce seed_roles komutunu çalıştırın."
        )
    return groups


def _end_overrides(
    endings: Iterable[tuple[AccessOverride, str]], actor: User | None, note: str
) -> None:
    """Kişiye özel satırları bitirir (silmez). `note` boşsa bitiş nedeninin adı yazılır."""
    now = timezone.now()
    for row, reason in endings:
        row.ended_at = now
        row.ended_by = actor
        row.end_reason = reason
        row.end_note = note or AccessOverride.EndReason(reason).label
        row.save(update_fields=sorted(AccessOverride.END_FIELDS))


def _active_rows(user: User) -> list[AccessOverride]:
    """Kişinin etkin kişiye özel satırları, kilitli ve numara sırasıyla."""
    if user.pk is None:
        return []
    return list(
        AccessOverride.objects.select_for_update()
        .filter(user_id=user.pk, ended_at__isnull=True)
        .order_by("pk")
    )


def set_user_roles(user: User, roles: Iterable[str], actor: User | None, *, note: str = "") -> None:
    """Kullanıcının rollerini verilen listeyle değiştirir ve değişikliği denetim günlüğüne yazar.

    Kullanıcı açma ve yönetim komutları kullanır; var olan kullanıcının rolleri Yetkiler ekranında
    `set_user_access` ile değişir. Rol kancası burada da çalışır (plan §5.2): admin rolü verilince
    kişinin etkin kişiye özel ayarları `admin`, kaldırılan rolün KVKK bölümlerindeki eklemeler
    `role_removed` nedeniyle biter; o zaman denetim kaydına `access` (önce/sonra satırlar) da
    yazılır.

    Tanımsız rol kodunda `BusinessRuleError("unknown_role")`; rol henüz oluşturulmamışsa
    (`seed_roles` çalışmamış) `BusinessRuleError("role_not_seeded")`.
    """
    wanted = sorted(set(roles))
    _check_roles(wanted)
    with transaction.atomic():
        groups = _role_groups(wanted)
        before = sorted(user.groups.values_list("name", flat=True))
        if before == wanted:
            return
        active = _active_rows(user)
        user.groups.set(groups)
        user.refresh_roles()
        endings = user_access.role_change_endings(active, before, wanted)
        changes: dict[str, Any] = {"roles": [before, wanted]}
        if endings:
            _end_overrides(endings, _real_actor(actor), note)
            ended = {row.pk for row, _reason in endings}
            remaining = [row for row in active if row.pk not in ended]
            changes["access"] = [
                user_access.override_rows(active),
                user_access.override_rows(remaining),
            ]
        log_change(_real_actor(actor), user, AuditLog.Action.UPDATE, changes, note)
        publish_access_changed(user, actor)


def publish_access_changed(user: User, actor: User | None = None) -> None:
    """Kullanıcının geçerli yetkisi değişti: commit sonrası `access.changed` olayını yayınlar
    (açık sayfaları menüyü ve düğmeleri yeniler; plan §8 madde 11). Bildirim ve denetim kaydı
    üretmez; değişikliğin kaydını çağıran yazar."""
    events.publish(event_names.ACCESS_CHANGED, {"user_id": user.pk}, _real_actor(actor))


def _admin_removal_guard(actor: User, user: User, roles: Iterable[str]) -> None:
    """Admin rolü kaldırılırken: kendi admin rolünüz kaldırılamaz (`cannot_remove_own_admin`);
    başka aktif yönetici kalmayacaksa kaldırılamaz (`last_admin`). Çağıran, yöneticilerin
    satırlarını önceden kilitler (`_lock_active_admins`)."""
    wanted = set(roles)
    if user.has_role(ADMIN) and ADMIN not in wanted:
        if user.pk == actor.pk:
            raise BusinessRuleError(
                "cannot_remove_own_admin", "Kendi sistem yöneticisi rolünüzü kaldıramazsınız."
            )
        if user.is_active and not user.is_superuser:
            _ensure_another_admin(user, LAST_ADMIN_ROLE_MESSAGE)


def _lock_active_admins() -> None:
    """Aktif yöneticilerin satırlarını numara sırasıyla kilitler: iki admin aynı anda birbirinin
    admin rolünü kaldıramaz (son admin kuralı yarışı; critic §3.1). PostgreSQL `DISTINCT`
    sorguda kilit vermediği için numaralar alt sorguyla seçilir."""
    list(
        User.objects.select_for_update()
        .filter(pk__in=active_admins().values("pk"))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _check_access_request(
    actor: User,
    user: User,
    active: list[AccessOverride],
    desired: list[OverrideSpec],
    roles_after: tuple[str, ...],
) -> None:
    """Yetkiler kaydının kuralları, critic §4.1 sırasıyla (`access_changed`'dan sonra; gerekçe
    kuralı kaydın kendisindedir)."""
    active_specs = {OverrideSpec.of(row) for row in active}
    new_rows = [spec for spec in desired if spec not in active_specs]
    admin_after = user.is_superuser or ADMIN in roles_after
    changed = bool(new_rows) or (not admin_after and set(desired) != active_specs)
    if actor.pk == user.pk and changed:
        raise BusinessRuleError("cannot_edit_own_access", "Kendi yetkilerinizi değiştiremezsiniz.")
    if admin_after and new_rows:
        raise BusinessRuleError(
            "admin_has_all_access",
            "Sistem yöneticisi bütün yetkilere sahiptir; kişiye özel yetki tanımlanmaz.",
        )
    _role_groups(list(roles_after))
    _admin_removal_guard(actor, user, roles_after)

    seen: set[tuple[str, str]] = set()
    for spec in desired:
        if spec.entry in seen:
            raise BusinessRuleError(
                "access_duplicate", f"Aynı yetki iki kez seçilmiş: {spec.key} ({spec.level})."
            )
        seen.add(spec.entry)
    for spec in new_rows:
        _check_new_row(spec, roles_after)

    revoked_views = {spec.key for spec in desired if spec.effect == REVOKE and spec.level == VIEW}
    if any(
        spec.effect == GRANT and spec.level in (CHANGE, APPROVE) and spec.key in revoked_views
        for spec in desired
    ):
        raise BusinessRuleError(
            "access_conflict",
            "Görmeyi kaldırdığınız bölümde değiştirme ya da onay yetkisi verilemez.",
        )

    after = user_access.preview_access(roles_after, desired)
    for spec in new_rows:
        if spec.effect != GRANT or spec.entry in after.entries:
            continue
        for need in access.section(spec.key).requirements(spec.level):
            if need not in after.entries:
                raise BusinessRuleError(
                    "access_requires",
                    f"Bu yetki için önce “{user_access.access_label(need)}” yetkisi gerekir.",
                )


def _check_new_row(spec: OverrideSpec, roles_after: tuple[str, ...]) -> None:
    """Yeni bir kişiye özel satırın kuralları (kalan satırlar yeniden denetlenmez)."""
    if spec.effect not in (GRANT, REVOKE) or not user_access.is_known(spec):
        raise BusinessRuleError("unknown_access", f"Tanımsız yetki: {spec.key} ({spec.level}).")
    item = access.section(spec.key)
    if item.kind is access.Kind.OPEN_RECORDS and spec.effect == GRANT:
        raise BusinessRuleError(
            "open_records_revoke_only",
            "Açık kayıtları herkes okur; bu satır yalnız bir kişi için kapatılabilir.",
        )
    if spec.level in item.admin_only:
        raise BusinessRuleError(
            "access_not_grantable", "Bu yetki yalnızca sistem yöneticisine aittir."
        )
    if spec.effect == REVOKE and spec.level in item.locked:
        raise BusinessRuleError("access_locked", "Bu yetki herkese açıktır; kişiden kaldırılamaz.")
    if (
        spec.effect == GRANT
        and item.restricted_to_role is not None
        and item.restricted_to_role not in roles_after
    ):
        raise BusinessRuleError(
            "access_requires_role",
            "Bu yetki yalnızca yönetim rolündeki kullanıcılara verilebilir (KVKK).",
        )


def set_user_access(
    actor: User,
    user: User,
    *,
    version: str,
    overrides: Iterable[OverrideSpec],
    roles: Iterable[str] | None = None,
    note: str = "",
    dry_run: bool = False,
) -> AccessPlan:
    """Sistem › Kullanıcılar › Yetkiler kaydı (plan §5.2, §5.10, §6.1): rolleri (verilirse) ve
    kişiye özel ayarların istenen etkin kümesini (`overrides`, tam liste) bir arada kaydeder.

    Yalnız sistem yöneticisi çağırır (değilse 403). `version` ekran açıldığındaki sürüm
    belirtecidir (`user_access.access_version`); uymazsa `access_changed`. `dry_run=True` hiçbir
    şey yazmaz, aynı planı (uyarılarla) döner. Değişiklik yoksa yazmaz ve olay yayınlamaz; gerçek
    kayıtta gerekçe (`note`, en az 5 karakter) zorunludur. Hata kodları ve sırası: critic §4.1.

    Kilit sırası: (admin rolü kaldırılıyorsa) aktif yöneticiler → kişi → kişinin etkin satırları.
    Gerçek kayıtta önce satırlar biter, sonra yenileri açılır; kullanıcı üzerinde tek denetim
    kaydı yazılır (`roles` değiştiyse, `access` her zaman; satırlar numaralarıyla). Commit sonrası
    `access.changed` (açık oturumlar yenilenir) ve `access.updated` (kişiye bildirim) yayınlanır.
    """
    require_admin(actor, ACCESS_ADMIN_MESSAGE)
    desired = list(overrides)
    wanted = None if roles is None else sorted(set(roles))
    with transaction.atomic():
        current = set(Group.objects.filter(user__pk=user.pk).values_list("name", flat=True))
        if wanted is not None and ADMIN in current and ADMIN not in wanted:
            _lock_active_admins()
        target = User.objects.select_for_update().get(pk=user.pk)
        active = _active_rows(target)
        if user_access.access_version(target, active) != version:
            raise BusinessRuleError(
                "access_changed", "Yetkiler siz düzenlerken değişti; sayfayı yenileyin."
            )
        roles_before = tuple(target.roles)
        roles_after = roles_before if wanted is None else tuple(wanted)
        _check_access_request(actor, target, active, desired, roles_after)
        plan = user_access.build_plan(target, active, roles_after=roles_after, desired=desired)
        if dry_run or not plan.changed:
            return plan
        note = note.strip()
        if len(note) < 5:
            raise BusinessRuleError("access_note_required", "Değişikliğin gerekçesini yazın.")
        actor_or_none = _real_actor(actor)
        roles_changed = plan.roles_after != plan.roles_before
        if roles_changed:
            target.groups.set(_role_groups(list(plan.roles_after)))
        _end_overrides(plan.end, actor_or_none, note)
        created = AccessOverride.objects.bulk_create(
            [
                AccessOverride(
                    user=target,
                    key=spec.key,
                    level=spec.level,
                    effect=spec.effect,
                    note=note,
                    created_by=actor_or_none,
                )
                for spec in plan.create
            ]
        )
        target.refresh_access()
        changes: dict[str, Any] = {}
        if roles_changed:
            changes["roles"] = [list(plan.roles_before), list(plan.roles_after)]
        changes["access"] = [
            user_access.override_rows(active),
            user_access.override_rows([*plan.keep, *created]),
        ]
        log_change(actor_or_none, target, AuditLog.Action.UPDATE, changes, note)
        publish_access_changed(target, actor)
        events.publish(event_names.ACCESS_UPDATED, {"user_id": target.pk}, actor_or_none)
    return plan


# --- kullanıcı yönetimi (Sistem > Kullanıcılar; API yalnızca admin'e açık) ----------------------

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,149}$")
# Geçici şifrede birbirine karışan karakterler (0/O/o, 1/l/I/i) yoktur.
_AMBIGUOUS_CHARACTERS = frozenset("0Oo1lIi")
_TEMP_PASSWORD_ALPHABET = "".join(
    ch for ch in string.ascii_letters + string.digits if ch not in _AMBIGUOUS_CHARACTERS
)


def generate_temporary_password(user: User) -> str:
    """Şifre politikasına uyan, okunaklı geçici şifre üretir: dörtlü gruplar, ör. `Kp7m-x3Rt-9wQa`.

    Grup sayısı `PASSWORD_MIN_LENGTH` tutana kadar artar; doğrulayıcıların reddettiği aday yeniden
    üretilir. Şifre hiçbir yerde saklanmaz; çağıran onu yalnızca bir kez gösterir.
    """
    for groups in range(3, 9):
        for _ in range(20):
            candidate = "-".join(
                "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(4))
                for _ in range(groups)
            )
            try:
                password_validation.validate_password(candidate, user)
            except DjangoValidationError:
                continue
            return candidate
    raise RuntimeError("Şifre politikasına uyan geçici şifre üretilemedi.")


def _clean_username(username: str) -> str:
    value = (username or "").strip()
    if not USERNAME_RE.match(value):
        raise BusinessRuleError(
            "invalid_username",
            "Kullanıcı adı en az 2 karakter olmalı ve yalnızca küçük harf (Türkçe karakter "
            "olmadan), rakam, nokta, alt çizgi ve tire içermeli (ör. ahmet.yilmaz).",
        )
    return value


def _clean_full_name(full_name: str) -> str:
    value = (full_name or "").strip()
    if not value:
        raise BusinessRuleError("full_name_required", "Ad soyad gerekli.")
    return value


def active_admins() -> QuerySet[User]:
    """Aktif yöneticiler: superuser'lar ve `admin` rolündekiler."""
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name=ADMIN))
        .distinct()
    )


def _ensure_another_admin(user: User, message: str) -> None:
    """`user` dışında aktif bir yönetici kalmayacaksa `BusinessRuleError("last_admin")`."""
    if not active_admins().exclude(pk=user.pk).exists():
        raise BusinessRuleError("last_admin", message)


def create_user(
    actor: User,
    *,
    username: str,
    full_name: str,
    email: str = "",
    phone: str = "",
    roles: Iterable[str] = (),
) -> tuple[User, str]:
    """Yeni kullanıcı açar; sistemin ürettiği geçici şifreyi döner.

    Geçici şifre yalnızca bu dönüş değerinde görünür, hiçbir yerde saklanmaz ve denetim günlüğüne
    yazılmaz. Kullanıcı ilk girişte kendi şifresini belirlemeden başka işlem yapamaz
    (`must_change_password`, `core.middleware`).

    - Kullanıcı adı: küçük harf, rakam, `.`, `_`, `-` (`invalid_username`); büyük/küçük harf
      farkıyla bile var olan bir adla aynı olamaz (`username_taken`). Sonradan değiştirilemez.
    - Ad soyad zorunlu (`full_name_required`); roller `set_user_roles` kurallarıyla atanır.
    """
    username = _clean_username(username)
    full_name = _clean_full_name(full_name)
    with transaction.atomic():
        if User.objects.filter(username__iexact=username).exists():
            raise BusinessRuleError("username_taken", "Bu kullanıcı adı zaten kullanılıyor.")
        user = User(
            username=username,
            full_name=full_name,
            email=(email or "").strip(),
            phone=(phone or "").strip(),
            must_change_password=True,
        )
        password = generate_temporary_password(user)
        user.set_password(password)
        save_with_audit(user, actor, note="Kullanıcı açıldı")
        set_user_roles(user, roles, actor, note="Kullanıcı açıldı")
    return user, password


def update_user(
    actor: User,
    user: User,
    *,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> User:
    """Kullanıcının kişisel bilgilerini günceller; verilmeyen alan değişmez.

    Kullanıcı adı değiştirilemez (denetim kayıtlarında ve @bahsetmelerde geçer). Roller burada
    değişmez: var olan kullanıcının rolleri ve kişiye özel yetkileri Sistem › Kullanıcılar ›
    Yetkiler ekranında, gerekçe yazılarak `set_user_access` ile değişir (plan §8 madde 13).
    Değişiklikler denetim günlüğüne yazılır.
    """
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if full_name is not None:
            user.full_name = _clean_full_name(full_name)
        if email is not None:
            user.email = email.strip()
        if phone is not None:
            user.phone = phone.strip()
        save_with_audit(user, actor, note="Kullanıcı bilgileri güncellendi")
    return user


def set_user_active(actor: User, user: User, active: bool) -> User:
    """Kullanıcıyı pasife alır ya da yeniden etkinleştirir; kullanıcılar silinmez.

    Pasif kullanıcı giriş yapamaz; açık oturumu bir sonraki isteğinde düşer (kimlik doğrulama arka
    ucu pasif kullanıcıyı tanımaz). Admin kendini pasife alamaz (`cannot_deactivate_self`); başka
    aktif yönetici kalmayacaksa yönetici pasife alınamaz (`last_admin`). Durum zaten istenen
    gibiyse hiçbir şey yapılmaz.
    """
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.is_active == active:
            return user
        if not active:
            if user.pk == actor.pk:
                raise BusinessRuleError(
                    "cannot_deactivate_self", "Kendi hesabınızı pasife alamazsınız."
                )
            if user.is_admin:
                _ensure_another_admin(
                    user, "Başka aktif sistem yöneticisi olmadığı için bu hesap pasife alınamaz."
                )
        user.is_active = active
        save_with_audit(
            user,
            actor,
            note="Kullanıcı yeniden etkinleştirildi" if active else "Kullanıcı pasife alındı",
        )
    return user


def reset_user_password(actor: User, user: User) -> str:
    """Kullanıcıya yeni geçici şifre üretir ve döner (yalnızca bu dönüş değerinde görünür).

    Kullanıcı bir sonraki girişte kendi şifresini belirler (`must_change_password`). Şifre
    değiştiği için kullanıcının açık oturumları kapanır; hatalı denemelerden doğan hesap kilidi de
    açılır. Kendi şifreniz Güvenlik sayfasından değişir (`use_security_page`); pasif kullanıcının
    şifresi sıfırlanmaz (`user_inactive`).
    """
    if user.pk == actor.pk:
        raise BusinessRuleError(
            "use_security_page", "Kendi şifrenizi Güvenlik sayfasından değiştirin."
        )
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if not user.is_active:
            raise BusinessRuleError(
                "user_inactive", "Pasif kullanıcının şifresi sıfırlanamaz; önce etkinleştirin."
            )
        was_locked = security.is_locked(user.get_username())
        password = generate_temporary_password(user)
        user.set_password(password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])  # şifre: core.signals
        security.reset_failed_logins(user.get_username())
        note = "Şifre sıfırlandı; kullanıcı girişte kendi şifresini belirleyecek"
        if was_locked:
            note += " (hesap kilidi açıldı)"
        log_change(_real_actor(actor), user, AuditLog.Action.CUSTOM, note=note)
    return password


def login_user(request: HttpRequest, username: str, password: str, otp_code: str = "") -> User:
    """Kullanıcı adı/şifreyi (ve kuruluysa iki aşamalı doğrulama kodunu) doğrular, oturum açar.

    - Hatalı bilgi ya da pasif kullanıcıda `BusinessRuleError("invalid_credentials")`.
    - Hesap kilitliyse `account_locked` (kullanıcı adı var olmasa da aynı yanıt; `core.security`).
    - Doğrulayıcı uygulaması kurulu kullanıcıda kod yoksa `otp_required`, hatalıysa `invalid_otp`
      (hatalı kod başarısız giriş sayılır). Kod yerine kurtarma kodu da girilebilir.

    Başarılı ve başarısız denemeler Django'nun giriş sinyalleriyle denetim günlüğüne yazılır
    (`core.signals`); yönetim paneli girişi de aynı yoldan denetlenir.
    """
    user = auth.authenticate(request, username=username, password=password)
    if not isinstance(user, User):
        if security.is_locked(username):
            raise BusinessRuleError(
                "account_locked",
                "Çok sayıda hatalı deneme nedeniyle hesap "
                f"{security.lockout_minutes()} dakika kilitlendi. Daha sonra tekrar deneyin "
                "ya da sistem yöneticisine başvurun.",
            )
        raise BusinessRuleError("invalid_credentials", "Kullanıcı adı veya şifre hatalı.")
    if security.otp_enabled(user):
        if not otp_code.strip():
            raise BusinessRuleError(
                "otp_required", "Telefonunuzdaki doğrulayıcı uygulamadaki kodu girin."
            )
        if not security.verify_second_factor(user, otp_code):
            security.report_failed_second_factor(request, username)
            if security.is_locked(username):
                raise BusinessRuleError(
                    "account_locked",
                    "Çok sayıda hatalı deneme nedeniyle hesap "
                    f"{security.lockout_minutes()} dakika kilitlendi.",
                )
            raise BusinessRuleError("invalid_otp", "Doğrulama kodu hatalı.")
    auth.login(request, user)
    return user


def logout_user(request: HttpRequest) -> None:
    """Oturumu kapatır. Giriş yapmış kullanıcının çıkışı sinyalle denetim günlüğüne yazılır."""
    auth.logout(request)


# --- ekler ---------------------------------------------------------------------------------------


def attachment_target(
    label: str, object_id: int, user: User | None = None
) -> tuple[ContentType, models.Model]:
    """`"app_label.model"` + kimlik → (ContentType, kayıt). Ek alamayan tür ya da olmayan kayıtta
    `BusinessRuleError`. `user` verilirse kaydı kendi ekranında göremeyen için de kayıt yokmuş gibi
    `record_not_found` (`core.records`)."""
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
    if target is None or (user is not None and not records.can_view(user, target)):
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
    content_type, target = attachment_target(target_type, object_id, actor)
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


# --- KVKK saklama süreleri (Faz 5, docs/KVKK.md) -------------------------------------------------


def purge_expired_personal_data(now: Any = None) -> dict[str, int]:
    """Saklama süresi dolan kişisel verileri temizler; her gece Celery Beat çalıştırır.

    - Giriş, çıkış ve başarısız giriş kayıtlarındaki IP adresleri `AUDIT_IP_RETENTION_DAYS`
      sonra silinir (kaydın kendisi kalır). Denetim kayıtları değiştirilemez kuralının bilinçli ve
      tek istisnasıdır: yalnızca IP alanı boşaltılır.
    - Süresi dolmuş oturumlar ve 1 günden eski, kilidi bitmiş giriş sayaçları silinir.
    """
    from datetime import timedelta

    from django.contrib.sessions.models import Session

    from apps.core.models import LoginLockout

    now = now or timezone.now()
    cutoff = now - timedelta(days=int(settings.AUDIT_IP_RETENTION_DAYS))
    ips = AuditLog.objects.filter(
        action__in=[AuditLog.Action.LOGIN, AuditLog.Action.LOGOUT, AuditLog.Action.LOGIN_FAILED],
        timestamp__lt=cutoff,
        ip_address__isnull=False,
    ).update(ip_address=None)
    sessions, _ = Session.objects.filter(expire_date__lt=now).delete()
    lockouts, _ = (
        LoginLockout.objects.filter(updated_at__lt=now - timedelta(days=1))
        .exclude(locked_until__gt=now)
        .delete()
    )
    return {"audit_ips": ips, "sessions": sessions, "lockouts": lockouts}


# --- yetki kataloğu (docs/plan/kisi-yetkileri.md §5.2) -----------------------------------------

# pg_advisory_xact_lock anahtarı: yetki kataloğu kopyası.
ACCESS_SYNC_LOCK_ID = 7_302_011


@transaction.atomic
def sync_access_catalog() -> tuple[AccessCatalogSnapshot, bool]:
    """Yetki kataloğu son sürüm kopyasından farklıysa yeni kopyayı saklar.

    Bölümler ya da rol paketleri yeni bir sürümle değişince bir kopya ve denetim günlüğüne
    "Yetki paketleri değişti." kaydı yazılır; değişmediyse hiçbir şey yazılmaz. Böylece geçmiş
    bir tarihteki yetkiler yeniden kurulabilir. `sync_access_catalog` komutu her kurulumda
    (canlıdaki göç servisi) çağırır. Döner: (son kopya, yeni yazıldı mı).
    """
    digest = access.catalog_hash()
    # Tablo boşken de çalışan işlem kilidi: aynı anda çalışan iki kurulum çift kopya yazmaz.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ACCESS_SYNC_LOCK_ID])
    latest = AccessCatalogSnapshot.objects.order_by("-id").first()
    if latest is not None and latest.catalog_hash == digest:
        return latest, False
    snapshot = AccessCatalogSnapshot.objects.create(catalog_hash=digest, catalog=access.catalog())
    previous = latest.catalog_hash if latest is not None else None
    log_change(
        None,
        snapshot,
        AuditLog.Action.CUSTOM,
        {"catalog_hash": [previous, digest]},
        note="Yetki paketleri değişti.",
    )
    return snapshot, True
