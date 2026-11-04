"""Kodlama sistematiği yazma işlemleri.

- `update_scheme`: biçimi değiştirir (yalnız admin, değişiklik notu zorunlu); her değişiklik
  denetim günlüğüne ve değiştirilemez `CodeSchemeRevision` satırına yazılır.
- `check_master_code` / `claim_master_code`: ana veri kaydı yazılmadan önce kod kuralları ve
  kaydetme transaction'ında sayaç kilidiyle kodu alma.
- `record_code_change`: kodu değişen kaydın eski kodunu geçerlilik aralığıyla saklar.
"""

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import connection, models, transaction
from django.utils import timezone

from apps.core.audit import log_change
from apps.core.coding import formats, selectors
from apps.core.coding.registry import DOCUMENT, LOT, MASTER, STANDARD, CodeType, code_type
from apps.core.exceptions import BusinessRuleError
from apps.core.models import (
    AuditLog,
    CodeHistory,
    CodeScheme,
    CodeSchemeRevision,
    CodeSequence,
    User,
)
from apps.core.permissions import user_has_role
from apps.core.roles import ADMIN
from apps.core.services import save_with_audit

ADMIN_ONLY_MESSAGE = "Kodlama ayarlarını yalnızca sistem yöneticisi değiştirir."
CODE_LOCK_MESSAGE = "Kod oluşturulduktan sonra yalnızca sistem yöneticisi değiştirebilir."
# Önerilenden en çok bu kadar ileri yazılan numara sayacı ilerletir; daha ilerisi ilerletmez.
COUNTER_WINDOW = 10
# Biçim değişikliklerini sıraya sokan PostgreSQL işlem kilidi (önek ayırma yarışına karşı).
_SCHEME_LOCK_ID = 730_101


def _real_actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def require_admin(actor: User | None) -> None:
    """Admin değilse `PermissionDenied` (API'de 403)."""
    if not user_has_role(actor, (ADMIN,)):
        raise PermissionDenied(ADMIN_ONLY_MESSAGE)


def get_type(key: str) -> CodeType:
    """Kayıtlı kod türü; yoksa `BusinessRuleError("unknown_code_type")`."""
    found = code_type(key)
    if found is None:
        raise BusinessRuleError("unknown_code_type", "Tanımsız kod türü.")
    return found


def _lock_schemes() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_SCHEME_LOCK_ID])


def _new_row(item: CodeType) -> CodeScheme:
    fmt = selectors.default_format(item)
    return CodeScheme(
        key=item.key,
        kind=item.kind,
        prefix=fmt.prefix,
        type_prefixes=dict(fmt.type_prefixes),
        width=fmt.width,
        year_format=fmt.year_format if item.kind == DOCUMENT else "",
        date_format=fmt.date_format if item.kind == LOT else "",
        is_active=False,
        revision=0,
    )


def _clean_counters(
    item: CodeType, fmt: formats.Format, counters: Mapping[str, Any]
) -> dict[str, int]:
    if item.kind != MASTER or item.free:
        raise BusinessRuleError("counters_not_allowed", "Bu türde sayaç düzeltilmez.")
    allowed = set(fmt.prefixes())
    result: dict[str, int] = {}
    for prefix, value in counters.items():
        prefix = str(prefix).strip().upper()
        if prefix not in allowed:
            raise BusinessRuleError("unknown_prefix", f"“{prefix}” bu türün öneki değil.")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise BusinessRuleError(
                "invalid_counter", "Sıradaki numara 1 ya da daha büyük bir tam sayı olmalıdır."
            )
        result[prefix] = value
    return result


def _set_counters(item: CodeType, counters: Mapping[str, int]) -> dict[str, list[int]]:
    """Sayaçları "sıradaki numara"ya göre düzeltir; eski → yeni (sıradaki numara) döner."""
    changes: dict[str, list[int]] = {}
    for prefix, next_number in sorted(counters.items()):
        sequence = lock_sequence(item, prefix)
        old = sequence.last_number + 1
        if old == next_number:
            continue
        sequence.last_number = next_number - 1
        sequence.save(update_fields=["last_number"])
        changes[prefix] = [old, next_number]
    return changes


