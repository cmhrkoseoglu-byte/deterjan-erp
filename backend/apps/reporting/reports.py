"""Rapor tanımları (Faz 4, Adım 4.3): sütunlar, filtreler, roller.

Ekran, Excel ve PDF aynı tanımı kullanır: API sütunları ve satırları buradan alır, dosya
çıktısı aynı sütunları yazar. Tutar sütunları (`sensitive`) yetkisi olmayan kullanıcıda hem
sütun listesinden hem satırlardan çıkarılır:

- `cost`: lot maliyeti ve stok değeri — yalnızca yonetim ve admin (Karar D-15).
- `price`: alış fiyatı — satin_alma, yonetim ve admin (depo hiçbir zaman görmez).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from apps.core.models import User
from apps.core.permissions import user_has_role
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
from apps.reporting import selectors
from apps.reporting.selectors import Rows

ColumnKind = Literal[
    "text", "number", "money", "percent", "duration", "date", "datetime", "boolean"
]
Sensitive = Literal["cost", "price"]

SENSITIVE_ROLES: dict[str, tuple[str, ...]] = {
    "cost": (YONETIM,),
    "price": (SATIN_ALMA, YONETIM),
}


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: ColumnKind = "text"
    sensitive: Sensitive | None = None
    # Excel sütun genişliği (karakter); PDF'de oransal kullanılır.
    width: int = 14


@dataclass(frozen=True)
class ReportDefinition:
    code: str
    title: str
    description: str
    roles: tuple[str, ...]
    columns: tuple[Column, ...]
    rows: Callable[[dict[str, Any]], Rows]
    # Kabul edilen filtre anahtarları (`api.serializers.ReportFilterSerializer` alanları).
    filters: tuple[str, ...] = ()
    summary: Callable[[Rows], list[tuple[str, Any, str]]] | None = None
    summary_labels: dict[str, str] = field(default_factory=dict)
    # Tarih filtresi boşsa varsayılan: son N gün (None: tarih filtresi yok).
    default_days: int | None = 30
    # Uzun raporlar PDF'de yatay sayfa kullanır.
    landscape: bool = True


def can_see(user: User, sensitive: str | None) -> bool:
    if sensitive is None:
        return True
    return user_has_role(user, SENSITIVE_ROLES[sensitive])


def visible_columns(definition: ReportDefinition, user: User) -> list[Column]:
    return [c for c in definition.columns if can_see(user, c.sensitive)]


def visible_summary(
    definition: ReportDefinition, user: User, summary: list[tuple[str, Any, str]]
) -> list[dict[str, Any]]:
    """Özet satırları; tutar türündekiler (`money`) maliyet yetkisi ister."""
    return [
        {"key": key, "label": definition.summary_labels.get(key, key), "value": value, "kind": kind}
        for key, value, kind in summary
        if kind != "money" or can_see(user, "cost")
    ]


def can_view(definition: ReportDefinition, user: User) -> bool:
    return user_has_role(user, definition.roles)


STOCK_ROLES = (DEPO, PLANLAMA, YONETIM, SATIN_ALMA)

REPORTS: dict[str, ReportDefinition] = {
    d.code: d
    for d in (
        ReportDefinition(
            code="stock-status",
            title="Stok durumu",
            description="Lot ve lokasyon bazında bakiye, rezerve ve kullanılabilir miktar.",
            roles=STOCK_ROLES,
            default_days=None,
            filters=(
                "material",
                "material_type",
                "warehouse",
                "location",
                "lot_status",
                "expiring_days",
            ),
            columns=(
                Column("material", "Malzeme", width=32),
                Column("material_type", "Tür", width=12),
                Column("lot_no", "Lot no", width=16),
                Column("lot_status", "Lot durumu", width=12),
                Column("expiry_date", "SKT", "date", width=11),
                Column("warehouse", "Depo", width=16),
                Column("location", "Lokasyon", width=14),
                Column("quantity", "Miktar", "number"),
                Column("reserved", "Rezerve", "number"),
                Column("available", "Kullanılabilir", "number"),
                Column("unit", "Birim", width=8),
                Column("unit_cost", "Birim maliyet (TL)", "number", sensitive="cost"),
                Column("value", "Stok değeri (TL)", "money", sensitive="cost"),
                Column("cost_is_estimated", "Tahmini", "boolean", sensitive="cost", width=9),
            ),
            rows=selectors.stock_status,
            summary=selectors.stock_status_summary,
            summary_labels={
                "row_count": "Satır",
                "lot_count": "Lot",
                "stock_value": "Toplam stok değeri (TL)",
            },
        ),
        ReportDefinition(
            code="stock-movements",
            title="Stok hareketleri",
            description="Hareket defteri: giriş, çıkış, transfer, sayım, fire ve sevkiyat.",
            roles=STOCK_ROLES,
            filters=(
                "date_from",
                "date_to",
                "material",
                "material_type",
                "warehouse",
                "location",
                "movement_type",
                "lot_no",
            ),
            columns=(
                Column("created_at", "Zaman", "datetime", width=16),
                Column("movement_type", "Hareket", width=16),
                Column("document_number", "Belge no", width=16),
                Column("material", "Malzeme", width=32),
                Column("lot_no", "Lot no", width=16),
                Column("warehouse", "Depo", width=16),
                Column("location", "Lokasyon", width=14),
                Column("quantity", "Miktar", "number"),
                Column("unit", "Birim", width=8),
                Column("user", "Kullanıcı", width=16),
                Column("note", "Not", width=28),
            ),
            rows=selectors.stock_movements,
            summary=selectors.stock_movements_summary,
            summary_labels={
                "row_count": "Hareket",
                "inbound": "Giriş toplamı",
                "outbound": "Çıkış toplamı",
            },
        ),
        ReportDefinition(
            code="production",
            title="Üretim raporu",
            description="Biten şarjlar: plan ve gerçek çıktı, verim, tolerans dışı tartımlar.",
            roles=(URETIM, PLANLAMA, YONETIM),
            filters=("date_from", "date_to", "material", "equipment"),
            columns=(
                Column("batch_no", "Şarj no", width=16),
                Column("order_number", "Emir no", width=16),
                Column("product", "Ürün", width=30),
                Column("equipment", "Tank", width=10),
                Column("started_at", "Başlama", "datetime", width=16),
                Column("finished_at", "Bitiş", "datetime", width=16),
                Column("duration_hours", "Süre (saat)", "duration", width=10),
                Column("planned_quantity", "Plan", "number"),
                Column("actual_quantity", "Gerçek", "number"),
                Column("unit", "Birim", width=8),
                Column("yield_pct", "Verim (%)", "percent", width=10),
                Column("weighing_count", "Tartım", "number", width=8),
                Column("deviation_count", "Sapma", "number", width=8),
                Column("max_deviation_pct", "En büyük sapma (%)", "percent", width=12),
                Column("deviation_notes", "Sapma notları", width=30),
                Column("lot_status", "Lot durumu", width=12),
            ),
            rows=selectors.production,
            summary=selectors.production_summary,
            summary_labels={
                "batch_count": "Şarj",
                "avg_yield": "Ortalama verim (%)",
                "batches_with_deviation": "Sapmalı şarj",
            },
        ),
        ReportDefinition(
            code="filling",
            title="Dolum raporu",
            description="Biten dolum partileri: teorik ve gerçek bulk tüketimi, sağlam adet, fire.",
            roles=(DOLUM, PLANLAMA, YONETIM),
            filters=("date_from", "date_to", "material", "equipment"),
            columns=(
                Column("lot_no", "Mamul lot", width=16),
                Column("order_number", "Emir no", width=16),
                Column("product", "Ürün", width=30),
                Column("line", "Hat", width=10),
                Column("finished_at", "Bitiş", "datetime", width=16),
                Column("good_units", "Sağlam adet", "number"),
                Column("scrap_units", "Fire adet", "number"),
                Column("scrap_rate", "Fire oranı (%)", "percent", width=10),
                Column("theoretical_bulk", "Teorik bulk", "number"),
                Column("actual_bulk", "Gerçek bulk", "number"),
                Column("bulk_unit", "Birim", width=8),
                Column("bulk_variance_pct", "Bulk farkı (%)", "percent", width=10),
            ),
            rows=selectors.filling,
            summary=selectors.filling_summary,
            summary_labels={
                "run_count": "Parti",
                "good_units": "Sağlam adet",
                "scrap_rate": "Fire oranı (%)",
                "avg_bulk_variance": "Ortalama bulk farkı (%)",
            },
        ),
        ReportDefinition(
            code="quality",
            title="QC raporu",
            description="Karar verilen numuneler: bekleme süresi, red oranı, spesifikasyon dışı "
            "sonuçlar.",
            roles=(LABORATUVAR, PLANLAMA, YONETIM),
            filters=("date_from", "date_to", "material", "stage", "decision"),
            columns=(
                Column("number", "Numune no", width=16),
                Column("stage", "Aşama", width=12),
                Column("lot_no", "Lot no", width=16),
                Column("material", "Malzeme", width=30),
                Column("created_at", "Açılış", "datetime", width=16),
                Column("decided_at", "Karar", "datetime", width=16),
                Column("wait_hours", "Bekleme (saat)", "duration", width=10),
                Column("decision", "Karar", width=14),
                Column("out_of_spec_count", "Spec dışı", "number", width=9),
                Column("out_of_spec_tests", "Spec dışı testler", width=30),
            ),
            rows=selectors.quality,
            summary=selectors.quality_summary,
            summary_labels={
                "sample_count": "Numune",
                "rejected_count": "Red",
                "rejection_rate": "Red oranı (%)",
                "out_of_spec_samples": "Spec dışı sonuçlu numune",
                "avg_wait_hours": "Ortalama bekleme (saat)",
            },
        ),
        ReportDefinition(
            code="shipments",
            title="Sevkiyat raporu",
            description="Sevk edilen satırlar: müşteri, ürün, lotlar, istenen tarihe göre "
            "zamanında mı.",
            roles=(SEVKIYAT, PLANLAMA, YONETIM),
            filters=("date_from", "date_to", "customer", "material"),
            columns=(
                Column("number", "Sevkiyat no", width=16),
                Column("dispatched_at", "Sevk zamanı", "datetime", width=16),
                Column("customer", "Müşteri", width=28),
                Column("order_number", "Sipariş no", width=16),
                Column("product", "Ürün", width=28),
                Column("planned_quantity", "Planlanan", "number"),
                Column("shipped_quantity", "Sevk edilen", "number"),
                Column("unit", "Birim", width=8),
                Column("lots", "Lotlar", width=24),
                Column("vehicle_plate", "Plaka", width=10),
                Column("requested_date", "İstenen tarih", "date", width=11),
                Column("on_time", "Zamanında", "boolean", width=9),
            ),
            rows=selectors.shipments,
            summary=selectors.shipments_summary,
            summary_labels={
                "shipment_count": "Sevkiyat",
                "customer_count": "Müşteri",
                "on_time_rate": "Zamanında sevk (%)",
            },
        ),
        ReportDefinition(
            code="task-durations",
            title="Görev süreleri",
            description="Hangi adım ne kadar bekliyor: görev türü ve birim bazında üstlenme ve "
            "kapanma süreleri, açık ve gecikmiş görevler.",
            roles=(PLANLAMA, YONETIM),
            filters=("date_from", "date_to", "role"),
            landscape=True,
            columns=(
                Column("task_kind", "Görev türü", width=30),
                Column("role", "Birim", width=14),
                Column("total", "Toplam", "number", width=8),
                Column("done", "Tamamlanan", "number", width=10),
                Column("open", "Açık", "number", width=8),
                Column("overdue", "Gecikmiş", "number", width=9),
                Column("avg_claim_hours", "Ort. üstlenme (saat)", "duration", width=12),
                Column("avg_close_hours", "Ort. kapanma (saat)", "duration", width=12),
                Column("max_close_hours", "En uzun kapanma (saat)", "duration", width=12),
                Column("oldest_open_hours", "En eski açık (saat)", "duration", width=12),
            ),
            rows=selectors.task_durations,
            summary=selectors.task_durations_summary,
            summary_labels={
                "task_count": "Görev",
                "open_count": "Açık",
                "overdue_count": "Gecikmiş",
                "bottleneck": "Darboğaz (en uzun ortalama kapanma)",
            },
        ),
    )
}


def get_report(code: str) -> ReportDefinition | None:
    return REPORTS.get(code)


def reports_for(user: User) -> list[ReportDefinition]:
    return [d for d in REPORTS.values() if can_view(d, user)]
