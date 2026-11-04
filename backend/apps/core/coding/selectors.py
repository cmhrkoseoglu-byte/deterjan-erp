"""Kodlama sistematiği okuma işlemleri: etkin biçim, öneri, eski kodla bulma, ekran özeti.

Yazma işlemleri `core.coding.services` içindedir. Modüllerin modelleri `apps.get_model` ile, kod
türünün kaydındaki etiketten bulunur; `core` modül import etmez.
"""

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.core.coding import formats
from apps.core.coding.formats import Format
from apps.core.coding.registry import (
    DOCUMENT,
    LOT,
    MASTER,
    STANDARD,
    CodeType,
    code_types,
)
from apps.core.exceptions import BusinessRuleError
from apps.core.models import (
    CodeHistory,
    CodeScheme,
    CodeSchemeRevision,
    CodeSequence,
    DocumentSequence,
)

# Öneride en çok bu kadar dolu ya da ayrılmış numara atlanır.
SEARCH_LIMIT = 10_000


# --- biçim -----------------------------------------------------------------------------------


def scheme_row(code_type: CodeType) -> CodeScheme | None:
    """Türün kayıtlı biçim satırı; admin hiç değiştirmediyse None."""
    return CodeScheme.objects.filter(key=code_type.key).first()


def default_format(code_type: CodeType) -> Format:
    return Format(
        kind=code_type.kind,
        prefix=code_type.default_prefix,
        width=code_type.default_width,
        type_prefixes=dict(code_type.default_type_prefixes),
        year_format=code_type.default_year_format,
        date_format=code_type.default_date_format,
        free=code_type.free,
    )


def format_from_row(code_type: CodeType, row: CodeScheme | None) -> Format:
    """Satır varsa onun değerleri, yoksa kayıttaki varsayılan."""
    if row is None:
        return default_format(code_type)
    return Format(
        kind=code_type.kind,
        prefix=row.prefix or code_type.default_prefix,
        width=row.width or code_type.default_width,
        type_prefixes=dict(row.type_prefixes or code_type.default_type_prefixes),
        year_format=row.year_format or code_type.default_year_format,
        date_format=row.date_format or code_type.default_date_format,
        free=code_type.free,
    )


def effective_format(code_type: CodeType) -> Format:
    return format_from_row(code_type, scheme_row(code_type))


def is_active(code_type: CodeType) -> bool:
    """Ana veri biçimi etkin mi (öneri ve biçim zorunluluğu)."""
    if code_type.kind != MASTER:
        return False
    row = scheme_row(code_type)
    return bool(row and row.is_active)


def type_prefix(code_type: CodeType, fmt: Format, type_value: str | None) -> str | None:
    """Ana veri kaydının öneki: türe göre önekte kaydın türünden, değilse biçimin öneki."""
    if code_type.free:
        return None
    if code_type.type_field:
        return fmt.type_prefixes.get(str(type_value or "")) or None
    return fmt.prefix or None


def instance_prefix(code_type: CodeType, fmt: Format, instance: models.Model) -> str | None:
    value = getattr(instance, code_type.type_field, None) if code_type.type_field else None
    return type_prefix(code_type, fmt, value)


def format_hint(code_type: CodeType, fmt: Format, type_value: str | None = None) -> str:
    """Kullanıcıya gösterilen biçim (`MLZ-0000000`); serbest kodda boş."""
    prefix = type_prefix(code_type, fmt, type_value)
    return formats.master_code(prefix, fmt.width, 0) if prefix else ""


# --- kayıtlar ve eski kodlar -----------------------------------------------------------------


def model_class(code_type: CodeType) -> type[models.Model]:
    return apps.get_model(code_type.model)


def _content_type(code_type: CodeType) -> ContentType:
    return ContentType.objects.get_for_model(model_class(code_type))


def code_in_use(code_type: CodeType, code: str, *, exclude_pk: Any = None) -> bool:
    """Kod aynı türde başka bir kaydın güncel kodu mu?"""
    queryset = model_class(code_type)._base_manager.filter(**{code_type.field: code})
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.exists()