@transaction.atomic
def update_scheme(
    actor: User,
    key: str,
    *,
    note: str,
    prefix: str | None = None,
    width: int | None = None,
    type_prefixes: Mapping[str, str] | None = None,
    year_format: str | None = None,
    date_format: str | None = None,
    is_active: bool | None = None,
    counters: Mapping[str, Any] | None = None,
) -> CodeScheme:
    """Kod türünün biçimini değiştirir; yalnızca bundan sonra verilecek kodları etkiler.

    - Yalnız admin (`PermissionDenied`); standart ve kilitli türler değiştirilemez
      (`scheme_locked`); değişiklik notu zorunlu (`note_required`).
    - Önek tüm türlerde tektir, geçmişte başka türün kullandığı önek verilmez (`prefix_in_use`);
      sıra hanesi bu dönemin sayacına yetmeli (`sequence_too_narrow`).
    - `counters` ana veride sıradaki numarayı düzeltir: `{"MLZ": 25}`.
    - Değişiklik denetim günlüğüne (alan farkları, not) ve `CodeSchemeRevision`'a yazılır.
    """
    require_admin(actor)
    item = get_type(key)
    if item.kind == STANDARD:
        raise BusinessRuleError("scheme_locked", "Standart kodlar değiştirilmez.")
    if item.locked:
        raise BusinessRuleError(
            "scheme_locked", f"{item.label} numarasının biçimi ekrandan değiştirilemez."
        )
    note = (note or "").strip()
    if not note:
        raise BusinessRuleError("note_required", "Değişiklik notu yazın (geçmişte görünür).")
    _lock_schemes()
    row = CodeScheme.objects.select_for_update().filter(key=item.key).first()
    values: dict[str, Any] = {}
    for name, value in (
        ("prefix", prefix),
        ("width", width),
        ("type_prefixes", type_prefixes),
        ("year_format", year_format),
        ("date_format", date_format),
    ):
        if value is not None:
            values[name] = value
    fmt = selectors.candidate_format(item, row, values)
    selectors.check_format(item, fmt)
    clean_counters = _clean_counters(item, fmt, counters) if counters else {}
    if is_active is not None and item.kind != MASTER:
        raise BusinessRuleError("not_applicable", "Bu türde biçim etkinleştirilmez.")

    if row is None:
        row = save_scheme_row(_new_row(item), actor, note="Varsayılan biçim kaydedildi")
    before = (
        row.prefix,
        dict(row.type_prefixes or {}),
        row.width,
        row.year_format,
        row.date_format,
        row.is_active,
    )
    if item.kind == MASTER and not item.free:
        row.prefix = "" if item.type_field else fmt.prefix
        row.type_prefixes = dict(fmt.type_prefixes) if item.type_field else {}
        row.width = fmt.width
    elif item.kind != MASTER:
        row.prefix = fmt.prefix
        row.width = fmt.width
        row.year_format = fmt.year_format if item.kind == DOCUMENT else ""
        row.date_format = fmt.date_format if item.kind == LOT else ""
    if is_active is not None:
        row.is_active = is_active
    after = (
        row.prefix,
        dict(row.type_prefixes or {}),
        row.width,
        row.year_format,
        row.date_format,
        row.is_active,
    )
    counter_changes = _set_counters(item, clean_counters) if clean_counters else {}
    if before == after and not counter_changes:
        raise BusinessRuleError("no_change", "Kaydedilecek bir değişiklik yok.")
    row.revision += 1
    row = save_scheme_row(row, actor, note=note)
    if counter_changes:
        log_change(
            _real_actor(actor),
            row,
            AuditLog.Action.CUSTOM,
            {"counters": counter_changes},
            f"Sayaç düzeltildi: {note}",
        )
    CodeSchemeRevision.objects.create(
        scheme=row,
        revision=row.revision,
        prefix=row.prefix,
        type_prefixes=dict(row.type_prefixes or {}),
        width=row.width,
        year_format=row.year_format,
        date_format=row.date_format,
        is_active=row.is_active,
        counters={prefix: change[1] for prefix, change in counter_changes.items()},
        note=note,
        changed_by=_real_actor(actor),
    )
    return row


def save_scheme_row(row: CodeScheme, actor: User | None, *, note: str) -> CodeScheme:
    """Biçim satırını denetimli kaydeder (yalnızca bu modül çağırır)."""
    return save_with_audit(row, actor, note=note)


# --- ana veri kodları ------------------------------------------------------------------------


def can_change_code(actor: User | None) -> bool:
    """Kayıt açıldıktan sonra kodu yalnızca admin değiştirir (CUMHUR, 2026-11-04)."""
    return user_has_role(actor, (ADMIN,))


def ensure_can_change_code(actor: User | None) -> None:
    if not can_change_code(actor):
        raise PermissionDenied(CODE_LOCK_MESSAGE)


def _code(item: CodeType, instance: models.Model) -> str:
    return str(getattr(instance, item.field) or "")


