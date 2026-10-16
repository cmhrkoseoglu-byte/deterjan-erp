"""İzlenebilirlik ve geri çağırma sorguları (Faz 3, Adım 3.4).

`inventory.selectors.lot_trace` soy ağacının üzerine kurulur ve stok defterinden okur:

- **Geri izleme** (`backward_trace`): mamul lot → dolum → bulk lot → hammadde lotları; hammadde
  lotlarında tedarikçi, tedarikçi lot no ve mal kabul belgesi.
- **İleri izleme** (`forward_trace`): hammadde lotu → şarjlar → bulk lotlar → dolum lotları; her
  lotta stoktaki, sevk edilen ve iade gelen miktar, sevk edilen lotlarda sevkiyat satırları.
- **Geri çağırma simülasyonu** (`recall_simulation`): seçilen lotlar ve ileri soyları; stokta
  kalan miktar lokasyon bazında, sevk edilen miktar sevkiyat ve müşteri bazında.

Müşteri halkası: sevkiyat `SHIPMENT` hareketiyle stoktan çıkar; hareket belge numarasını
(`SV-...`) ve kaynak belgeyi taşır. Sevkiyat satırları `shipment_rows` ile bu hareketlerden
okunur; müşteri alanları hareketin kaynağı olan sevkiyattan (`sales.Shipment` → sipariş →
müşteri) tek sorguyla doldurulur (`_customers_for`).

Tüm miktarlar lotun malzemesinin temel birimindedir. Sorgu sayısı lot sayısından bağımsızdır
(özyinelemeli CTE + toplu sorgular).
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from django.db import connection
from django.db.models import Min, Sum

from apps.inventory.models import GoodsReceiptLine, Lot, StockBalance, StockMovement
from apps.inventory.selectors import lot_trace_backward, lot_trace_forward
from apps.sales.models import Shipment

MovementType = StockMovement.Type
ZERO = Decimal(0)
# Simülasyonda lotların sıralaması: zincirin başından sonuna.
TYPE_ORDER = {"RAW": 0, "PACKAGING": 1, "BULK": 2, "FINISHED": 3}

_FORWARD_CLOSURE_SQL = """
WITH RECURSIVE closure(node) AS (
    SELECT unnest(%(lot_ids)s::bigint[])
  UNION
    SELECT l.child_lot_id
    FROM closure c
    JOIN inventory_lotlink l ON l.parent_lot_id = c.node
)
SELECT node FROM closure
"""


def forward_closure(lot_ids: Iterable[int]) -> set[int]:
    """Lotlar ve ileri soylarındaki tüm lotların kimlikleri (tek sorgu; UNION döngüyü keser)."""
    ids = sorted(set(lot_ids))
    if not ids:
        return set()
    with connection.cursor() as cursor:
        cursor.execute(_FORWARD_CLOSURE_SQL, {"lot_ids": ids})
        return {row[0] for row in cursor.fetchall()}


def _walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in node["children"]:
        yield from _walk(child)


# --- miktarlar -------------------------------------------------------------------------------


def on_hand_by_lot(lot_ids: Iterable[int]) -> dict[int, Decimal]:
    """Lot bazında stoktaki toplam miktar."""
    rows = (
        StockBalance.objects.filter(lot_id__in=list(lot_ids), quantity__gt=0)
        .values("lot_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["lot_id"]: row["total"] for row in rows}


_SHIPMENT_KEYS = (
    "lot_id",
    "document_number",
    "source_content_type__app_label",
    "source_content_type__model",
    "source_object_id",
)


def _shipment_groups(lot_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Lot + sevkiyat belgesi başına net sevk (sevkiyat hareketleri ve onların ters kayıtları).

    Ters kayıtlar ayrı ve küçük sorgularla eşlenir (kendine birleştirme yok): büyük hareket
    defterinde sorgu planı tablo istatistiklerine bağlı kalmasın."""
    ids = list(lot_ids)
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    shipments = (
        StockMovement.objects.filter(movement_type=MovementType.SHIPMENT, lot_id__in=ids)
        .values(*_SHIPMENT_KEYS)
        .annotate(total=Sum("quantity"), first_at=Min("created_at"))
    )
    for row in shipments:
        groups[tuple(row[key] for key in _SHIPMENT_KEYS)] = row
    reversals = list(
        StockMovement.objects.filter(movement_type=MovementType.REVERSAL, lot_id__in=ids).values(
            *_SHIPMENT_KEYS, "quantity", "reversal_of_id"
        )
    )
    if reversals:
        reversed_shipments = set(
            StockMovement.objects.filter(
                pk__in=[row["reversal_of_id"] for row in reversals],
                movement_type=MovementType.SHIPMENT,
            ).values_list("pk", flat=True)
        )
        for row in reversals:
            group = groups.get(tuple(row[key] for key in _SHIPMENT_KEYS))
            if row["reversal_of_id"] in reversed_shipments and group is not None:
                group["total"] += row["quantity"]
    return [row for row in groups.values() if row["total"]]