def code_reserved(code_type: CodeType, code: str, *, exclude_pk: Any = None) -> bool:
    """Kod aynı türde başka bir kaydın eski kodu mu? (Kullanılmış kod başka kayda verilmez.)"""
    queryset = CodeHistory.objects.filter(
        content_type=_content_type(code_type), field=code_type.field, code=code
    )
    if exclude_pk is not None:
        queryset = queryset.exclude(object_id=exclude_pk)
    return queryset.exists()


def used_codes(code_type: CodeType, prefix: str) -> set[str]:
    """Bu önekle başlayan güncel ve eski kodlar."""
    head = formats.stem(prefix)
    model = model_class(code_type)
    current = model._base_manager.filter(**{f"{code_type.field}__startswith": head}).values_list(
        code_type.field, flat=True
    )
    former = CodeHistory.objects.filter(
        content_type=_content_type(code_type), field=code_type.field, code__startswith=head
    ).values_list("code", flat=True)
    return {*current, *former}


def highest_number(code_type: CodeType, prefix: str) -> int:
    """Güncel ve eski kodlarda bu önekten sonraki en büyük sayı (sayacın başlangıcı)."""
    numbers = (formats.loose_number(code, prefix) for code in used_codes(code_type, prefix))
    return max((number for number in numbers if number is not None), default=0)


def counter_value(code_type: CodeType, prefix: str) -> int:
    """Verilen son sıra no: sayaç satırı varsa o, yoksa mevcut kodlardaki en büyük sayı."""
    row = CodeSequence.objects.filter(key=code_type.key, stem=formats.stem(prefix)).first()
    if row is not None:
        return row.last_number
    return highest_number(code_type, prefix)


def next_free(code_type: CodeType, prefix: str, width: int, after: int) -> tuple[str, int]:
    """`after`'dan sonraki ilk boş kod: dolu ya da başka kaydın eski kodu olan numara atlanır."""
    used = used_codes(code_type, prefix)
    number = after + 1
    for _ in range(SEARCH_LIMIT):
        code = formats.master_code(prefix, width, number)
        if code not in used:
            return code, number
        number += 1
    raise BusinessRuleError(
        "sequence_exhausted", "Sıradaki boş kod bulunamadı; sistem yöneticisi sayacı düzeltmeli."
    )


def suggest_code(code_type: CodeType, *, type_value: str | None = None) -> str | None:
    """Etkin ana veri biçiminde sıradaki kod; biçim kapalıysa, serbest kodda ya da önek
    bulunamazsa None. Kilitsiz bir bakıştır; kod kaydetmede yeniden denetlenir."""
    if code_type.kind != MASTER or code_type.free:
        return None
    row = scheme_row(code_type)
    if row is None or not row.is_active:
        return None
    fmt = format_from_row(code_type, row)
    prefix = type_prefix(code_type, fmt, type_value)
    if prefix is None:
        return None
    code, _ = next_free(code_type, prefix, fmt.width, counter_value(code_type, prefix))
    return code


def find_by_code[M: models.Model](
    model: type[M], code: str, *, field: str = "code"
) -> tuple[M | None, bool]:
    """Koda göre kayıt: önce güncel kod, sonra eski kod. (kayıt, eski_kodla_mı) döner."""
    if not code:
        return None, False
    current = model._base_manager.filter(**{field: code}).first()
    if current is not None:
        return current, False
    history = (
        CodeHistory.objects.filter(
            content_type=ContentType.objects.get_for_model(model), field=field, code=code
        )
        .order_by("-valid_to", "-id")
        .first()
    )
    if history is None:
        return None, False
    return model._base_manager.filter(pk=history.object_id).first(), True


