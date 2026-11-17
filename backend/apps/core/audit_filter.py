"""Denetim günlüğü süzmesi (docs/plan/kisi-yetkileri.md §5.6 "Denetim günlüğü süzmesi", §8 madde 7).

Her modül kendi modelleri için gereken yetkiyi ve gizli alanları `access.py`'sinde kaydeder
(`core.access.register_audit_model`; plan §5.1):

    register_audit_model("personnel.employeewage", requires=[WAGES])
    register_audit_model(
        "purchasing.purchaseorder", requires=[PRICES], fields=PRICE_FIELDS, nested=True,
        note=AMOUNT_NOTE,
    )

Süzme yalnız kaydı olan modellere uygulanır. Satır kuralları (ör. sorun bildirimi) ve yalnız admin
bölümleri (ör. kodlama sistematiği) süzme yapmaz. Yorum ve ek kayıtları bağlı oldukları kaydı izler
(`register_audit_parent`): bağlı kaydın modeli bütünüyle gizleniyorsa (ör. olay) onlar da gizlenir.

Karar veritabanında verilir: sayfalama, sayım, ayrıntı (gizli kayıt 404) ve arama aynı süzgeçten
geçer; not araması kişiye gizlenen notu kapsamaz (`NOTE` açıklaması). Alanlar yanıtta gizlenir
(`mask_entries`).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import (
    BooleanField,
    Case,
    Expression,
    F,
    Q,
    QuerySet,
    TextField,
    Value,
    When,
)
from django.db.models.sql.compiler import SQLCompiler

from apps.core import access
from apps.core.access import AuditRule
from apps.core.models import AuditLog, User
from apps.core.records import HistoryFilter

# Kişiye gösterilen not (gizliyse boş); arama bu açıklamada yapılır.
NOTE = "audit_note"
HIDDEN = "audit_hidden"


class OnlyKeys(Expression):
    """`changes` boş olmayan bir nesne ve bütün anahtarları verilen listede mi?"""

    output_field = BooleanField()

    def __init__(self, expression: Any, keys: Iterable[str]) -> None:
        super().__init__(output_field=BooleanField())
        self.expression = expression
        self.keys = sorted(keys)

    def get_source_expressions(self) -> list[Any]:
        return [self.expression]

    def set_source_expressions(self, exprs: Any) -> None:
        (self.expression,) = exprs

    def as_sql(self, compiler: SQLCompiler, connection: Any) -> Any:
        sql, params = compiler.compile(self.expression)
        text = (
            f"(CASE WHEN jsonb_typeof({sql}) = 'object' "
            f"THEN ({sql} <> '{{}}'::jsonb AND ({sql} - %s::text[]) = '{{}}'::jsonb) "
            "ELSE false END)"
        )
        return text, [*params, *params, *params, self.keys]


@dataclass(frozen=True)
class Mask:
    """Bir kuralın gizlediği alanlar; `name` kaydın kurala girip girmediğini taşıyan açıklama."""

    name: str
    fields: frozenset[str]
    nested: bool


@dataclass(frozen=True)
class AuditView:
    """Bir kişinin denetim günlüğünde göremedikleri."""

    hidden: Q | None = None
    note_hidden: Q | None = None
    masks: tuple[tuple[Mask, Q], ...] = ()


def _active(user: Any) -> User | None:
    if not isinstance(user, User) or not user.is_authenticated or not user.is_active:
        return None
    return user


def allowed(user: Any, rule: AuditRule) -> bool:
    """Kişi kuralın kayıtlarını ve alanlarını görür mü?"""
    active = _active(user)
    if active is None:
        return False
    if active.is_admin:
        return True
    if rule.admin_only:
        return False
    return all(active.access.allows(key, level) for key, level in rule.requires)


def _content_type_id(label: str) -> int:
    return ContentType.objects.get_for_model(apps.get_model(label)).pk


def _rows(rule: AuditRule) -> Q | None:
    rows = rule.rows() if callable(rule.rows) else rule.rows
    return rows if rows is None or isinstance(rows, Q) else Q(rows)


def _scope(rule: AuditRule) -> Q:
    """Kuralın uygulandığı denetim kayıtları."""
    base = (
        Q(content_type_id=_content_type_id(rule.label))
        if rule.label is not None
        else Q(content_type__isnull=True)
    )
    rows = _rows(rule)
    return base if rows is None else base & rows


def _any(parts: list[Q]) -> Q | None:
    if not parts:
        return None
    combined = parts[0]
    for part in parts[1:]:
        combined |= part
    return combined


def _hidden_children(label: str, whole: frozenset[int], seen: frozenset[str]) -> Any:
    """Bağlı olduğu kayıt gizlenen yorum ya da ek kimlikleri (eki olan yorum: iki düzey)."""
    content_type_field, object_id_field = access.audit_parents()[label]
    condition = Q(**{f"{content_type_field}_id__in": sorted(whole)})
    for other in sorted(access.audit_parents()):
        if other == label or other in seen:
            continue
        condition |= Q(
            **{
                f"{content_type_field}_id": _content_type_id(other),
                f"{object_id_field}__in": _hidden_children(other, whole, seen | {label}),
            }
        )
    return apps.get_model(label)._base_manager.filter(condition).values("pk")


def view_for(user: Any) -> AuditView:
    """Kişinin denetim günlüğünde göremedikleri: gizli kayıtlar, gizli notlar, gizli alanlar."""
    hidden: list[Q] = []
    notes: list[Q] = []
    masks: list[tuple[Mask, Q]] = []
    whole: set[int] = set()
    for number, rule in enumerate(access.audit_rules()):
        if allowed(user, rule):
            continue
        scope = _scope(rule)
        if rule.hides_rows:
            hidden.append(scope)
            if rule.label is not None and rule.rows is None:
                whole.add(_content_type_id(rule.label))
            continue
        note: Q | None = None
        if rule.note is not None:
            note = Q(note__regex=rule.note)
        if rule.note_with_fields:
            changed = Q(changes__has_any_keys=sorted(rule.fields))
            note = changed if note is None else note | changed
        if note is not None:
            note = scope & ~Q(note="") & note
            notes.append(note)
            # Değişikliği olmayan kayıt, notu gizliyse listelenmez.
            hidden.append(note & Q(changes={}))
        if rule.fields:
            masks.append((Mask(f"audit_mask_{number}", rule.fields, rule.nested), scope))
            # Yalnız gizli alanları değiştiren kayıt listelenmez.
            hidden.append(scope & Q(OnlyKeys(F("changes"), rule.fields)))
    if whole:
        for label in sorted(access.audit_parents()):
            hidden.append(
                Q(
                    content_type_id=_content_type_id(label),
                    object_id__in=_hidden_children(label, frozenset(whole), frozenset()),
                )
            )
    return AuditView(hidden=_any(hidden), note_hidden=_any(notes), masks=tuple(masks))


def _flag(condition: Q | None) -> Any:
    if condition is None:
        return Value(False, output_field=BooleanField())
    return Case(
        When(condition, then=Value(True)), default=Value(False), output_field=BooleanField()
    )


def visible_entries(view: AuditView, queryset: QuerySet[AuditLog]) -> QuerySet[AuditLog]:
    """Kişinin görebildiği denetim kayıtları; `NOTE` gösterilen not, maskeler alan açıklaması."""
    note: Any = F("note")
    if view.note_hidden is not None:
        note = Case(
            When(view.note_hidden, then=Value("")), default=F("note"), output_field=TextField()
        )
    queryset = queryset.annotate(**{NOTE: note})
    if view.hidden is not None:
        queryset = queryset.annotate(**{HIDDEN: _flag(view.hidden)}).filter(**{HIDDEN: False})
    for mask, scope in view.masks:
        queryset = queryset.annotate(**{mask.name: _flag(scope)})
    return queryset


def mask_entries(view: AuditView, entries: Iterable[AuditLog]) -> None:
    """Yanıttan önce kayıtların gizli not ve alanlarını çıkarır (yalnız bellekte; kayıtlar
    yazılmaz)."""
    for entry in entries:
        if hasattr(entry, NOTE):
            entry.note = getattr(entry, NOTE)
        for mask, _scope_q in view.masks:
            if getattr(entry, mask.name, False):
                entry.changes = HistoryFilter(fields=mask.fields, nested=mask.nested).changes(
                    entry.changes
                )


def entries_for(user: Any, queryset: QuerySet[AuditLog] | None = None) -> QuerySet[AuditLog]:
    """Kişinin görebildiği denetim kayıtları (görünüm dışı kullanım ve testler için)."""
    base = AuditLog.objects.all() if queryset is None else queryset
    return visible_entries(view_for(user), base)


def model_errors() -> list[str]:
    """Kuralların bilinmeyen model etiketleri (sistem denetimi ve testler)."""
    errors: list[str] = []
    labels = {rule.label for rule in access.audit_rules() if rule.label is not None}
    for label in sorted(labels | set(access.audit_parents())):
        try:
            apps.get_model(label)
        except (LookupError, ValueError):
            errors.append(f"{label}: denetim günlüğü kuralının modeli yok.")
    return errors