def shipped_by_lot(lot_ids: Iterable[int]) -> dict[int, Decimal]:
    """Lot bazında net sevk edilen miktar (ters kayıtlar düşülür), pozitif."""
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for row in _shipment_groups(lot_ids):
        totals[row["lot_id"]] -= row["total"]
    return dict(totals)


def returned_by_lot(lot_ids: Iterable[int]) -> dict[int, Decimal]:
    """Lot bazında müşteriden iade gelen miktar."""
    rows = (
        StockMovement.objects.filter(movement_type=MovementType.RETURN, lot_id__in=list(lot_ids))
        .values("lot_id")
        .annotate(total=Sum("quantity"))
    )
    return {row["lot_id"]: row["total"] for row in rows}


SHIPMENT_MODEL = "sales.shipment"


def _customers_for(rows: list[dict[str, Any]]) -> None:
    """Sevkiyat satırlarına müşteri alanlarını (`customer_id`, `customer_code`,
    `customer_name`) ve sipariş numarasını (`order_number`) yazar: hareketin kaynağı sevkiyat
    belgesidir (`source_model` = `sales.shipment`). Kaynağı sevkiyat olmayan satırda boş kalır."""
    ids = {row["source_id"] for row in rows if row["source_model"] == SHIPMENT_MODEL}
    shipments = {
        row["id"]: row
        for row in Shipment.objects.filter(pk__in=ids).values(
            "id",
            "sales_order__number",
            "sales_order__customer_id",
            "sales_order__customer__code",
            "sales_order__customer__name",
        )
    }
    for row in rows:
        shipment = (
            shipments.get(row["source_id"]) if row["source_model"] == SHIPMENT_MODEL else None
        )
        row["customer_id"] = shipment["sales_order__customer_id"] if shipment else None
        row["customer_code"] = shipment["sales_order__customer__code"] if shipment else None
        row["customer_name"] = shipment["sales_order__customer__name"] if shipment else None
        row["order_number"] = shipment["sales_order__number"] if shipment else None


