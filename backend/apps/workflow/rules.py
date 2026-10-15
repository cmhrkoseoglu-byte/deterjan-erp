"""Olay → görev/bildirim kural tablosu (Faz 1, Adım 1.5).

Kurallar kodda veri olarak tanımlıdır; `services.process_event` bir olay geldiğinde önce kapanış
kurallarını (bu olayla kapanan açık görevler), sonra açılış kurallarını uygular.

Olay payload sözleşmesi `docs/DECISIONS.md` ("İş akışı olay sözleşmesi") bölümündedir. Kısaca:
bir kaydı anlatan her sözlük (`Subject`) en az `{"model": "app_label.model", "id": <pk>}` içerir;
kullanıcıya görünen ad için `number`, `lot_no` ya da `repr` alanlarından biri bulunur.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from apps.core import event_names as ev
from apps.core.roles import DEPO, LABORATUVAR, PLANLAMA, SATIN_ALMA, URETIM, YONETIM

Payload = Mapping[str, Any]
Subject = Mapping[str, Any]
Text = str | Callable[[Subject], str]


def _self(payload: Payload) -> list[Subject]:
    return [payload]


@dataclass(frozen=True)
class CloseOn:
    """Görevi kapatan olay. `subject`, kapanış olayının payload'ından görevin bağlı olduğu kaydı
    bulur (varsayılan: payload'ın kendisi)."""

    event: str
    subject: Callable[[Payload], Subject | None] = lambda payload: payload


@dataclass(frozen=True)
class TaskRule:
    """Olay gelince bir role görev açar. `subjects` olaydan görev açılacak kayıtları çıkarır
    (bir mal kabulde birden çok lot olabilir); her kayda bir görev."""

    code: str
    event: str
    role: str
    title: Text
    description: Text = ""
    subjects: Callable[[Payload], list[Subject]] = _self
    close_on: tuple[CloseOn, ...] = ()


@dataclass(frozen=True)
class NotifyRule:
    """Olay gelince rollere bildirim gönderir (`when` koşulu sağlanırsa)."""

    code: str
    event: str
    roles: tuple[str, ...]
    title: Text
    body: Text = ""
    level: str = "INFO"
    when: Callable[[Payload], bool] = lambda payload: True


@dataclass(frozen=True)
class CancelTasksRule:
    """Olayın kaydına bağlı açık görevleri iptal eder; iptal edilen görevlerin rollerine ve
    `notify_roles`'a bildirim gönderir."""

    code: str
    event: str
    title: Text
    body: Text = ""
    notify_roles: tuple[str, ...] = field(default_factory=tuple)
    level: str = "WARNING"


Rule = TaskRule | NotifyRule | CancelTasksRule


def _sample_at(*stages: str) -> Callable[[Payload], list[Subject]]:
    """Numune olayının kendisi (numune görevi), aşama uyuyorsa."""

    def subjects(payload: Payload) -> list[Subject]:
        return [payload] if payload.get("stage") in stages else []

    return subjects


def _rework_lot(payload: Payload) -> list[Subject]:
    """Yeniden işleme kararında lot (planlama görevi lota bağlanır)."""
    lot = payload.get("lot")
    if payload.get("decision") != "REWORK" or not lot:
        return []
    return [
        {**lot, "sample_number": payload.get("number", ""), "reason": payload.get("reason", "")}
    ]


def _in_process_rejected(payload: Payload) -> bool:
    return payload.get("stage") == "IN_PROCESS" and payload.get("decision") == "REJECT"


def _expiring_body(payload: Payload) -> str:
    lots = payload.get("lots", [])
    lines = [
        f"{lot.get('lot_no', '')} — {lot.get('material_code', '')} "
        f"{lot.get('material_name', '')} (SKT {lot.get('expiry_date', '')})"
        for lot in lots[:20]
    ]
    if len(lots) > 20:
        lines.append(f"… ve {len(lots) - 20} lot daha")
    return "\n".join(lines)


def _below_min_body(payload: Payload) -> str:
    materials = payload.get("materials", [])
    lines = [
        f"{m.get('code', '')} {m.get('name', '')}: {m.get('quantity', '')} "
        f"(en az {m.get('min_stock', '')} {m.get('unit', '')})"
        for m in materials[:20]
    ]
    if len(materials) > 20:
        lines.append(f"… ve {len(materials) - 20} malzeme daha")
    return "\n".join(lines)


RULES: tuple[Rule, ...] = (
    # Faz 2: mal kabul ve şarj bitişinde quality numune açar; görev numuneye bağlıdır ve numune
    # karara bağlanınca (ya da iptal edilince) kapanır.
    TaskRule(
        code="incoming_qc",
        event=ev.SAMPLE_CREATED,
        role=LABORATUVAR,
        title="Giriş kontrolü: {lot_no}",
        description="{material_code} {material_name} — numune {number}",
        subjects=_sample_at("INCOMING"),
        close_on=(CloseOn(ev.SAMPLE_DECIDED), CloseOn(ev.SAMPLE_CANCELLED)),
    ),
    NotifyRule(
        code="lot_rejected",
        event=ev.LOT_REJECTED,
        roles=(DEPO, SATIN_ALMA),
        level="WARNING",
        title="Lot reddedildi: {lot_no}",
        body="{material_code} {material_name}. {note}",
    ),
    TaskRule(
        code="material_prep",
        event=ev.PRODUCTION_ORDER_APPROVED,
        role=DEPO,
        title="Malzeme hazırla: {number}",
        description="Üretim emri {number} onaylandı; ihtiyaç listesindeki malzemeleri hazırlayın.",
        close_on=(CloseOn(ev.PRODUCTION_ORDER_MATERIAL_READY),),
    ),
    TaskRule(
        code="start_batch",
        event=ev.PRODUCTION_ORDER_MATERIAL_READY,
        role=URETIM,
        title="Şarjı başlat: {number}",
        description="Üretim emri {number} için malzemeler hazır.",
        close_on=(CloseOn(ev.PRODUCTION_BATCH_STARTED, lambda payload: payload.get("order")),),
    ),
    NotifyRule(
        code="production_deviation",
        event=ev.PRODUCTION_DEVIATION,
        roles=(PLANLAMA, LABORATUVAR),
        level="WARNING",
        title="Tartım sapması: {order_number}",
        body=(
            "Şarj {batch_no}, {material_code} lot {lot_no}: planlanan {planned_quantity}, "
            "tartılan {actual_quantity} (%{deviation_pct}). {note}"
        ),
    ),
    TaskRule(
        code="batch_sample_analysis",
        event=ev.SAMPLE_CREATED,
        role=LABORATUVAR,
        title="Numune analizi: {lot_no}",
        description="{material_code} {material_name} — numune {number}",
        subjects=_sample_at("IN_PROCESS", "FINAL"),
        close_on=(CloseOn(ev.SAMPLE_DECIDED), CloseOn(ev.SAMPLE_CANCELLED)),
    ),
    TaskRule(
        code="conditional_release_approval",
        event=ev.SAMPLE_AWAITING_APPROVAL,
        role=YONETIM,
        title="Şartlı kabul onayı: {lot_no}",
        description="{material_code} {material_name} — numune {number}. {reason}",
        close_on=(CloseOn(ev.SAMPLE_DECIDED), CloseOn(ev.SAMPLE_IN_TEST)),
    ),
    TaskRule(
        code="rework_order",
        event=ev.SAMPLE_DECIDED,
        role=PLANLAMA,
        title="Yeniden işleme emri aç: {lot_no}",
        description="{material_code} {material_name} — numune {sample_number}. {reason}",
        subjects=_rework_lot,
        close_on=(
            CloseOn(ev.PRODUCTION_ORDER_APPROVED, lambda payload: payload.get("rework_lot")),
        ),
    ),
    NotifyRule(
        code="in_process_out_of_spec",
        event=ev.SAMPLE_DECIDED,
        roles=(URETIM, PLANLAMA),
        level="WARNING",
        title="Ara kontrol uygun değil: {lot_no}",
        body="{material_code} {material_name} — numune {number}. {reason}",
        when=_in_process_rejected,
    ),
    NotifyRule(
        code="bulk_lot_released",
        event=ev.LOT_RELEASED,
        roles=(PLANLAMA, URETIM),
        title="Bulk lot serbest bırakıldı: {lot_no}",
        body="{material_code} {material_name}",
        when=lambda payload: payload.get("material_type") == "BULK",
    ),
    NotifyRule(
        code="bulk_lot_rejected",
        event=ev.LOT_REJECTED,
        roles=(PLANLAMA, URETIM),
        level="WARNING",
        title="Bulk lot reddedildi: {lot_no}",
        body="{material_code} {material_name}. Üretim emri analiz bekliyor. {note}",
        when=lambda payload: payload.get("material_type") == "BULK",
    ),
    NotifyRule(
        code="production_low_yield",
        event=ev.PRODUCTION_LOW_YIELD,
        roles=(PLANLAMA, YONETIM),
        level="WARNING",
        title="Düşük verim: {order_number}",
        body="Şarj {batch_no}: verim %{yield_pct} (eşik %{threshold_pct}).",
    ),
    CancelTasksRule(
        code="production_order_cancelled",
        event=ev.PRODUCTION_ORDER_CANCELLED,
        notify_roles=(PLANLAMA,),
        title="Üretim emri iptal edildi: {number}",
        body="Emre bağlı açık görevler iptal edildi.",
    ),
    NotifyRule(
        code="lots_expiring",
        event=ev.LOTS_EXPIRING,
        roles=(DEPO, PLANLAMA),
        level="WARNING",
        title="SKT'si {days} gün içinde dolacak lotlar",
        body=_expiring_body,
        when=lambda payload: bool(payload.get("lots")),
    ),
    NotifyRule(
        code="below_min_stock",
        event=ev.BELOW_MIN_STOCK,
        roles=(DEPO, PLANLAMA),
        level="WARNING",
        title="Minimum stok altındaki malzemeler",
        body=_below_min_body,
        when=lambda payload: bool(payload.get("materials")),
    ),
)


def rules_for(event_name: str) -> list[Rule]:
    """Olayla açılan/bildirim gönderen kurallar, tablo sırasıyla."""
    return [rule for rule in RULES if rule.event == event_name]


def closing_rules_for(event_name: str) -> list[tuple[TaskRule, CloseOn]]:
    """Bu olayla kapanan görev kuralları ve kapanış tanımı."""
    return [
        (rule, close)
        for rule in RULES
        if isinstance(rule, TaskRule)
        for close in rule.close_on
        if close.event == event_name
    ]


def all_event_names() -> set[str]:
    """Kural tablosunun dinlediği tüm olaylar (açılış ve kapanış)."""
    names = {rule.event for rule in RULES}
    names.update(c.event for rule in RULES if isinstance(rule, TaskRule) for c in rule.close_on)
    return names


class _Blank(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def render(text: Text, subject: Subject) -> str:
    """Şablonu kayıt alanlarıyla doldurur; eksik alan boş metin olur."""
    if callable(text):
        return text(subject).strip()
    return " ".join(text.format_map(_Blank(subject)).split()).rstrip(" —:")
