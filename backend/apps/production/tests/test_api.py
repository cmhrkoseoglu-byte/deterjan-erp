from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory.models import Lot
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.tests.factories import unit
from apps.production import services
from apps.production.models import ProductionOrder
from apps.production.tests.factories import approved_order, ready_order

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal


def url(name, *args, **query):
    path = reverse(f"production:{name}", args=args)
    if query:
        path += "?" + "&".join(f"{key}={value}" for key, value in query.items())
    return path


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def order_body(plant, quantity="1000"):
    return {
        "recipe_version": plant.version.pk,
        "planned_quantity": quantity,
        "unit": unit("KG").pk,
        "planned_date": "2026-10-20",
        "equipment": plant.tank.pk,
        "priority": 3,
    }


# --- yetki -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["order-list", "batch-list"])
def test_read_requires_login_but_no_role(name, client_for):
    assert APIClient().get(url(name)).status_code == 401
    assert client_for().get(url(name)).status_code == 200


@pytest.mark.parametrize("role", ["depo", "uretim", "laboratuvar", "yonetim"])
def test_only_planning_writes_orders(role, client_for, plant, planner):
    api = client_for(role)
    order = services.create_order(planner, {**_data(plant)})
    assert api.post(url("order-list"), order_body(plant), format="json").status_code == 403
    assert (
        api.patch(url("order-detail", order.pk), {"notes": "x"}, format="json").status_code == 403
    )
    assert api.post(url("order-approve", order.pk), {}, format="json").status_code == 403
    assert api.post(url("order-cancel", order.pk), {"reason": "x"}).status_code == 403


@pytest.mark.parametrize("role", ["planlama", "uretim", "laboratuvar"])
def test_only_depo_prepares(role, client_for, plant, planner):
    api = client_for(role)
    order = approved_order(plant, planner)
    assert api.post(url("order-start-prep", order.pk)).status_code == 403
    assert api.post(url("order-mark-ready", order.pk)).status_code == 403
    assert api.post(url("order-picks", order.pk), {}, format="json").status_code == 403
    assert api.get(url("order-picks", order.pk)).status_code == 200


@pytest.mark.parametrize("role", ["planlama", "depo", "laboratuvar"])
def test_only_production_runs_batches(role, client_for, plant, planner, depo, operator):
    api = client_for(role)
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)
    assert api.post(url("batch-list"), {"order": order.pk}, format="json").status_code == 403
    assert api.post(url("batch-consume", batch.pk), {}, format="json").status_code == 403
    assert api.post(url("batch-finish", batch.pk), {}, format="json").status_code == 403
    assert api.post(url("batch-cancel", batch.pk), {"reason": "x"}).status_code == 403


def _data(plant):
    return {
        "recipe_version": plant.version,
        "planned_quantity": D("1000"),
        "unit": unit("KG"),
        "planned_date": "2026-10-20",
        "equipment": plant.tank,
    }


# --- emir --------------------------------------------------------------------------------------