def former_codes(instance: models.Model, *, field: str = "code") -> list[str]:
    """Kaydın eski kodları, en yeniden eskiye (tekrarsız)."""
    rows = CodeHistory.objects.filter(
        content_type=ContentType.objects.get_for_model(instance),
        object_id=instance.pk,
        field=field,
    ).order_by("-valid_to", "-id")
    seen: dict[str, None] = {}
    for code in rows.values_list("code", flat=True):
        seen.setdefault(code, None)
    current = getattr(instance, field, None)
    return [code for code in seen if code != current]


def former_code_map(
    model: type[models.Model], ids: Iterable[Any], *, field: str = "code"
) -> dict[Any, list[str]]:
    """Birden çok kaydın eski kodları (liste serializer'ları için tek sorgu)."""
    result: dict[Any, list[str]] = {}
    rows = CodeHistory.objects.filter(
        content_type=ContentType.objects.get_for_model(model), object_id__in=list(ids), field=field
    ).order_by("-valid_to", "-id")
    for object_id, code in rows.values_list("object_id", "code"):
        codes = result.setdefault(object_id, [])
        if code not in codes:
            codes.append(code)
    return result


def code_as_of(instance: models.Model, when: datetime, *, field: str = "code") -> str:
    """Kaydın `when` anındaki kodu (belgeler yeniden basılırken belgenin tarihindeki kod)."""
    row = (
        CodeHistory.objects.filter(
            content_type=ContentType.objects.get_for_model(instance),
            object_id=instance.pk,
            field=field,
            valid_from__lte=when,
            valid_to__gt=when,
        )
        .order_by("-valid_to", "-id")
        .first()
    )
    return row.code if row is not None else str(getattr(instance, field))


# --- belge ve lot sayaçları --------------------------------------------------------------------


def last_document_number(prefix: str, year: int) -> int:
    row = DocumentSequence.objects.filter(prefix=prefix, year=year).first()
    return row.last_number if row is not None else 0


def last_lot_number(code_type: CodeType, prefix: str, day: date) -> int:
    if code_type.lot_counter is None:
        return 0
    return code_type.lot_counter(prefix, day)


# --- önek ayırma ve biçim denetimi -------------------------------------------------------------


def _row_prefixes(prefix: str, type_prefixes: Mapping[str, str] | None) -> set[str]:
    return {value for value in (prefix, *(type_prefixes or {}).values()) if value}


def used_prefixes(kind: str, *, exclude_key: str = "") -> dict[str, str]:
    """Bu türdeki (ana veri, belge ya da lot) öteki kod türlerinin bugün ya da geçmişte
    kullandığı önekler → türün adı. Önek başka türe verilmez."""
    rows = {row.key: row for row in CodeScheme.objects.filter(kind=kind)}
    history: dict[str, set[str]] = {}
    for revision in CodeSchemeRevision.objects.filter(scheme__kind=kind).select_related("scheme"):
        history.setdefault(revision.scheme.key, set()).update(
            _row_prefixes(revision.prefix, revision.type_prefixes)
        )
    result: dict[str, str] = {}
    for item in code_types(kind):
        if item.key == exclude_key:
            continue
        prefixes = _row_prefixes(item.default_prefix, item.default_type_prefixes)
        row = rows.get(item.key)
        if row is not None:
            prefixes |= _row_prefixes(row.prefix, row.type_prefixes)
        prefixes |= history.get(item.key, set())
        for prefix in prefixes:
            result.setdefault(prefix, item.label)
    return result


def candidate_format(
    code_type: CodeType, row: CodeScheme | None, values: Mapping[str, Any]
) -> Format:
    """Mevcut biçimin üzerine istenen değişiklikler (kaydedilmez)."""
    current = format_from_row(code_type, row)
    type_prefixes = values.get("type_prefixes")
    return Format(
        kind=code_type.kind,
        prefix=str(values.get("prefix", current.prefix) or "").strip().upper(),
        width=int(values.get("width", current.width)),
        type_prefixes=(
            {str(k): str(v).strip().upper() for k, v in type_prefixes.items()}
            if isinstance(type_prefixes, Mapping)
            else dict(current.type_prefixes)
        ),
        year_format=str(values.get("year_format", current.year_format)),
        date_format=str(values.get("date_format", current.date_format)),
        free=code_type.free,
    )


