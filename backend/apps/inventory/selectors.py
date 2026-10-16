"""Stok okuma sorguları: bakiyeler, FEFO'ya göre kullanılabilir lotlar, lot soy ağacı (geri/ileri
izleme), SKT'si yaklaşan lotlar, minimum stok altındaki malzemeler."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from django.db import connection
from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.inventory.models import Lot, LotLink, StockBalance, StockReservation
from apps.masterdata.models import Location, Material

ZERO = Value(Decimal(0), output_field=DecimalField(max_digits=18, decimal_places=4))
# Ağaç görünümünde en fazla derinlik (döngü zaten atlanır; çok derin zincirde yanıtı sınırlar).
MAX_TRACE_DEPTH = 25
# Minimum stok kontrolünde sayılmayan lotlar: kullanılamayacak stok.
UNUSABLE_STATUSES = (Lot.Status.REJECTED, Lot.Status.BLOCKED)


def _reserved_subquery() -> Coalesce:
    reserved = (
        StockReservation.objects.filter(
            lot=OuterRef("lot"),
            location=OuterRef("location"),
            status=StockReservation.Status.ACTIVE,
        )
        .values("lot")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return Coalesce(Subquery(reserved), ZERO)


def balances() -> QuerySet[StockBalance]:
    """Sıfırdan büyük bakiyeler (malzeme, lot, lokasyon ilişkileriyle).

    Açıklamalar: `reserved_quantity` (aktif rezervasyonlar) ve `available_quantity`
    (bakiye − rezerve), temel birimde."""
    return (
        StockBalance.objects.filter(quantity__gt=0)
        .select_related("material__base_unit", "lot", "location__warehouse")
        .annotate(reserved_quantity=_reserved_subquery())
        .annotate(available_quantity=F("quantity") - F("reserved_quantity"))
    )


def stock_by_material(material: Material) -> QuerySet[StockBalance]:
    """Malzemenin lot ve lokasyon bazında bakiyeleri."""
    return balances().filter(material=material).order_by("lot__expiry_date", "lot__lot_no")


def stock_by_location(location: Location) -> QuerySet[StockBalance]:
    """Lokasyondaki malzeme ve lot bakiyeleri."""
    return balances().filter(location=location).order_by("material__code", "lot__lot_no")


def available_lots(
    material: Material, fefo: bool = True, *, today: date | None = None
) -> QuerySet[StockBalance]:
    """Kullanılabilir stok: yalnızca serbest (RELEASED), SKT'si geçmemiş lotların rezerve
    edilmemiş miktarı pozitif bakiyeleri (`available_quantity` = bakiye − aktif rezervasyonlar).
    `fefo=True`: SKT'si en yakın önce (SKT'siz en sonda), sonra en eski lot."""
    today = today or timezone.localdate()
    queryset = (
        balances()
        .filter(material=material, lot__status=Lot.Status.RELEASED)
        .filter(Q(lot__expiry_date__isnull=True) | Q(lot__expiry_date__gte=today))
        .filter(available_quantity__gt=0)  # type: ignore[misc]
    )
    if fefo:
        return queryset.order_by(
            F("lot__expiry_date").asc(nulls_last=True),
            "lot__created_at",
            "lot__id",
            "location__code",
        )
    return queryset.order_by("lot__lot_no", "location__code")


def lots_with_stock() -> QuerySet[Lot]:
    """Lotlar, toplam stok (`total_quantity`) açıklamasıyla."""
    total = (
        StockBalance.objects.filter(lot=OuterRef("pk"))
        .values("lot")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return Lot.objects.select_related("material__base_unit", "supplier").annotate(
        total_quantity=Coalesce(Subquery(total), ZERO)
    )


# --- soy ağacı -------------------------------------------------------------------------------

# UNION (ALL değil): aynı bağ ikinci kez işlenmez; ortak girdili ağaçlarda patlama ve döngü olmaz.
_TRACE_SQL = """
WITH RECURSIVE trace(link_id, node) AS (
    SELECT l.id, l.{next}
    FROM inventory_lotlink l
    WHERE l.{start} = %(lot_id)s
  UNION
    SELECT l.id, l.{next}
    FROM trace t
    JOIN inventory_lotlink l ON l.{start} = t.node
)
SELECT link_id FROM trace
"""


def _reachable_link_ids(lot_id: int, direction: Literal["backward", "forward"]) -> list[int]:
    # Geri izleme: çıktı lottan girdilere (child → parent); ileri izleme: girdiden çıktılara.
    start, nxt = ("child_lot_id", "parent_lot_id")
    if direction == "forward":
        start, nxt = nxt, start
    sql = _TRACE_SQL.format(start=start, next=nxt)
    with connection.cursor() as cursor:
        cursor.execute(sql, {"lot_id": lot_id})
        return [row[0] for row in cursor.fetchall()]


def _lot_node(lot: Lot) -> dict[str, Any]:
    material = lot.material
    return {
        "id": lot.pk,
        "lot_no": lot.lot_no,
        "status": lot.status,
        "status_display": lot.get_status_display(),
        "lot_source": lot.source,
        "lot_source_display": lot.get_source_display(),
        "material_id": material.pk,
        "material_code": material.code,
        "material_name": material.name,
        "material_type": material.material_type,
        "unit": material.base_unit.code,
        "expiry_date": lot.expiry_date,
    }


def lot_trace(lot: Lot, direction: Literal["backward", "forward"]) -> dict[str, Any]:
    """Lotun soy ağacı (özyinelemeli CTE ile tek sorguda bulunan bağlar).

    - `backward`: lotun üretiminde kullanılan girdi lotlar ve onların girdileri (geri izleme).
    - `forward`: lotun kullanıldığı çıktı lotlar ve onların çıktıları (ileri izleme).

    Dönüş: `{**lot, "quantity": None, "children": [{**lot, "quantity", "children": [...]}, ...]}`.
    `quantity`, girdi lottan kullanılan miktardır (temel birimde); aynı girdi-çıktı çifti için
    birden çok bağ (ör. iki aşamada eklenen su) toplanır.
    """
    if direction not in ("backward", "forward"):
        raise ValueError("direction backward ya da forward olmalıdır.")
    link_ids = _reachable_link_ids(lot.pk, direction)
    links = LotLink.objects.filter(pk__in=link_ids).select_related(
        "parent_lot__material__base_unit", "child_lot__material__base_unit"
    )
    edges: dict[int, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    lots: dict[int, Lot] = {}
    for link in links:
        if direction == "backward":
            source_lot, target_lot = link.child_lot, link.parent_lot
        else:
            source_lot, target_lot = link.parent_lot, link.child_lot
        lots[source_lot.pk] = source_lot
        lots[target_lot.pk] = target_lot
        edges[source_lot.pk][target_lot.pk] += link.quantity

    def build(lot_id: int, quantity: Decimal | None, seen: frozenset[int]) -> dict[str, Any]:
        node = {**_lot_node(lots.get(lot_id, lot)), "quantity": quantity, "children": []}
        if len(seen) >= MAX_TRACE_DEPTH:
            return node
        for target_id, used in sorted(edges.get(lot_id, {}).items()):
            if target_id in seen:
                continue
            node["children"].append(build(target_id, used, seen | {target_id}))
        node["children"].sort(key=lambda child: (child["material_code"], child["lot_no"]))
        return node

    lot = Lot.objects.select_related("material__base_unit").get(pk=lot.pk)
    lots[lot.pk] = lot
    return build(lot.pk, None, frozenset({lot.pk}))


def lot_trace_backward(lot: Lot) -> dict[str, Any]:
    """Geri izleme: bu lotu oluşturan girdi lotlar ağacı."""
    return lot_trace(lot, "backward")


def lot_trace_forward(lot: Lot) -> dict[str, Any]:
    """İleri izleme: bu lotun kullanıldığı çıktı lotlar ağacı."""
    return lot_trace(lot, "forward")


# --- günlük kontroller -----------------------------------------------------------------------


def expiring_lots(days: int, *, today: date | None = None) -> QuerySet[Lot]:
    """Stokta olan (reddedilmemiş) ve SKT'si `days` gün içinde dolacak ya da dolmuş lotlar,
    SKT'ye göre sıralı."""
    today = today or timezone.localdate()
    return (
        lots_with_stock()
        .filter(total_quantity__gt=0, expiry_date__isnull=False)  # type: ignore[misc]
        .filter(expiry_date__lte=today + timedelta(days=days))
        .exclude(status=Lot.Status.REJECTED)
        .order_by("expiry_date", "lot_no")
    )


def below_min_stock() -> QuerySet[Material]:
    """Minimum stoku tanımlı aktif malzemelerden toplam stoku minimumun altında olanlar.

    Toplam stoka reddedilmiş ve bloke lotlar sayılmaz; karantinadaki (gelen) stok sayılır.
    Açıklama: `stock_quantity` (temel birimde).
    """
    stock = (
        StockBalance.objects.filter(material=OuterRef("pk"))
        .exclude(lot__status__in=UNUSABLE_STATUSES)
        .values("material")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return (
        Material.objects.filter(is_active=True, min_stock__isnull=False)
        .select_related("base_unit")
        .annotate(stock_quantity=Coalesce(Subquery(stock), ZERO))
        .filter(stock_quantity__lt=F("min_stock"))
        .order_by("code")
    )