def test_create_update_approve_order(plant, planner):
    api = client(planner)

    response = api.post(url("order-list"), order_body(plant, "2000"), format="json")
    assert response.status_code == 201, response.data
    body = response.data
    assert body["number"].startswith("UE-")
    assert body["status"] == "DRAFT"
    assert body["product_code"] == "BULASIK"
    assert body["production_location_code"] == "URETIM"

    # Durum PATCH ile değişmez.
    response = api.patch(
        url("order-detail", body["id"]),
        {"status": "COMPLETED", "planned_quantity": "1500"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "DRAFT"
    assert response.data["planned_base_quantity"] == "1500.0000"

    response = api.post(url("order-approve", body["id"]), {}, format="json")
    assert response.status_code == 200
    assert response.data["status"] == "APPROVED"
    codes = [(r["material_code"], r["required_quantity"]) for r in response.data["requirements"]]
    assert codes == [("LAS", "900.0000"), ("SLES", "450.0000"), ("SU", "150.0000")]
    assert response.data["allowed_transitions"] == ["CANCELLED", "MATERIAL_PREP"]
    # Hesaplanan miktarlar da JSON'da metin döner (arayüz "600.0000" bekler).
    assert response.json()["remaining_quantity"] == "1500.0000"
    assert response.json()["suggested_batch_quantity"] == "1000.0000"

    listing = api.get(url("order-list"), {"status": "APPROVED"})
    assert [row["id"] for row in listing.data["results"]] == [body["id"]]


def test_business_errors_are_400_with_code(plant, planner):
    api = client(planner)
    order = approved_order(plant, planner)

    response = api.post(url("order-approve", order.pk), {}, format="json")

    assert response.status_code == 400
    assert response.data["code"] == "invalid_transition"


# --- hazırlama ---------------------------------------------------------------------------------


def test_pick_by_scanned_lot_number_and_mark_ready(plant, planner, depo):
    api = client(depo)
    order = approved_order(plant, planner)
    detail = api.get(url("order-detail", order.pk)).data
    rows = {r["material_code"]: r for r in detail["requirements"]}

    suggestions = api.get(
        url("order-pick-suggestions", order.pk), {"requirement": rows["LAS"]["id"]}
    )
    assert [s["lot_no"] for s in suggestions.data] == [plant.lots["las"].lot_no]

    for code in ("LAS", "SLES"):
        response = api.post(
            url("order-picks", order.pk),
            {
                "requirement": rows[code]["id"],
                "lot_no": plant.lots[code.lower()].lot_no.lower(),
                "quantity": rows[code]["required_quantity"],
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["to_location_code"] == "URETIM"

    response = api.post(url("order-mark-ready", order.pk))
    assert response.status_code == 200, response.data
    assert response.data["status"] == "MATERIAL_READY"
    assert all(r["is_ready"] for r in response.data["requirements"])
    assert len(response.data["picks"]) == 2


def test_quarantine_lot_scan_is_rejected(plant, planner, depo):
    api = client(depo)
    order = approved_order(plant, planner)
    quarantined = stocked_lot(
        "50", material=plant.las, location=plant.quarantine, status=Lot.Status.QUARANTINE
    )
    requirement = plant.requirement(order, plant.las)

    response = api.post(
        url("order-picks", order.pk),
        {"requirement": requirement.pk, "lot_no": quarantined.lot_no, "quantity": "10"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "lot_not_released"


def test_unknown_lot_scan_is_rejected(plant, planner, depo):
    api = client(depo)
    order = approved_order(plant, planner)
    requirement = plant.requirement(order, plant.las)

    response = api.post(
        url("order-picks", order.pk),
        {"requirement": requirement.pk, "lot_no": plant.lots["sles"].lot_no, "quantity": "10"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "lot_not_found"
    # Lot kimliğiyle (olmayan ya da başka malzemenin lotu) mesaj kimliği gösterir; lot no da
    # gönderilse aranan kimliktir.
    missing_id = Lot.objects.latest("pk").pk + 1
    for lot_id, lot_no in ((missing_id, ""), (missing_id, "YOK-1"), (plant.lots["sles"].pk, "")):
        response = api.post(
            url("order-picks", order.pk),
            {"requirement": requirement.pk, "lot": lot_id, "lot_no": lot_no, "quantity": "10"},
            format="json",
        )
        assert (response.status_code, response.data) == (
            400,
            {
                "code": "lot_not_found",
                "detail": f"{plant.las.code} malzemesinde {lot_id} lotu bulunamadı.",
            },
        ), (lot_id, lot_no)


GTIN = "8690000000012"
CASE_GTIN = "18690000000019"  # koli GTIN'i (GTIN-14)


def with_case_gtin(plant):
    """LAS'a ürün GTIN'i ve 1 KOLI = 25 kg koli dönüşümünde koli GTIN'i."""
    Material.objects.filter(pk=plant.las.pk).update(gtin=GTIN)
    MaterialUnitConversion.objects.create(
        material=plant.las, unit=unit("KOLI"), factor_to_base=D("25"), gtin=CASE_GTIN
    )


def test_pick_by_gs1_barcode(plant, planner, depo, operator):
    """Üretim ortak lot çözümünü kullanır (GS1 adım 7): koli barkodu ((01) koli GTIN'i + (10) lot),
    ham GS1, ürün GTIN'i ve lot etiketi (`LOT:`) yalnızca ihtiyacın malzemesindeki lotu bulur."""
    las = plant.lots["las"]
    with_case_gtin(plant)
    order = approved_order(plant, planner)
    requirement = plant.requirement(order, plant.las)

    def pick(code, user=depo):
        body = {"requirement": requirement.pk, "lot_no": code, "quantity": "10"}
        return client(user).post(url("order-picks", order.pk), body, format="json")

    codes = [
        f"(01){CASE_GTIN}(10){las.lot_no}",
        f"]C101{CASE_GTIN}10{las.lot_no}",
        f"(01)0{GTIN}(10){las.lot_no.lower()}",
        f"LOT:{las.lot_no}",
        # AIM'siz (17)+(10): baştaki ya da sondaki GS (FNC1) GS1 işaretidir, metin kırpılmaz.
        "\x1d17281015" + f"10{las.lot_no}",
        "17281015" + f"10{las.lot_no}\x1d",
        # NBSP gibi boşluk atılır; arkasındaki parantezli AI yine GS1'dir.
        f"\xa0(01){CASE_GTIN}(10){las.lot_no}",
        # GS1 verisinin sonundaki boşluk da (NBSP, dikey sekme, NEL, RS) atılır.
        f"(01){CASE_GTIN}(10){las.lot_no}\xa0",
        f"(01){CASE_GTIN}(10){las.lot_no}\x0b",
        f"]C101{CASE_GTIN}10{las.lot_no}\x85",
        "\x1d17281015" + f"10{las.lot_no}\x1e",
    ]
    for code in codes:
        response = pick(code)
        assert response.status_code == 201, (repr(code), response.data)
        assert response.data["lot_no"] == las.lot_no
    # Boş ya da yalnız GS ve boşluk: lot okutulmamıştır.
    for blank in ("", "\x1d", " \x1d\r\n"):
        response = pick(blank)
        assert (response.status_code, response.json()["errors"]) == (
            400,
            {"lot_no": ["Lot okutulmalı ya da seçilmelidir."]},
        ), repr(blank)
    # Başka malzemenin lotu bu ihtiyaçta bulunmaz; GS1 kontrol hanesi denetlenir.
    other = pick(f"LOT:{plant.lots['sles'].lot_no}")
    assert other.status_code == 400 and other.data["code"] == "lot_not_found"
    # Mesajda okutulan ham veri (AIM, GS) değil, barkoddaki lot no.
    for code in (f"]C101{CASE_GTIN}10YOK-1\x1d17281015", "\x0b]C0YOK-1"):
        missing = pick(code)
        assert (missing.status_code, missing.data) == (
            400,
            {
                "code": "lot_not_found",
                "detail": f"{plant.las.code} malzemesinde YOK-1 lotu bulunamadı.",
            },
        ), repr(code)
    wrong = pick(f"(01){CASE_GTIN[:-1]}0(10){las.lot_no}")
    assert wrong.status_code == 400 and wrong.data["code"] == "gs1_check_digit"
    assert pick(f"(01){CASE_GTIN}(10){las.lot_no}", user=operator).status_code == 403


OLD_CASE_GTIN = "28690000000016"  # eski koli GTIN'i (arşivde)


def test_pick_by_archived_case_gtin(plant, planner, depo, operator):
    """Eski koli GTIN'i (arşiv: koli içi miktar değişince yerine yenisi verildi) depodaki eski
    kolilerde kalır: üretim ortak lot çözümüyle lotu güncel koli GTIN'indeki gibi, yalnızca
    ihtiyacın malzemesinde bulur. Arşiv satırı doğrudan yazılır (okutma malzeme türüne bakmaz)."""
    las, sles = plant.lots["las"], plant.lots["sles"]
    with_case_gtin(plant)
    RetiredGtin.objects.create(
        conversion=MaterialUnitConversion.objects.get(material=plant.las, unit__code="KOLI"),
        gtin=OLD_CASE_GTIN,
        factor_to_base=D("20"),
        replaced_by=CASE_GTIN,
    )
    order = approved_order(plant, planner)
    requirement = plant.requirement(order, plant.las)

    def pick(code, user=depo):
        body = {"requirement": requirement.pk, "lot_no": code, "quantity": "10"}
        return client(user).post(url("order-picks", order.pk), body, format="json")

    codes = [
        f"(01){OLD_CASE_GTIN}(10){las.lot_no}",
        f"]C101{OLD_CASE_GTIN}10{las.lot_no}\x1d17281015",
        f"\xa0(01){OLD_CASE_GTIN}(10){las.lot_no.lower()}\x1e",
    ]
    for code in codes:
        response = pick(code)
        assert response.status_code == 201, (repr(code), response.data)
        assert response.data["lot_no"] == las.lot_no
    # GTIN malzemeyi belirler: başka malzemenin lot no'su bu ihtiyaçta bulunmaz.
    other = pick(f"(01){OLD_CASE_GTIN}(10){sles.lot_no}")
    assert (other.status_code, other.data) == (
        400,
        {
            "code": "lot_not_found",
            "detail": f"{plant.las.code} malzemesinde {sles.lot_no} lotu bulunamadı.",
        },
    )
    assert pick(f"(01){OLD_CASE_GTIN}(10){las.lot_no}", user=operator).status_code == 403


# --- şarj ve tartım ----------------------------------------------------------------------------


def test_weigh_by_gs1_barcode(plant, planner, depo, operator):
    """Tartımda da ortak lot çözümü: koli barkodu lotu bulur, başka malzemenin lotu bulunmaz."""
    las = plant.lots["las"]
    with_case_gtin(plant)
    api = client(operator)
    order = ready_order(plant, planner, depo)
    batch = api.post(url("batch-list"), {"order": order.pk}, format="json").data
    lines = {line["material_code"]: line for line in batch["lines"]}
    body = {"requirement": lines["LAS"]["requirement"], "quantity": "600"}

    wrong = api.post(
        url("batch-consume", batch["id"]),
        {**body, "lot_no": f"LOT:{plant.lots['sles'].lot_no}"},
        format="json",
    )
    assert wrong.status_code == 400 and wrong.data["code"] == "lot_not_found"
    code = f"(01){CASE_GTIN}(17)281015(10){las.lot_no}"
    response = api.post(url("batch-consume", batch["id"]), {**body, "lot_no": code}, format="json")
    assert response.status_code == 200, response.data
    states = {line["material_code"]: line["state"] for line in response.data["lines"]}
    assert states["LAS"] == "ok"
    assert client(depo).post(url("batch-consume", batch["id"]), body).status_code == 403


def test_batch_start_weigh_finish(plant, planner, depo, operator):
    api = client(operator)
    order = ready_order(plant, planner, depo)

    response = api.post(url("batch-list"), {"order": order.pk}, format="json")
    assert response.status_code == 201, response.data
    batch = response.data
    assert batch["batch_no"].startswith("B-")
    assert batch["output_lot_status"] == "QUARANTINE"
    lines = {line["material_code"]: line for line in batch["lines"]}
    assert lines["LAS"]["planned_quantity"] == "600.0000"
    assert lines["LAS"]["state"] == "pending"
    assert [a["location_code"] for a in lines["LAS"]["available"]] == ["URETIM"]
    assert [a["location_code"] for a in lines["SU"]["available"]] == ["DEPO"]

    # Tolerans dışı tartım notsuz reddedilir.
    over = {"requirement": lines["SLES"]["requirement"], "lot_no": plant.lots["sles"].lot_no}
    response = api.post(url("batch-consume", batch["id"]), {**over, "quantity": "310"})
    assert response.status_code == 400
    assert response.data["code"] == "deviation_note_required"

    for code, quantity in (("LAS", "600"), ("SU", "100")):
        response = api.post(
            url("batch-consume", batch["id"]),
            {
                "requirement": lines[code]["requirement"],
                "lot": plant.lots[code.lower() if code != "SU" else "water"].pk,
                "quantity": quantity,
            },
            format="json",
        )
        assert response.status_code == 200, response.data
    response = api.post(
        url("batch-consume", batch["id"]), {**over, "quantity": "297", "note": ""}, format="json"
    )
    assert response.status_code == 200, response.data
    states = {line["material_code"]: line["state"] for line in response.data["lines"]}
    assert states == {"LAS": "ok", "SLES": "ok", "SU": "ok"}
    assert len(response.data["consumptions"]) == 3

    response = api.post(url("batch-finish", batch["id"]), {"output_quantity": "995"}, format="json")
    assert response.status_code == 200, response.data
    assert response.data["status"] == "COMPLETED"
    assert response.data["yield_pct"] == "99.50"
    assert response.data["order_status"] == "QC_PENDING"
    assert response.data["lines"][0]["available"] == []


def test_cancel_batch(plant, planner, depo, operator):
    api = client(operator)
    order = ready_order(plant, planner, depo)
    batch = services.start_batch(operator, order)

    response = api.post(url("batch-cancel", batch.pk), {"reason": "Yanlış tank"}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == "CANCELLED"
    assert ProductionOrder.objects.get(pk=order.pk).status == "IN_PRODUCTION"
