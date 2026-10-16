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
from apps.core.roles import (
    DEPO,
    DOLUM,
    LABORATUVAR,
    PLANLAMA,
    SATIN_ALMA,
    SEVKIYAT,
    URETIM,
    YONETIM,
)

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


def _no_users(payload: Payload) -> list[int]:
    return []


@dataclass(frozen=True)
class NotifyRule:
    """Olay gelince rollere bildirim gönderir (`when` koşulu sağlanırsa). `users` payload'dan
    ayrıca bildirim alacak kullanıcı kimliklerini çıkarır (ör. siparişi oluşturan)."""

    code: str
    event: str
    roles: tuple[str, ...]
    title: Text
    body: Text = ""
    level: str = "INFO"
    when: Callable[[Payload], bool] = lambda payload: True
    users: Callable[[Payload], list[int]] = _no_users


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


def _sample_at(*stages: str, skip_finished: bool = False) -> Callable[[Payload], list[Subject]]:
    """Numune olayının kendisi (numune görevi), aşama uyuyorsa. `skip_finished`: mamul numunesi
    atlanır (dolum partisi bitince "Mamul kontrolü" görevi açılır)."""

    def subjects(payload: Payload) -> list[Subject]:
        if payload.get("stage") not in stages:
            return []
        if skip_finished and payload.get("material_type") == "FINISHED":
            return []
        return [payload]

    return subjects


def _output_lot(payload: Payload) -> list[Subject]:
    """Dolum partisinin lotu (mamul kontrolü görevi lota bağlanır)."""
    lot = payload.get("output_lot")
    if not lot:
        return []
    return [
        {
            **lot,
            "order_number": payload.get("order_number", ""),
            "sample_number": payload.get("sample_number", ""),
        }
    ]


def _rework_lot(payload: Payload) -> list[Subject]:
    """Yeniden işleme kararında lot (planlama görevi lota bağlanır)."""
    lot = payload.get("lot")
    if payload.get("decision") != "REWORK" or not lot or payload.get("stage") == "RETURN":
        return []
    return [
        {**lot, "sample_number": payload.get("number", ""), "reason": payload.get("reason", "")}
    ]


def _return_rework_lot(payload: Payload) -> list[Subject]:
    """İade numunesinde yeniden işleme kararı: lot (mamul) planlamaya görevle bağlanır."""
    lot = payload.get("lot")
    if payload.get("decision") != "REWORK" or not lot or payload.get("stage") != "RETURN":
        return []
    return [
        {**lot, "sample_number": payload.get("number", ""), "reason": payload.get("reason", "")}
    ]


def _fully_planned_order(payload: Payload) -> Subject | None:
    """Siparişin tamamı sevkiyata planlandıysa sipariş ("Sevkiyat planla" görevi kapanır)."""
    return payload.get("order") if payload.get("order_fully_planned") else None


def _report_requester(payload: Payload) -> list[int]:
    user_id = payload.get("requested_by_id")
    return [user_id] if isinstance(user_id, int) else []


def _order_creator(payload: Payload) -> list[int]:
    user_id = payload.get("order_created_by_id")
    return [user_id] if isinstance(user_id, int) else []


def _shipment_lots_body(payload: Payload) -> str:
    lots = ", ".join(
        f"{lot.get('lot_no')} ({lot.get('quantity')})" for lot in payload.get("lots") or []
    )
    plate = payload.get("vehicle_plate") or ""
    return f"{payload.get('customer_name', '')}, sipariş {payload.get('order_number', '')}, " + (
        f"araç {plate}. Lotlar: {lots}" if plate else f"Lotlar: {lots}"
    )


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


def _lot_rejected_body(payload: Payload) -> str:
    """Satın alma lotunda tedarikçi de yazılır (tedarikçiye iade süreci için)."""
    head = f"{payload.get('material_code', '')} {payload.get('material_name', '')}."
    if payload.get("supplier_name"):
        head = f"{head} Tedarikçi: {payload['supplier_name']}."
    return " ".join(f"{head} {payload.get('note', '')}".split())


