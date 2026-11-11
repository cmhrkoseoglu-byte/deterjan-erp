"""Fiyat ve maliyet görünürlüğü sondası (plan §5.5, 2. parça).

Bugün fiyat ve maliyet kararları işlevlerin içinde verilir: serializer'lar fiyat alanlarını
çıkarır (`RECEIPT_PRICE_ROLES`, `PriceHidingMixin`), kayıt geçmişi gizli alanları süzer
(`hidden_fields`), raporlar ve pano maliyeti düşürür (`SENSITIVE_ROLES`, `can_see`). Sonda bu
kararları 14 personayla, olabilen her yerde API'den gözleyerek dondurur:

- mal kabul: liste, ayrıntı ve geçmişteki fiyatlar; fiyatı göremeyenin yazdığı fiyat;
- satın alma siparişi: liste, ayrıntı, geçmiş, PDF, onay görevinin açıklaması, beklenen
  teslimatlar ve siparişten açılan mal kabule geçen fiyat;
- lot: liste, ayrıntı ve geçmişteki maliyet; maliyet modülündeki lot maliyeti;
- satış siparişi: fiyatları gören herkes;
- maliyet: personel maliyeti ve ondan açılan işçilik oranının notu;
- raporlar ve yönetim panosu: maliyet sütunları, özet, Excel ve stok değeri;
- kayıt türlerinin gizli alanları (kayıt defterinden, her persona için).

Değerler kimlik, zaman ve sıra taşımaz: yalnız tutar alanları yazılır (girilen fiyatlar olduğu
gibi, hesaplanan tutarlar "<n>"); notlardaki sayılar (tutar, kur, belge ve lot numarası) `#` olur.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from typing import Any, cast

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core import records
from apps.core.models import Currency, User
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
from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.personas import PERSONAS, make_personas, persona_client
from apps.core.tests.factories import UserFactory
from apps.costing import services as costing
from apps.costing.models import CostRate, CostStage
from apps.costing.tests.factories import build_chain
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceipt, GoodsReceiptExtraCost, GoodsReceiptLine, Lot
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata.models import Supplier
from apps.masterdata.tests.factories import CustomerFactory, SupplierFactory, unit
from apps.personnel import services as personnel
from apps.personnel.tests.factories import employee
from apps.production.models import ProductionBatch
from apps.production.tests.factories import Plant
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder
from apps.reporting.reports import REPORTS
from apps.sales import services as sales
from apps.sales.models import SalesOrder
from apps.sales.tests.factories import finished_product

pytestmark = pytest.mark.django_db

NAME = "probe_prices"
API = "/api/v1"
D = Decimal
Json = Any
Cases = dict[str, dict[str, Json]]
Commit = Callable[[], AbstractContextManager[Any]]

# Personel maliyeti ayı: geçmişte ve bordro onayı istemeyen (Ekim 2026 öncesi) bir ay.
COST_YEAR, COST_MONTH = 2026, 9
ORDER_DATE = date(2026, 10, 16)
EXPECTED_DATE = date(2026, 10, 20)
FREIGHT = GoodsReceiptExtraCost.Kind.FREIGHT
CUSTOMS = GoodsReceiptExtraCost.Kind.CUSTOMS
BY_QUANTITY = GoodsReceiptExtraCost.Allocation.QUANTITY
BY_VALUE = GoodsReceiptExtraCost.Allocation.VALUE

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
DECIMAL = re.compile(r"-?\d+(?:\.\d+)?")
MONEY_KEY = re.compile(r"price|cost|amount|total|rate|value|currency|limit")

# Bugün gizli alanı olan kayıt türleri (kayıt defterinden sayılır; bkz. `_registry_cases`).
HIDDEN_FIELD_TYPES = ["inventory.lot", "purchasing.purchaseorder"]
# Bugün raporlardaki hassas sütunlar: (rapor, sütun, hak).
SENSITIVE_COLUMNS = [
    ("stock-status", "cost_is_estimated", "cost"),
    ("stock-status", "unit_cost", "cost"),
    ("stock-status", "value", "cost"),
]


# --- değerleri sadeleştirme ------------------------------------------------------------------


def _is_money(key: str) -> bool:
    """Tutar alanı mı: fiyat, maliyet, tutar, toplam, kur, değer, para birimi ya da limit (miktar
    ve tarih alanları değil; ör. `total_quantity`, `cost_date`)."""
    return bool(MONEY_KEY.search(key)) and not key.endswith(("quantity", "_date", "_at"))


def _shape(value: Json) -> Json:
    """Hesaplanan tutarın yalnız varlığı (değeri hesaba bağlıdır, yetkiye değil): sayı "<n>"."""
    if isinstance(value, Mapping):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shape(item) for item in value]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float) or (isinstance(value, str) and DECIMAL.fullmatch(value)):
        return "<n>"
    return value


def _plain(value: Json, computed: bool) -> Json:
    if isinstance(value, Mapping):
        return _money(value, computed=computed)
    if isinstance(value, list):
        return [_plain(item, computed) for item in value]
    return _shape(value) if computed else value


def _money(data: Mapping[str, Json], *, computed: bool = False) -> dict[str, Json]:
    """Yanıttaki tutar alanları; iç içe sözlük ve listelerde de yalnız tutar alanları."""
    return {key: _plain(value, computed) for key, value in data.items() if _is_money(key)}


def _masked(text: str | None) -> str:
    """Nottaki sayılar (tutar, kur, belge ve lot numarası, yıl) `#` olur."""
    return NUMBER.sub("#", text or "")


def _entry(entry: Mapping[str, Json], *, computed: bool = False) -> dict[str, Json]:
    """Geçmiş kaydı: işlem, görünen tutarlar (silinen satır ve ek masrafın içi dahil) ve not."""
    money: dict[str, Json] = {}
    for key, value in (entry.get("changes") or {}).items():
        if _is_money(key):
            money[key] = _plain(value, computed)
        elif isinstance(value, list) and any(isinstance(item, Mapping) for item in value):
            money[key] = [_plain(item, computed) for item in value]
    return {"action": entry["action"], "money": money, "note": _masked(entry.get("note"))}


def _refused(response: Any) -> dict[str, Json] | None:
    """Yanıt 2xx değilse durumu (400'de iş kuralı kodu da); 2xx ise None."""
    if 200 <= response.status_code < 300:
        return None
    result: dict[str, Json] = {"status": response.status_code}
    if response.status_code == 400:
        body = response.json()
        if isinstance(body, dict) and "code" in body:
            result["code"] = body["code"]
    return result


def _results(response: Any) -> list[Json]:
    body = response.json()
    return list(body["results"]) if isinstance(body, dict) else list(body)


def _stored(line: GoodsReceiptLine) -> dict[str, Json]:
    """Mal kabul satırında veritabanına yazılan miktar ve fiyat."""
    line.refresh_from_db()
    return {
        "quantity": str(line.quantity),
        "unit_price": None if line.unit_price is None else str(line.unit_price),
        "currency": line.currency,
        "exchange_rate": None if line.exchange_rate is None else str(line.exchange_rate),
    }


# --- kurulum ---------------------------------------------------------------------------------


@dataclass
class Scene:
    staff: dict[str, User]
    plant: Plant
    receipt: GoodsReceipt  # fiyatlı, geçmişi dolu, kaydedilmiş mal kabul
    lot: Lot  # o mal kabulün lotu (maliyeti iki kez hesaplanmış)
    order: PurchaseOrder  # geçmişi dolu, onaylı sipariş
    receivable: PurchaseOrder  # siparişten mal kabul sondası için onaylı sipariş
    sales_order: SalesOrder
    labor_rate: CostRate  # personel maliyetinden açılan işçilik oranı
    write_supplier: Supplier  # yazma sondalarının mal kabulleri (okuma sondalarına karışmaz)


def _staff() -> dict[str, User]:
    """Kurulumu yapan kullanıcılar (personalardan ayrı)."""
    roles = (DEPO, URETIM, LABORATUVAR, PLANLAMA, YONETIM, DOLUM, SATIN_ALMA, SEVKIYAT)
    return {
        role: cast(User, UserFactory(username=f"sonda_fiyat_{role}", roles=[role]))
        for role in roles
    }


def _labor_rate(staff: dict[str, User], batch: ProductionBatch) -> CostRate:
    """Onaylı puantajlı aydan işçilik oranı açar (notuna personel maliyeti tutarı yazılır)."""
    manager = staff[YONETIM]
    # Şarj o ayda bitmiş sayılır: oranın tabanı o ay üretilen kg'dır.
    moment = timezone.make_aware(datetime.combine(date(COST_YEAR, COST_MONTH, 15), time(12)))
    ProductionBatch.objects.filter(pk=batch.pk).update(finished_at=moment)
    maker = employee(manager, full_name="Can Kaya", department="Üretim")
    personnel.add_wage(
        manager, {"employee": maker, "gross_monthly": D("45000"), "valid_from": date(2020, 1, 1)}
    )
    costing.set_department_cost_center(manager, "Üretim", CostStage.PRODUCTION)
    personnel.approve_attendance_month(manager, COST_YEAR, COST_MONTH)
    return costing.add_labor_rate_from_personnel_cost(
        manager, COST_YEAR, COST_MONTH, CostStage.PRODUCTION, date(COST_YEAR, COST_MONTH, 1)
    )


def _receipt(staff: dict[str, User], plant: Plant, commit: Commit) -> GoodsReceipt:
    """Mal kabul: taslakta fiyat ve ek masraf, satır ve ek masraf kaldırma, kayıt ve kayıttan
    sonra notlu fiyat düzeltmesi (lot maliyeti yeniden hesaplanır)."""
    depo, buyer = staff[DEPO], staff[SATIN_ALMA]
    kg = unit("KG")
    receipt = inventory.create_goods_receipt(
        depo,
        {
            "supplier": SupplierFactory.create(name="Sonda Kimya A.Ş."),
            "receipt_date": date.today(),
            "quarantine_location": plant.quarantine,
            "storage_location": plant.storage,
        },
        [
            {"material": plant.las, "quantity": D("100"), "unit": kg},
            {"material": plant.water, "quantity": D("50"), "unit": kg},
        ],
    )
    first, second = receipt.lines.order_by("line_no")
    inventory.set_receipt_costs(
        buyer,
        receipt,
        lines=[
            {
                "id": first.pk,
                "unit_price": D("6"),
                "currency": Currency.EUR,
                "exchange_rate": D(35),
            },
            {"id": second.pk, "unit_price": D("0.02")},
        ],
        extra_costs=[
            {"kind": FREIGHT, "description": "", "amount": D("100"), "allocation": BY_QUANTITY},
            {"kind": CUSTOMS, "description": "", "amount": D("50"), "allocation": BY_VALUE},
        ],
    )
    # Taslakta satır kaldırma: geçmişe satırın içi (fiyatıyla) yazılır.
    inventory.update_goods_receipt(depo, receipt, {}, [{"id": first.pk}])
    # Ek masraf kaldırma: geçmişe ek masrafın içi (tutarıyla) yazılır.
    freight = receipt.extra_costs.get(kind=FREIGHT)
    inventory.set_receipt_costs(
        buyer,
        receipt,
        extra_costs=[
            {
                "id": freight.pk,
                "kind": FREIGHT,
                "description": "",
                "amount": freight.amount,
                "allocation": BY_QUANTITY,
            }
        ],
    )
    with commit():
        inventory.post_goods_receipt(depo, receipt)
    with commit():
        inventory.set_receipt_costs(
            buyer,
            receipt,
            lines=[
                {
                    "id": first.pk,
                    "unit_price": D("7"),
                    "currency": Currency.EUR,
                    "exchange_rate": D(35),
                }
            ],
            note="Fiyat 6,00 EUR yerine 7,00 EUR",
        )
    return receipt


def _order(staff: dict[str, User], plant: Plant, commit: Commit) -> PurchaseOrder:
    """Sipariş: yalnız kur değişen ve karışık güncelleme, taslakta satır kaldırma, onaya gönderme
    (notta tutar, yönetime görev) ve onay (notta tutar, kur ve limit)."""
    buyer, manager = staff[SATIN_ALMA], staff[YONETIM]
    kg = unit("KG")
    order = purchasing.create_order(
        buyer,
        {
            "supplier": SupplierFactory.create(name="Sonda Tedarik A.Ş."),
            "order_date": ORDER_DATE,
            "currency": Currency.EUR,
            "exchange_rate": D(34),
            "notes": "",
        },
        [
            {
                "material": plant.las,
                "quantity": D("100"),
                "unit": kg,
                "unit_price": D("10"),
                "expected_date": EXPECTED_DATE,
            },
            {
                "material": plant.sles,
                "quantity": D("50"),
                "unit": kg,
                "unit_price": D("20"),
                "expected_date": EXPECTED_DATE,
            },
        ],
    )
    purchasing.update_order(buyer, order, {"exchange_rate": D(35)})
    purchasing.update_order(buyer, order, {"notes": "Acil teslim", "exchange_rate": D(36)})
    first = order.lines.order_by("line_no").first()
    assert first is not None
    purchasing.update_order(buyer, order, {}, [{"id": first.pk}])
    with commit():
        purchasing.submit_for_approval(buyer, order)
    with commit():
        purchasing.approve_order(manager, order)
    return order


def _receivable(staff: dict[str, User], plant: Plant) -> PurchaseOrder:
    order = purchasing.create_order(
        staff[SATIN_ALMA],
        {
            "supplier": SupplierFactory.create(name="Sonda Ambalaj A.Ş."),
            "order_date": ORDER_DATE,
            "currency": Currency.EUR,
            "exchange_rate": D(35),
        },
        [
            {
                "material": plant.las,
                "quantity": D("100"),
                "unit": unit("KG"),
                "unit_price": D("8"),
                "expected_date": EXPECTED_DATE,
            }
        ],
    )
    return purchasing.approve_order(staff[YONETIM], order)


def _sales_order(staff: dict[str, User]) -> SalesOrder:
    """Fiyatlı satış siparişi; taslakta kaldırılan satır geçmişe fiyatıyla yazılır."""
    seller = staff[SEVKIYAT]
    product = finished_product(name="Sonda bulaşık deterjanı")
    order = sales.create_order(
        seller,
        {"customer": CustomerFactory.create(name="Sonda Müşteri Ltd."), "order_date": date.today()},
        [
            {
                "product": product,
                "quantity": D("24"),
                "unit": unit("ADET"),
                "unit_price": D("12.5"),
                "currency": Currency.TRY,
            },
            {
                "product": product,
                "quantity": D("2"),
                "unit": unit("KOLI"),
                "unit_price": D("140"),
                "currency": Currency.TRY,
            },
        ],
    )
    first = order.lines.order_by("line_no").first()
    assert first is not None
    sales.update_order(seller, order, {}, [{"id": first.pk}])
    return order


def _scene(commit: Commit) -> Scene:
    staff = _staff()
    chain = build_chain(staff, commit, fill=False)
    assert chain.batch is not None
    labor_rate = _labor_rate(staff, chain.batch)
    receipt = _receipt(staff, chain.plant, commit)
    line = receipt.lines.get()
    assert line.created_lot is not None
    order = _order(staff, chain.plant, commit)
    receivable = _receivable(staff, chain.plant)
    sales_order = _sales_order(staff)
    return Scene(
        staff=staff,
        plant=chain.plant,
        receipt=receipt,
        lot=line.created_lot,
        order=order,
        receivable=receivable,
        sales_order=sales_order,
        labor_rate=labor_rate,
        write_supplier=SupplierFactory.create(name="Sonda Yazma A.Ş."),
    )


def _draft_receipt(scene: Scene) -> GoodsReceiptLine:
    """Yazma sondası için yeni taslak mal kabul (5 TL fiyatlı tek satır)."""
    receipt = inventory.create_goods_receipt(
        scene.staff[DEPO],
        {
            "supplier": scene.write_supplier,
            "receipt_date": date.today(),
            "quarantine_location": scene.plant.quarantine,
            "storage_location": scene.plant.storage,
        },
        [
            {
                "material": scene.plant.water,
                "quantity": D("10"),
                "unit": unit("KG"),
                "unit_price": D("5"),
            }
        ],
    )
    return receipt.lines.get()


# --- sondalar --------------------------------------------------------------------------------

Probe = Callable[[APIClient], Json]


def _each(clients: Mapping[str, APIClient], probe: Probe) -> dict[str, Json]:
    return {persona: probe(client) for persona, client in clients.items()}


def _history(client: APIClient, label: str, object_id: int, *, computed: bool = False) -> Json:
    response = client.get(
        f"{API}/workflow/record-history/", {"content_type": label, "object_id": str(object_id)}
    )
    refused = _refused(response)
    if refused is not None:
        return refused
    return {"status": 200, "entries": [_entry(e, computed=computed) for e in _results(response)]}


def _rows(client: APIClient, url: str, params: Mapping[str, Json]) -> Json:
    response = client.get(url, params)
    refused = _refused(response)
    if refused is not None:
        return refused
    return {"status": 200, "rows": [_money(row) for row in _results(response)]}


def _document(client: APIClient, url: str) -> Json:
    """Ayrıntı: başlıktaki ve satırlardaki tutar alanları."""
    response = client.get(url)
    refused = _refused(response)
    if refused is not None:
        return refused
    data = response.json()
    return {
        "status": 200,
        "money": _money(data),
        "lines": [_money(line) for line in data.get("lines", [])],
    }


def _receipt_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    receipt = scene.receipt
    url = f"{API}/inventory/goods-receipts/"
    return {
        "goods_receipt.list": _each(
            clients, lambda c: _rows(c, url, {"supplier": receipt.supplier_id})
        ),
        "goods_receipt.detail": _each(clients, lambda c: _document(c, f"{url}{receipt.pk}/")),
        "goods_receipt.history": _each(
            clients, lambda c: _history(c, "inventory.goodsreceipt", receipt.pk)
        ),
    }


def _receipt_write_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    """Fiyatı göremeyenin gönderdiği fiyat yok sayılır mı (her persona kendi kaydında)."""
    url = f"{API}/inventory/goods-receipts/"
    water, kg = scene.plant.water, unit("KG")

    def create(client: APIClient) -> Json:
        response = client.post(
            url,
            {
                "supplier": scene.write_supplier.pk,
                "receipt_date": date.today().isoformat(),
                "quarantine_location": scene.plant.quarantine.pk,
                "storage_location": scene.plant.storage.pk,
                "lines": [
                    {
                        "material": water.pk,
                        "quantity": "5",
                        "unit": kg.pk,
                        "unit_price": "3.5",
                        "currency": "EUR",
                        "exchange_rate": "35",
                    }
                ],
                "extra_costs": [{"kind": FREIGHT, "amount": "9", "allocation": BY_QUANTITY}],
            },
            format="json",
        )
        refused = _refused(response)
        if refused is not None:
            return refused
        receipt = GoodsReceipt.objects.get(pk=response.json()["id"])
        return {
            "status": response.status_code,
            "stored": _stored(receipt.lines.get()),
            "extra_costs": receipt.extra_costs.count(),
        }

    def update(client: APIClient) -> Json:
        line = _draft_receipt(scene)
        response = client.patch(
            f"{url}{line.receipt_id}/",
            {
                "lines": [
                    {
                        "id": line.pk,
                        "material": water.pk,
                        "quantity": "12",
                        "unit": kg.pk,
                        "unit_price": "999",
                        "currency": "USD",
                        "exchange_rate": "40",
                    }
                ]
            },
            format="json",
        )
        return _refused(response) or {"status": response.status_code, "stored": _stored(line)}

    def set_costs(client: APIClient) -> Json:
        line = _draft_receipt(scene)
        response = client.post(
            f"{url}{line.receipt_id}/costs/",
            {
                "lines": [
                    {"id": line.pk, "unit_price": "4", "currency": "USD", "exchange_rate": "40"}
                ],
                "extra_costs": [{"kind": FREIGHT, "amount": "9", "allocation": BY_QUANTITY}],
            },
            format="json",
        )
        refused = _refused(response)
        if refused is not None:
            return refused
        amounts = [str(row.amount) for row in line.receipt.extra_costs.order_by("id")]
        return {"status": response.status_code, "stored": _stored(line), "extra_costs": amounts}

    return {
        "goods_receipt.write.create": _each(clients, create),
        "goods_receipt.write.update": _each(clients, update),
        "goods_receipt.write.costs": _each(clients, set_costs),
    }


def _order_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    order, receivable = scene.order, scene.receivable
    url = f"{API}/purchasing/orders/"

    def pdf(client: APIClient) -> Json:
        response = client.get(f"{url}{order.pk}/pdf/")
        return _refused(response) or {"status": 200, "content_type": response["Content-Type"]}

    def approval_task(client: APIClient) -> Json:
        # Görevin açıklamasında sipariş tutarı yazar (`workflow.rules`, purchase_order_approval).
        response = client.get(
            f"{API}/workflow/tasks/",
            {
                "rule_code": "purchase_order_approval",
                "content_type": "purchasing.purchaseorder",
                "object_id": str(order.pk),
            },
        )
        refused = _refused(response)
        if refused is not None:
            return refused
        return {
            "status": 200,
            "descriptions": sorted(_masked(task["description"]) for task in _results(response)),
        }

    return {
        "purchase_order.list": _each(
            clients, lambda c: _rows(c, url, {"supplier": order.supplier_id})
        ),
        "purchase_order.detail": _each(clients, lambda c: _document(c, f"{url}{order.pk}/")),
        "purchase_order.pdf": _each(clients, pdf),
        "purchase_order.history": _each(
            clients, lambda c: _history(c, "purchasing.purchaseorder", order.pk)
        ),
        "purchase_order.approval_task": _each(clients, approval_task),
        "purchase_order.expected_deliveries": _each(
            clients,
            lambda c: _rows(
                c, f"{API}/purchasing/expected-deliveries/", {"supplier": receivable.supplier_id}
            ),
        ),
    }


def _order_write_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    """Siparişten açılan taslak mal kabule fiyat, kim açarsa açsın siparişten geçer."""
    receivable = scene.receivable

    def receive(client: APIClient) -> Json:
        line = receivable.lines.get()
        response = client.post(
            f"{API}/purchasing/orders/{receivable.pk}/receive/",
            {
                "receipt_date": date.today().isoformat(),
                "quarantine_location": scene.plant.quarantine.pk,
                "storage_location": scene.plant.storage.pk,
                "lines": [{"order_line": line.pk, "quantity": "1"}],
            },
            format="json",
        )
        refused = _refused(response)
        if refused is not None:
            return refused
        receipt = GoodsReceipt.objects.get(pk=response.json()["id"])
        return {"status": response.status_code, "stored": _stored(receipt.lines.get())}

    return {"purchase_order.write.receive": _each(clients, receive)}


def _lot_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    lot = scene.lot
    url = f"{API}/inventory/lots/"

    def cost_history(client: APIClient) -> Json:
        response = client.get(f"{API}/costing/lots/{lot.pk}/")
        refused = _refused(response)
        if refused is not None:
            return refused
        versions = [
            {
                "version": version["version"],
                "money": _money(version, computed=True),
                "note": _masked(version["note"]),
            }
            for version in response.json()["versions"]
        ]
        return {"status": 200, "versions": versions}

    return {
        "lot.list": _each(clients, lambda c: _rows(c, url, {"supplier": lot.supplier_id})),
        "lot.detail": _each(clients, lambda c: _document(c, f"{url}{lot.pk}/")),
        "lot.history": _each(
            clients, lambda c: _history(c, "inventory.lot", lot.pk, computed=True)
        ),
        "lot.cost_history": _each(clients, cost_history),
    }


def _sales_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    order = scene.sales_order
    url = f"{API}/sales/orders/"
    return {
        "sales_order.list": _each(
            clients, lambda c: _rows(c, url, {"customer": order.customer_id})
        ),
        "sales_order.detail": _each(clients, lambda c: _document(c, f"{url}{order.pk}/")),
        "sales_order.history": _each(clients, lambda c: _history(c, "sales.salesorder", order.pk)),
    }


def _costing_cases(scene: Scene, clients: Mapping[str, APIClient]) -> Cases:
    rate = scene.labor_rate
    url = f"{API}/costing/rates/"

    def shown(row: Mapping[str, Json]) -> Json:
        return {"rate_per_kg": _shape(row["rate_per_kg"]), "note": _masked(row["note"])}

    def rate_list(client: APIClient) -> Json:
        response = client.get(url, {"kind": "LABOR", "stage": "PRODUCTION"})
        refused = _refused(response)
        if refused is not None:
            return refused
        rows = [shown(row) for row in _results(response) if row["id"] == rate.pk]
        return {"status": 200, "labor_rate": rows}

    def rate_detail(client: APIClient) -> Json:
        response = client.get(f"{url}{rate.pk}/")
        return _refused(response) or {"status": 200, "labor_rate": shown(response.json())}

    def personnel_cost(client: APIClient) -> Json:
        response = client.get(f"{API}/costing/personnel-costs/{COST_YEAR}/{COST_MONTH}/")
        refused = _refused(response)
        if refused is not None:
            return refused
        data = response.json()
        amounts = ("gross_salary", "overtime_pay", "extras_total", "employer_share", "total_cost")
        row_amounts = ("gross_monthly", "gross_salary", "gross_total", "employer_share")
        return {
            "status": 200,
            "totals": {key: _shape(data[key]) for key in amounts},
            "stages": [
                {"stage": stage["stage"], **_money(stage, computed=True)}
                for stage in sorted(data["stages"], key=lambda item: item["stage"])
            ],
            "rows": [
                {key: _shape(row[key]) for key in (*row_amounts, "total_cost")}
                for row in data["rows"]
            ],
        }

    return {
        "costing.labor_rate.list": _each(clients, rate_list),
        "costing.labor_rate.detail": _each(clients, rate_detail),
        "costing.personnel_cost": _each(clients, personnel_cost),
    }


def _report_cases(clients: Mapping[str, APIClient]) -> Cases:
    sensitive = {(code, key) for code, key, _kind in _sensitive_columns()}
    stock = REPORTS["stock-status"]
    summary = stock.summary([]) if stock.summary is not None else []
    money_summary = [key for key, _value, kind in summary if kind == "money"]
    labels = sorted(
        {c.label for c in stock.columns if c.sensitive}
        | {stock.summary_labels[key] for key in money_summary}
    )
    report_url = f"{API}/reporting/reports/stock-status/"

    def report_list(client: APIClient) -> Json:
        response = client.get(f"{API}/reporting/reports/")
        refused = _refused(response)
        if refused is not None:
            return refused
        shown = {
            report["code"]: sorted(
                column["key"]
                for column in report["columns"]
                if (report["code"], column["key"]) in sensitive
            )
            for report in response.json()
            if any(code == report["code"] for code, _key in sensitive)
        }
        return {"status": 200, "sensitive_columns": shown}

    def stock_status(client: APIClient) -> Json:
        response = client.get(report_url)
        refused = _refused(response)
        if refused is not None:
            return refused
        data = response.json()
        keys = {key for _code, key in sensitive}
        first = data["results"][0] if data["results"] else {}
        return {
            "status": 200,
            "columns": sorted(c["key"] for c in data["columns"] if c["key"] in keys),
            "row_keys": sorted(key for key in first if key in keys),
            "summary": sorted(item["key"] for item in data["summary"]),
        }

    def stock_status_excel(client: APIClient) -> Json:
        response = client.post(f"{report_url}export/", {"file_format": "xlsx"}, format="json")
        refused = _refused(response)
        if refused is not None:
            return refused
        sheet = load_workbook(BytesIO(response.content), read_only=True).worksheets[0]
        cells = {value for row in sheet.iter_rows(values_only=True) for value in row}
        return {"status": 200, "sensitive_labels": [label for label in labels if label in cells]}

    def management(client: APIClient) -> Json:
        response = client.get(f"{API}/reporting/dashboards/management/")
        refused = _refused(response)
        if refused is not None:
            return refused
        data = response.json()
        value = data["stock_value"]
        return {
            "status": 200,
            "stock_value": None if value is None else sorted(value),
            "pending_purchase_total_try": _shape(data["approvals"]["purchase_orders"]["total_try"]),
        }

    return {
        "reporting.report_list": _each(clients, report_list),
        "reporting.stock_status": _each(clients, stock_status),
        "reporting.stock_status_excel": _each(clients, stock_status_excel),
        "reporting.management_dashboard": _each(clients, management),
    }


def _registry_cases(users: Mapping[str, User | None]) -> Cases:
    """Kayıt türlerinin gizli alanları. API bunu yalnız alanı değişmiş kayıtta gösterir; her tür
    için kayıt defterinden okunur (`records.registered_record_types`, `records.hidden_fields_for`).
    """
    labels = [
        label
        for label in records.registered_record_types()
        if (access := records.record_access(label)) is not None and access.hidden_fields is not None
    ]
    assert labels == HIDDEN_FIELD_TYPES, (
        f"Gizli alanlı kayıt türleri değişti: {labels}. Bilinçli bir değişiklikse (plan §8) bu "
        "listeyi ve anlık görüntüyü birlikte güncelleyin."
    )
    return {
        f"record_type.hidden_fields.{label}": {
            persona: sorted(records.hidden_fields_for(user, label))
            for persona, user in users.items()
        }
        for label in labels
    }


def _sensitive_columns() -> list[tuple[str, str, str]]:
    return sorted(
        (definition.code, column.key, column.sensitive)
        for definition in REPORTS.values()
        for column in definition.columns
        if column.sensitive is not None
    )


# --- kurulumun sağlaması ---------------------------------------------------------------------


def _assert_scene_has_every_situation(cases: Cases) -> None:
    """Kurulum dondurulacak her durumu üretmiş mi. Fiyatı gören personada yalnız yapıya bakar;
    metinler ve görünürlük anlık görüntüdedir (plan §8 onları değiştirebilir, bu denetim değil)."""

    def entries(case: str, persona: str) -> list[dict[str, Json]]:
        return list(cases[case][persona]["entries"])

    def nested(items: list[dict[str, Json]], key: str, field: str) -> bool:
        return any(field in (e["money"].get(key) or [{}])[0] for e in items)

    receipt = entries("goods_receipt.history", "yonetim")
    assert nested(receipt, "line", "unit_price"), "mal kabulde silinen satır kaydı yok"
    assert nested(receipt, "extra_cost", "amount"), "mal kabulde silinen ek masraf kaydı yok"
    assert any(e["action"] == "update" and e["note"] for e in receipt[:1]), "fiyat düzeltmesi yok"
    order = entries("purchase_order.history", "satin_alma")
    assert nested(order, "line", "unit_price"), "siparişte silinen satır kaydı yok"
    assert any(set(e["money"]) == {"exchange_rate"} for e in order), "yalnız kur değişmedi"
    assert sum(e["action"] == "status_change" for e in order) >= 2, "onaya gönderme ve onay yok"
    assert nested(entries("sales_order.history", "sevkiyat"), "line", "unit_price")
    assert sum("unit_cost" in e["money"] for e in entries("lot.history", "yonetim")) == 2
    assert len(cases["purchase_order.approval_task"]["yonetim"]["descriptions"]) == 1
    assert cases["costing.labor_rate.detail"]["yonetim"]["labor_rate"]["note"]


# --- test ------------------------------------------------------------------------------------


def test_price_and_cost_visibility_matches_snapshot(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> None:
    users = make_personas()
    scene = _scene(lambda: django_capture_on_commit_callbacks(execute=True))
    clients: dict[str, APIClient] = {}
    for persona, user in users.items():
        clients[persona] = persona_client(user)
    assert tuple(clients) == PERSONAS
    assert _sensitive_columns() == SENSITIVE_COLUMNS, (
        f"Raporların hassas sütunları değişti: {_sensitive_columns()}. Bilinçliyse (plan §8) "
        "bu listeyi ve anlık görüntüyü birlikte güncelleyin."
    )

    # Okumalar yazmalardan önce: yazma sondalarının kayıtları okunan kayıtlara karışmaz.
    builders: Iterable[Callable[[], Cases]] = (
        lambda: _receipt_cases(scene, clients),
        lambda: _order_cases(scene, clients),
        lambda: _lot_cases(scene, clients),
        lambda: _sales_cases(scene, clients),
        lambda: _costing_cases(scene, clients),
        lambda: _report_cases(clients),
        lambda: _registry_cases(users),
        lambda: _receipt_write_cases(scene, clients),
        lambda: _order_write_cases(scene, clients),
    )
    cases: Cases = {}
    for build in builders:
        cases.update(build())

    _assert_scene_has_every_situation(cases)
    snapshot.check(NAME, cases)
    assert_stock_invariants()