def _check_prefixes_free(code_type: CodeType, prefixes: Iterable[str]) -> None:
    taken = used_prefixes(code_type.kind, exclude_key=code_type.key)
    for prefix in sorted(set(prefixes)):
        if prefix in taken:
            raise BusinessRuleError(
                "prefix_in_use",
                f"“{prefix}” öneki {taken[prefix]} için kullanılıyor ya da kullanıldı; başka bir "
                "önek seçin.",
            )


def _check_length(code_type: CodeType, longest: str, limit: int) -> None:
    if len(longest) > limit:
        raise BusinessRuleError(
            "pattern_too_long",
            f"Bu biçimle {code_type.label.lower()} {len(longest)} karakter olur; en fazla {limit} "
            "olabilir.",
        )


def _check_narrow(last: int, width: int) -> None:
    if formats.digits(last) > width:
        raise BusinessRuleError(
            "sequence_too_narrow",
            f"Bu dönemde {last} numara verildi; sıra hanesi en az {formats.digits(last)} "
            "olmalıdır.",
        )


def check_format(code_type: CodeType, fmt: Format, *, today: date | None = None) -> None:
    """İstenen biçimin kuralları; ihlalde `BusinessRuleError`. Biçim değiştirme ve önizleme
    aynı denetimi kullanır."""
    today = today or timezone.localdate()
    if code_type.kind == MASTER:
        if code_type.free:
            return
        formats.validate_width(MASTER, fmt.width)
        if code_type.type_field:
            expected = {value for value, _ in code_type.type_choices}
            if set(fmt.type_prefixes) != expected:
                raise BusinessRuleError(
                    "invalid_type_prefixes", "Her tür için bir önek girilmelidir."
                )
            prefixes = list(fmt.type_prefixes.values())
        else:
            prefixes = [fmt.prefix]
        for prefix in prefixes:
            formats.validate_prefix(MASTER, prefix)
            longest = formats.master_code(prefix, fmt.width, formats.largest_number(fmt.width))
            _check_length(code_type, longest, code_type.max_length)
        _check_prefixes_free(code_type, prefixes)
        return
    formats.validate_prefix(code_type.kind, fmt.prefix)
    formats.validate_width(code_type.kind, fmt.width)
    largest = formats.largest_number(fmt.width)
    if code_type.kind == DOCUMENT:
        formats.validate_year_format(fmt.year_format)
        _check_length(code_type, formats.document_number(fmt, today.year, largest), 31)
        _check_narrow(last_document_number(fmt.prefix, today.year), fmt.width)
    else:
        formats.validate_date_format(fmt.date_format)
        _check_length(code_type, formats.lot_number(fmt, today, largest), formats.MAX_LENGTH[LOT])
        _check_narrow(last_lot_number(code_type, fmt.prefix, today), fmt.width)
    _check_prefixes_free(code_type, [fmt.prefix])


# --- ekran özeti -------------------------------------------------------------------------------


def _user_name(user: Any) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "username", "")) if user else ""