def _purchase_lines_body(payload: Payload) -> str:
    lines = [
        f"{line.get('material_code', '')} {line.get('material_name', '')}: "
        f"{line.get('quantity', '')} {line.get('line_unit', '')} — "
        f"teslim {line.get('expected_date', '')}"
        for line in payload.get("lines", [])[:20]
    ]
    return "\n".join([f"Tedarikçi: {payload.get('supplier_name', '')}", *lines])


def _shortage_body(payload: Payload) -> str:
    lines = [
        f"{line.get('product_code', '')} {line.get('product_name', '')}: "
        f"{line.get('quantity', '')} {line.get('unit', '')}"
        for line in payload.get("lines", [])
    ]
    head = f"{payload.get('customer_name', '')} siparişinde stok yetmedi."
    if payload.get("reason"):
        head = f"{head} {payload['reason']}."
    return "\n".join([head, *lines])


def _reserved_expiring_body(payload: Payload) -> str:
    lots = payload.get("lots", [])
    lines = [
        f"{lot.get('lot_no', '')} — {lot.get('material_code', '')} "
        f"(SKT {lot.get('expiry_date', '')}), rezerve {lot.get('reserved_quantity', '')} "
        f"{lot.get('unit', '')}: {', '.join(lot.get('orders', []))}"
        for lot in lots[:20]
    ]
    if len(lots) > 20:
        lines.append(f"… ve {len(lots) - 20} lot daha")
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
        body=_lot_rejected_body,
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
        subjects=_sample_at("IN_PROCESS", "FINAL", skip_finished=True),
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
    # Faz 2, Adım 2.2: dolum.
    TaskRule(
        code="packaging_prep",
        event=ev.FILLING_ORDER_APPROVED,
        role=DEPO,
        title="Ambalaj malzemesi hazırla: {number}",
        description="Dolum emri {number} ({product_code}) onaylandı; ambalaj malzemelerini dolum "
        "hattına hazırlayın.",
        close_on=(CloseOn(ev.FILLING_ORDER_MATERIAL_READY),),
    ),
    TaskRule(
        code="start_filling",
        event=ev.FILLING_ORDER_MATERIAL_READY,
        role=DOLUM,
        title="Dolumu başlat: {number}",
        description="Dolum emri {number} için ambalaj malzemesi hazır.",
        close_on=(CloseOn(ev.FILLING_RUN_STARTED, lambda payload: payload.get("order")),),
    ),
    TaskRule(
        code="finished_qc",
        event=ev.FILLING_RUN_COMPLETED,
        role=LABORATUVAR,
        title="Mamul kontrolü: {lot_no}",
        description="{material_code} {material_name} — dolum emri {order_number}, numune "
        "{sample_number}",
        subjects=_output_lot,
        close_on=(CloseOn(ev.SAMPLE_DECIDED, lambda payload: payload.get("lot")),),
    ),
    NotifyRule(
        code="filling_bulk_variance",
        event=ev.FILLING_BULK_VARIANCE,
        roles=(PLANLAMA, YONETIM),
        level="WARNING",
        title="Dolum bulk farkı: {number}",
        body=(
            "Dolum lotu {lot_no} ({product_code}, {good_units} adet): teorik "
            "{theoretical_quantity}, gerçek {actual_quantity} (%{variance_pct}, eşik "
            "%{threshold_pct})."
        ),
    ),
    NotifyRule(
        code="finished_lot_released",
        event=ev.LOT_RELEASED,
        roles=(SEVKIYAT, PLANLAMA),
        title="Sevke hazır: {lot_no}",
        body="{material_code} {material_name}",
        when=lambda payload: payload.get("material_type") == "FINISHED",
    ),
    NotifyRule(
        code="finished_lot_rejected",
        event=ev.LOT_REJECTED,
        roles=(PLANLAMA, DOLUM),
        level="WARNING",
        title="Mamul lot reddedildi: {lot_no}",
        body="{material_code} {material_name}. Dolum emri analiz bekliyor. {note}",
        when=lambda payload: payload.get("material_type") == "FINISHED",
    ),
    CancelTasksRule(
        code="filling_order_cancelled",
        event=ev.FILLING_ORDER_CANCELLED,
        notify_roles=(PLANLAMA,),
        title="Dolum emri iptal edildi: {number}",
        body="Emre bağlı açık görevler iptal edildi.",
    ),
    # Faz 3, Adım 3.3: müşteri iadesi.
    TaskRule(
        code="return_qc",
        event=ev.SAMPLE_CREATED,
        role=LABORATUVAR,
        title="İade kontrolü: {lot_no}",
        description="{material_code} {material_name} — numune {number}",
        subjects=_sample_at("RETURN"),
        close_on=(CloseOn(ev.SAMPLE_DECIDED), CloseOn(ev.SAMPLE_CANCELLED)),
    ),
    TaskRule(
        code="return_rework",
        event=ev.SAMPLE_DECIDED,
        role=PLANLAMA,
        title="İade lotu yeniden işlenecek: {lot_no}",
        description="{material_code} {material_name} — numune {sample_number}. {reason}",
        subjects=_return_rework_lot,
    ),
    TaskRule(
        code="return_scrap",
        event=ev.CUSTOMER_RETURN_SCRAP_REQUIRED,
        role=DEPO,
        title="İade imha et: {number}",
        description="{customer_name}: imha kararı verilen iade satırlarını imha edip kaydedin.",
        close_on=(CloseOn(ev.CUSTOMER_RETURN_CLOSED),),
    ),
    NotifyRule(
        code="return_closed",
        event=ev.CUSTOMER_RETURN_CLOSED,
        roles=(SEVKIYAT,),
        title="İade sonuçlandı: {number}",
        body="{customer_name}",
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
    # Faz 3, Adım 3.1: satış siparişi. "Sevkiyat planla" görevi sevkiyat planlanınca (Adım 3.2)
    # ya da sipariş kapanınca kapanır; eksik görevi eksik tamamen rezerve edilince kapanır.
    TaskRule(
        code="plan_shipment",
        event=ev.SALES_ORDER_CONFIRMED,
        role=SEVKIYAT,
        title="Sevkiyat planla: {number}",
        description="{customer_name} siparişi onaylandı.",
        close_on=(
            CloseOn(ev.SALES_ORDER_CLOSED),
            CloseOn(ev.SHIPMENT_PLANNED, _fully_planned_order),
        ),
    ),
    TaskRule(
        code="sales_shortage",
        event=ev.SALES_ORDER_SHORTAGE,
        role=PLANLAMA,
        title="Eksik ürün için üretim/dolum planla: {number}",
        description=_shortage_body,
        close_on=(CloseOn(ev.SALES_ORDER_FULLY_RESERVED), CloseOn(ev.SALES_ORDER_CLOSED)),
    ),
    CancelTasksRule(
        code="sales_order_cancelled",
        event=ev.SALES_ORDER_CANCELLED,
        title="Satış siparişi iptal edildi: {number}",
        body="Siparişe bağlı açık görevler iptal edildi.",
    ),
    NotifyRule(
        code="reserved_lots_expiring",
        event=ev.RESERVED_LOTS_EXPIRING,
        roles=(SEVKIYAT, PLANLAMA),
        level="WARNING",
        title="Rezerve lotların SKT'si {days} gün içinde doluyor",
        body=_reserved_expiring_body,
        when=lambda payload: bool(payload.get("lots")),
    ),
    # Faz 3, Adım 3.2: sevkiyat.
    TaskRule(
        code="pick_shipment",
        event=ev.SHIPMENT_PLANNED,
        role=DEPO,
        title="Toplama yap: {number}",
        description="{customer_name}, sipariş {order_number}.",
        close_on=(CloseOn(ev.SHIPMENT_LOADED),),
    ),
    TaskRule(
        code="dispatch_shipment",
        event=ev.SHIPMENT_LOADED,
        role=SEVKIYAT,
        title="Sevki onayla / irsaliye kes: {number}",
        description="{customer_name}, sipariş {order_number}, araç {vehicle_plate}.",
        close_on=(CloseOn(ev.SHIPMENT_DISPATCHED),),
    ),
    NotifyRule(
        code="shipment_dispatched",
        event=ev.SHIPMENT_DISPATCHED,
        roles=(YONETIM,),
        title="Sevk edildi: {number}",
        body=_shipment_lots_body,
        users=_order_creator,
    ),
    CancelTasksRule(
        code="shipment_cancelled",
        event=ev.SHIPMENT_CANCELLED,
        title="Sevkiyat iptal edildi: {number}",
        body="Sevkiyata bağlı açık görevler iptal edildi; toplanan lotlar yerine döndü.",
    ),
    # --- satın alma (Faz 4, Adım 4.2) ---
    TaskRule(
        code="purchase_request",
        event=ev.PURCHASE_REQUEST_CREATED,
        role=SATIN_ALMA,
        title="Satın alma talebi: {number} — {material_code} {material_name}",
        description="{quantity} {unit}, ihtiyaç tarihi {need_date}. {reason}",
        close_on=(CloseOn(ev.PURCHASE_REQUEST_ORDERED), CloseOn(ev.PURCHASE_REQUEST_CANCELLED)),
    ),
    TaskRule(
        code="purchase_order_approval",
        event=ev.PURCHASE_ORDER_PENDING_APPROVAL,
        role=YONETIM,
        title="Satın alma siparişini onayla: {number}",
        description="{supplier_name}, tutar {total} {currency} ({total_try} TL).",
        close_on=(
            CloseOn(ev.PURCHASE_ORDER_APPROVED),
            CloseOn(ev.PURCHASE_ORDER_RETURNED),
        ),
    ),
    NotifyRule(
        code="purchase_order_returned",
        event=ev.PURCHASE_ORDER_RETURNED,
        roles=(SATIN_ALMA,),
        level="WARNING",
        title="Sipariş taslağa geri gönderildi: {number}",
        body="{note}",
    ),
    NotifyRule(
        code="expected_delivery",
        event=ev.PURCHASE_ORDER_APPROVED,
        roles=(DEPO,),
        title="Beklenen teslimat: {number} ({expected_date})",
        body=_purchase_lines_body,
    ),
    NotifyRule(
        code="purchase_order_received",
        event=ev.PURCHASE_ORDER_RECEIVED,
        roles=(SATIN_ALMA,),
        title="Sipariş teslim alındı: {number}",
        body="{supplier_name} {receipt_number}",
    ),
    CancelTasksRule(
        code="purchase_order_cancelled",
        event=ev.PURCHASE_ORDER_CANCELLED,
        title="Satın alma siparişi iptal edildi: {number}",
        body="Siparişe bağlı açık görevler iptal edildi.",
    ),
    # Raporlama (Faz 4, Adım 4.3): arka planda hazırlanan rapor yalnızca isteyene bildirilir.
    NotifyRule(
        code="report_ready",
        event=ev.REPORT_JOB_DONE,
        roles=(),
        title="Rapor hazır: {title}",
        body="{row_count} satır. Dosyayı Raporlar > İndirmeler sayfasından indirebilirsiniz.",
        users=_report_requester,
    ),
    NotifyRule(
        code="report_failed",
        event=ev.REPORT_JOB_FAILED,
        roles=(),
        title="Rapor hazırlanamadı: {title}",
        body="{error}",
        level="WARNING",
        users=_report_requester,
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