def shipment_rows(lot_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Lotların sevkiyat satırları: lot + sevkiyat belgesi başına net miktar, ilk sevk zamanı ve
    müşteri. Tamamı ters kayıtla geri alınan sevkiyat listelenmez."""
    rows = sorted(
        _shipment_groups(lot_ids),
        key=lambda row: (row["first_at"], row["document_number"], row["lot_id"]),
    )
    result = []
    for row in rows:
        app_label = row["source_content_type__app_label"]
        result.append(
            {
                "lot_id": row["lot_id"],
                "document_number": row["document_number"],
                "source_model": f"{app_label}.{row['source_content_type__model']}"
                if app_label
                else None,
                "source_id": row["source_object_id"],
                "shipped_at": row["first_at"],
                "quantity": -row["total"],
            }
        )
    _customers_for(result)
    return result


# --- geri ve ileri izleme --------------------------------------------------------------------


def backward_trace(lot: Lot) -> dict[str, Any]:
    """Geri izleme ağacı; satın alma lotlarında tedarikçi, tedarikçi lot no ve mal kabul."""
    tree = lot_trace_backward(lot)
    nodes = list(_walk(tree))
    ids = {node["id"] for node in nodes}
    lots = {
        row.pk: row
        for row in Lot.objects.filter(pk__in=ids)
        .select_related("supplier")
        .only("id", "supplier_lot_no", "supplier__code", "supplier__name", "manufactured_at")
    }
    receipts = {
        line.created_lot_id: line
        for line in GoodsReceiptLine.objects.filter(created_lot_id__in=ids).select_related(
            "receipt"
        )
    }
    for node in nodes:
        row = lots[node["id"]]
        supplier = row.supplier
        line = receipts.get(node["id"])
        node.update(
            {
                "manufactured_at": row.manufactured_at,
                "supplier_id": supplier.pk if supplier else None,
                "supplier_code": supplier.code if supplier else None,
                "supplier_name": supplier.name if supplier else None,
                "supplier_lot_no": row.supplier_lot_no,
                "receipt_id": line.receipt_id if line else None,
                "receipt_number": line.receipt.number if line else None,
                "receipt_date": line.receipt.receipt_date if line else None,
            }
        )
    return tree


def forward_trace(lot: Lot) -> dict[str, Any]:
    """İleri izleme ağacı; her lotta `on_hand`, `shipped`, `returned` ve `shipments`."""
    tree = lot_trace_forward(lot)
    nodes = list(_walk(tree))
    ids = {node["id"] for node in nodes}
    on_hand = on_hand_by_lot(ids)
    shipped = shipped_by_lot(ids)
    returned = returned_by_lot(ids)
    shipments: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in shipment_rows(ids):
        shipments[row["lot_id"]].append(row)
    for node in nodes:
        lot_id = node["id"]
        node.update(
            {
                "on_hand": on_hand.get(lot_id, ZERO),
                "shipped": shipped.get(lot_id, ZERO),
                "returned": returned.get(lot_id, ZERO),
                "shipments": shipments.get(lot_id, []),
            }
        )
    return tree


# --- geri çağırma simülasyonu ----------------------------------------------------------------


def _lot_row(lot: Lot) -> dict[str, Any]:
    material = lot.material
    return {
        "id": lot.pk,
        "lot_no": lot.lot_no,
        "status": lot.status,
        "status_display": lot.get_status_display(),
        "material_id": material.pk,
        "material_code": material.code,
        "material_name": material.name,
        "material_type": material.material_type,
        "unit": material.base_unit.code,
        "expiry_date": lot.expiry_date,
    }


def recall_simulation(lots: Sequence[Lot]) -> dict[str, Any]:
    """Seçilen lotlar için geri çağırma simülasyonu.

    Etkilenen lotlar: seçilenler ve ileri soyları (kullanıldıkları şarj ve dolum lotları).
    Dönüş: `selected` (lot kimlikleri), `lots` (etkilenen lotlar; stokta / sevk / iade
    miktarlarıyla), `stock` (lokasyon bazında stokta kalan), `shipments` (sevkiyat satırları),
    `customers` (müşteri + ürün bazında sevk edilen), `summary` (sayılar).
    """
    selected = sorted({lot.pk for lot in lots})
    ids = forward_closure(selected)
    lot_rows = {
        lot.pk: _lot_row(lot)
        for lot in Lot.objects.filter(pk__in=ids).select_related("material__base_unit")
    }
    shipped = shipped_by_lot(ids)
    returned = returned_by_lot(ids)

    stock = []
    on_hand: dict[int, Decimal] = defaultdict(Decimal)
    balances = (
        StockBalance.objects.filter(lot_id__in=ids, quantity__gt=0)
        .select_related("location__warehouse")
        .order_by("lot_id", "location__code")
    )
    for balance in balances:
        location = balance.location
        on_hand[balance.lot_id] += balance.quantity
        stock.append(
            {
                **_pick_lot(lot_rows[balance.lot_id]),
                "location_id": location.pk,
                "location_code": location.code,
                "location_name": location.name,
                "location_type": location.location_type,
                "warehouse_code": location.warehouse.code,
                "quantity": balance.quantity,
            }
        )

    shipments = [{**_pick_lot(lot_rows[row["lot_id"]]), **row} for row in shipment_rows(ids)]
    customers: dict[tuple[Any, int], dict[str, Any]] = {}
    for row in shipments:
        key = (row["customer_id"], row["material_id"])
        entry = customers.setdefault(
            key,
            {
                "customer_id": row["customer_id"],
                "customer_code": row["customer_code"],
                "customer_name": row["customer_name"],
                "material_id": row["material_id"],
                "material_code": row["material_code"],
                "material_name": row["material_name"],
                "unit": row["unit"],
                "quantity": ZERO,
                "lots": [],
                "documents": [],
            },
        )
        entry["quantity"] += row["quantity"]
        if row["lot_no"] not in entry["lots"]:
            entry["lots"].append(row["lot_no"])
        if row["document_number"] and row["document_number"] not in entry["documents"]:
            entry["documents"].append(row["document_number"])

    affected = []
    for lot_id, row in lot_rows.items():
        affected.append(
            {
                **row,
                "is_selected": lot_id in selected,
                "on_hand": on_hand.get(lot_id, ZERO),
                "shipped": shipped.get(lot_id, ZERO),
                "returned": returned.get(lot_id, ZERO),
            }
        )
    affected.sort(key=lambda r: (TYPE_ORDER.get(r["material_type"], 9), r["lot_no"]))
    customer_rows = sorted(
        customers.values(),
        key=lambda r: (r["customer_name"] or "", r["material_code"]),
    )
    known_customers = {r["customer_id"] for r in customer_rows if r["customer_id"] is not None}
    return {
        "selected": selected,
        "lots": affected,
        "stock": stock,
        "shipments": shipments,
        "customers": customer_rows,
        "summary": {
            "lot_count": len(affected),
            "finished_lot_count": sum(1 for r in affected if r["material_type"] == "FINISHED"),
            "lots_in_stock": sum(1 for r in affected if r["on_hand"] > 0),
            "shipped_lot_count": sum(1 for r in affected if r["shipped"] > 0),
            "shipment_count": len({r["document_number"] for r in shipments}),
            "customer_count": len(known_customers),
        },
    }


def _pick_lot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "lot_id": row["id"],
        "lot_no": row["lot_no"],
        "lot_status": row["status"],
        "material_id": row["material_id"],
        "material_code": row["material_code"],
        "material_name": row["material_name"],
        "material_type": row["material_type"],
        "unit": row["unit"],
    }