def check_master_code(item: CodeType, instance: models.Model, *, previous_code: str | None) -> None:
    """Kayıt yazılmadan önce kod kuralları (yeni kayıtta ya da kod değiştiyse).

    - Kod başka bir kaydın eski koduysa `code_reserved` (biçim etkin olsun olmasın).
    - Biçim etkinse karakter kuralı (`invalid_characters`, `code_must_start_with_letter`,
      `code_too_long`) ve sıralı kodda biçim (`code_format`).
    """
    code = _code(item, instance)
    if previous_code is not None and code == previous_code:
        return
    if code and selectors.code_reserved(item, code, exclude_pk=instance.pk):
        raise BusinessRuleError(
            "code_reserved", f"{code} başka bir kaydın eski kodu; yeni kod olarak kullanılamaz."
        )
    row = selectors.scheme_row(item)
    if row is None or not row.is_active:
        return
    error = formats.character_error(
        code,
        scanned=item.scanned,
        allow_underscore=item.allow_underscore,
        max_length=item.max_length,
    )
    if error is not None:
        raise error
    if item.free:
        return
    fmt = selectors.format_from_row(item, row)
    prefix = selectors.instance_prefix(item, fmt, instance)
    if prefix is None:
        raise BusinessRuleError(
            "code_prefix_missing", f"{item.label} için bu türde kod öneki tanımlı değil."
        )
    if formats.master_number(code, prefix, fmt.width) is None:
        raise BusinessRuleError(
            "code_format",
            f"Kod {item.label.lower()} biçimine uymuyor; biçim: "
            f"{formats.master_code(prefix, fmt.width, 0)}.",
        )


def lock_sequence(item: CodeType, prefix: str) -> CodeSequence:
    """Önek sayacını kilitler; satır yoksa mevcut kodlardaki en büyük sayıyla oluşturur."""
    head = formats.stem(prefix)
    if not CodeSequence.objects.filter(key=item.key, stem=head).exists():
        # Eşzamanlı ilk çağrılarda çakışma olmaz (ignore_conflicts); kilit aşağıda alınır.
        start = selectors.highest_number(item, prefix)
        CodeSequence.objects.bulk_create(
            [CodeSequence(key=item.key, stem=head, last_number=start)], ignore_conflicts=True
        )
    return CodeSequence.objects.select_for_update().get(key=item.key, stem=head)


def assign_master_code(item: CodeType, instance: models.Model) -> None:
    """Kodu boş yeni kayda etkin biçimde sıradaki kodu verir (ör. Excel'de "Kod" boş bırakıldı).

    Biçim kapalıysa, serbest kodda ya da önek bulunamazsa dokunmaz (kod zorunluluğu alan
    doğrulamasında kalır). Önek sayacı kilitlenir; transaction içinde çağrılmalıdır.
    """
    if item.free or _code(item, instance) or not selectors.is_active(item):
        return
    fmt = selectors.effective_format(item)
    prefix = selectors.instance_prefix(item, fmt, instance)
    if prefix is None:
        return
    sequence = lock_sequence(item, prefix)
    code, _ = selectors.next_free(item, prefix, fmt.width, sequence.last_number)
    setattr(instance, item.field, code)


def claim_master_code(item: CodeType, instance: models.Model, *, previous_code: str | None) -> None:
    """Kaydetme transaction'ında, kayıt yazılmadan hemen önce çağrılır.

    Kod biçime uyuyorsa önek sayacı kilitlenir; kod bu arada başka kayda verildiyse yeni öneriyle
    `code_taken`. Önerilenden en çok `COUNTER_WINDOW` ileri numara sayacı ilerletir. Kilit
    transaction bitene kadar aynı önekte kod alan öteki kayıtları bekletir.
    """
    code = _code(item, instance)
    if item.free or not code or (previous_code is not None and code == previous_code):
        return
    fmt = selectors.effective_format(item)
    prefix = selectors.instance_prefix(item, fmt, instance)
    number = formats.master_number(code, prefix, fmt.width) if prefix else None
    if prefix is None or number is None:
        return
    sequence = lock_sequence(item, prefix)
    if selectors.code_in_use(item, code, exclude_pk=instance.pk):
        suggestion, _ = selectors.next_free(item, prefix, fmt.width, sequence.last_number)
        raise BusinessRuleError(
            "code_taken", f"{code} az önce başka bir kayda verildi. Yeni öneri: {suggestion}."
        )
    if sequence.last_number < number <= sequence.last_number + COUNTER_WINDOW:
        sequence.last_number = number
        sequence.save(update_fields=["last_number"])


def record_code_change(
    actor: User | None,
    item: CodeType,
    instance: models.Model,
    old_code: str,
    *,
    reason: str = CodeHistory.Reason.CHANGE,
    note: str = "",
    run_id: int | None = None,
) -> CodeHistory:
    """Kodu değişen kaydın eski kodunu geçerlilik aralığıyla saklar (değiştirilemez satır)."""
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(instance)
    last = (
        CodeHistory.objects.filter(
            content_type=content_type, object_id=instance.pk, field=item.field
        )
        .order_by("-valid_to", "-id")
        .first()
    )
    now = timezone.now()
    valid_from = last.valid_to if last is not None else getattr(instance, "created_at", None)
    return CodeHistory.objects.create(
        content_type=content_type,
        object_id=instance.pk,
        field=item.field,
        code=old_code,
        valid_from=min(valid_from or now, now),
        valid_to=now,
        reason=reason,
        note=note[:255],
        run_id=run_id,
        created_by=_real_actor(actor),
    )