def describe(
    code_type: CodeType,
    *,
    row: CodeScheme | None = None,
    fmt: Format | None = None,
    today: date | None = None,
    with_row: bool = True,
) -> dict[str, Any]:
    """Kodlama ekranındaki satır: biçim, örnek, sıradaki ve verilen son numara, durum."""
    today = today or timezone.localdate()
    if with_row and row is None:
        row = scheme_row(code_type)
    fmt = fmt or format_from_row(code_type, row)
    body: dict[str, Any] = {
        "key": code_type.key,
        "kind": code_type.kind,
        "label": code_type.label,
        "configurable": code_type.configurable,
        "locked": code_type.locked,
        "free": code_type.free,
        "scanned": code_type.scanned,
        "prefix": fmt.prefix,
        "width": fmt.width,
        "type_field": code_type.type_field,
        "type_prefixes": dict(fmt.type_prefixes),
        "year_format": fmt.year_format if code_type.kind == DOCUMENT else "",
        "date_format": fmt.date_format if code_type.kind == LOT else "",
        "is_active": bool(row and row.is_active) if code_type.kind == MASTER else False,
        "revision": row.revision if row is not None else 0,
        "updated_at": row.updated_at if row is not None else None,
        "updated_by": _user_name(row.updated_by) if row is not None else "",
        "format": "",
        "next": "",
        "longest": "",
        "last_number": 0,
        "types": [],
        "samples": [],
    }
    largest = formats.largest_number(fmt.width) if fmt.width else 0
    if code_type.kind == MASTER and not code_type.free:
        if code_type.type_field:
            for value, label in code_type.type_choices:
                prefix = fmt.type_prefixes.get(value, "")
                last = counter_value(code_type, prefix) if prefix else 0
                body["types"].append(
                    {
                        "value": value,
                        "label": label,
                        "prefix": prefix,
                        "format": formats.master_code(prefix, fmt.width, 0) if prefix else "",
                        "next": next_free(code_type, prefix, fmt.width, last)[0] if prefix else "",
                        "last_number": last,
                    }
                )
            first = body["types"][0] if body["types"] else None
            if first:
                body["format"], body["next"] = first["format"], first["next"]
                body["last_number"] = first["last_number"]
                body["longest"] = formats.master_code(first["prefix"], fmt.width, largest)
        elif fmt.prefix:
            last = counter_value(code_type, fmt.prefix)
            body["last_number"] = last
            body["format"] = formats.master_code(fmt.prefix, fmt.width, 0)
            body["next"] = next_free(code_type, fmt.prefix, fmt.width, last)[0]
            body["longest"] = formats.master_code(fmt.prefix, fmt.width, largest)
    elif code_type.kind == DOCUMENT:
        last = last_document_number(fmt.prefix, today.year)
        body["last_number"] = last
        body["format"] = formats.document_number(fmt, today.year, 0)
        body["next"] = formats.document_number(fmt, today.year, last + 1)
        body["longest"] = formats.document_number(fmt, today.year, largest)
    elif code_type.kind == LOT:
        last = last_lot_number(code_type, fmt.prefix, today)
        body["last_number"] = last
        body["format"] = formats.lot_number(fmt, today, 0)
        body["next"] = formats.lot_number(fmt, today, last + 1)
        body["longest"] = formats.lot_number(fmt, today, largest)
    if code_type.kind in (MASTER, STANDARD):
        model = model_class(code_type)
        body["samples"] = list(
            model._base_manager.order_by(code_type.field).values_list(code_type.field, flat=True)[
                :5
            ]
        )
    return body


def overview(kind: str | None = None) -> list[dict[str, Any]]:
    """Bütün kayıtlı türlerin ekran satırları."""
    rows = {row.key: row for row in CodeScheme.objects.select_related("updated_by")}
    today = timezone.localdate()
    return [
        describe(item, row=rows.get(item.key), today=today, with_row=False)
        for item in code_types(kind)
    ]


def preview(code_type: CodeType, values: Mapping[str, Any]) -> dict[str, Any]:
    """Kaydetmeden istenen biçimin örnekleri ve (varsa) ilk kural ihlali."""
    row = scheme_row(code_type)
    error: dict[str, str] | None = None
    try:
        fmt = candidate_format(code_type, row, values)
        check_format(code_type, fmt)
    except (BusinessRuleError, ValueError, TypeError) as exc:
        if isinstance(exc, BusinessRuleError):
            error = {"code": exc.code, "detail": exc.message}
        else:
            error = {"code": "invalid_value", "detail": "Biçim değerleri geçersiz."}
        return {"valid": False, "error": error, "example": None}
    return {"valid": True, "error": None, "example": describe(code_type, row=row, fmt=fmt)}
