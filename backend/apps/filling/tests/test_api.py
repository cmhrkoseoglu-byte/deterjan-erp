from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.filling import services
from apps.filling.models import FillingOrder, FillingRun
from apps.filling.tests.factories import Line, approved_order, order_data, ready_order, started_run
from apps.inventory.models import Lot
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata.models import Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.tests.factories import unit

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal


def url(name, *args, **query):
    path = reverse(f"filling:{name}", args=args)
    if query:
        path += "?" + "&".join(f"{key}={value}" for key, value in query.items())
    return path


def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


def order_body(line: Line, units=500):
    return {
        "finished_product": line.finished.pk,
        "planned_units": units,
        "filling_line": line.filling_line.pk,
        "output_location": line.finished_store.pk,
        "planned_date": "2026-10-21",
    }


# --- yetki -----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["packaging-spec-list", "order-list", "run-list"])
def test_read_requires_login_but_no_role(name, client_for):
    assert APIClient().get(url(name)).status_code == 401
    assert client_for().get(url(name)).status_code == 200


@pytest.mark.parametrize("role", ["depo", "dolum", "laboratuvar", "yonetim"])
def test_only_planning_writes_specs_and_orders(role, client_for, line: Line, planner):
    api = client_for(role)
    order = services.create_order(planner, order_data(line))
    assert api.post(url("packaging-spec-copy", line.spec.pk), {}).status_code == 403
    assert api.post(url("order-list"), order_body(line), format="json").status_code == 403
    assert api.post(url("order-approve", order.pk), {}).status_code == 403
    assert api.post(url("order-cancel", order.pk), {"reason": "x"}).status_code == 403


@pytest.mark.parametrize("role", ["planlama", "dolum", "uretim"])
def test_only_depo_picks(role, client_for, line: Line, planner):
    order = approved_order(line, planner)
    row = order.requirements.get(material=line.bottle)
    api = client_for(role)
    body = {"requirement": row.pk, "lot_no": line.lots["bottle"].lot_no, "quantity": "10"}
    assert api.post(url("order-picks", order.pk), body, format="json").status_code == 403
    assert api.post(url("order-mark-ready", order.pk)).status_code == 403


@pytest.mark.parametrize("role", ["planlama", "depo", "laboratuvar"])
def test_only_filling_runs_the_line(role, client_for, line: Line, planner, depo, filler):
    order = ready_order(line, planner, depo)
    api = client_for(role)
    assert api.post(url("run-list"), {"order": order.pk}).status_code == 403
    run = services.start_run(filler, order)
    body = {"lot_no": line.lots["bulk"].lot_no, "quantity": "10"}
    assert api.post(url("run-consume-bulk", run.pk), body).status_code == 403
    assert api.post(url("run-finish", run.pk), {"good_units": 1}).status_code == 403
    assert api.post(url("order-finish", order.pk), {}).status_code == 403


# --- akış ------------------------------------------------------------------------------------


def test_spec_copy_edit_approve(line: Line, planner):
    api = client(planner)
    response = api.post(url("packaging-spec-copy", line.spec.pk), {"change_note": "Yeni koli"})
    assert response.status_code == 201, response.data
    draft = response.data
    assert draft["version_no"] == 2
    assert len(draft["lines"]) == 4

    response = api.patch(
        url("packaging-spec-detail", draft["id"]), {"units_per_case": 24}, format="json"
    )
    assert response.status_code == 200, response.data
    response = api.post(url("packaging-spec-approve", draft["id"]), {})
    assert response.status_code == 200, response.data
    assert response.data["status"] == "APPROVED"

    response = api.patch(
        url("packaging-spec-detail", draft["id"]), {"units_per_case": 6}, format="json"
    )
    assert response.status_code == 400
    assert response.data["code"] == "packaging_spec_locked"


def test_order_create_and_approve(line: Line, planner):
    api = client(planner)
    response = api.post(url("order-list"), order_body(line), format="json")
    assert response.status_code == 201, response.data
    assert response.data["number"].startswith("DO-")
    assert response.data["packaging_spec_version"] == 1

    response = api.post(url("order-approve", response.data["id"]), {})
    assert response.status_code == 200, response.data
    assert response.data["status"] == "APPROVED"
    rows = {row["material_code"]: row for row in response.data["requirements"]}
    assert D(rows["SISE-750"]["required_quantity"]) == D("510")


def test_pick_by_scan_and_suggestions(line: Line, planner, depo):
    order = approved_order(line, planner)
    row = order.requirements.get(material=line.bottle)
    api = client(depo)

    response = api.get(url("order-pick-suggestions", order.pk, requirement=row.pk))
    assert response.status_code == 200
    assert response.data[0]["lot_no"] == line.lots["bottle"].lot_no

    body = {"requirement": row.pk, "lot_no": f"LOT:{line.lots['bottle'].lot_no}", "quantity": "20"}
    response = api.post(url("order-picks", order.pk), body, format="json")
    assert response.status_code == 201, response.data

    body["lot_no"] = line.lots["cap"].lot_no
    response = api.post(url("order-picks", order.pk), body, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "lot_material_mismatch"

    body["lot_no"] = "H-000000-999"
    response = api.post(url("order-picks", order.pk), body, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "lot_not_found"


def test_filling_tablet_flow(line: Line, planner, depo, filler):
    order = ready_order(line, planner, depo)
    api = client(filler)

    response = api.post(url("run-list"), {"order": order.pk})
    assert response.status_code == 201, response.data
    run_id = response.data["id"]
    assert response.data["output_lot_no"].startswith("D-")
    # Koli etiketi türü için mamulün GTIN'i (Karar D-6); demo mamulde boş.
    assert response.data["finished_product_gtin"] == ""

    bulk = {"lot_no": line.lots["bulk"].lot_no, "quantity": "781"}
    assert api.post(url("run-consume-bulk", run_id), bulk).status_code == 200

    response = api.post(url("run-scan", run_id), {"lot_no": line.lots["cap"].lot_no})
    assert response.status_code == 200, response.data
    wrong = api.post(url("run-scan", run_id), {"lot_no": line.lots["bulk"].lot_no})
    assert wrong.status_code == 400
    assert wrong.data["code"] == "lot_material_mismatch"

    scrap = {"kind": "FINISHED", "reason_code": "UNDERFILL", "quantity": "2"}
    assert api.post(url("run-scrap", run_id), scrap).status_code == 200
    scrap = {
        "kind": "PACKAGING",
        "reason_code": "LABEL_ERROR",
        "quantity": "3",
        "lot_no": line.lots["label"].lot_no,
    }
    response = api.post(url("run-scrap", run_id), scrap)
    assert response.status_code == 200, response.data
    assert len(response.data["scraps"]) == 2

    response = api.post(url("run-finish", run_id), {"good_units": 1000})
    assert response.status_code == 200, response.data
    assert response.data["status"] == "COMPLETED"
    assert response.data["good_units"] == 1000

    response = api.get(url("run-report", run_id))
    assert response.status_code == 200
    assert D(response.data["bulk"]["theoretical"]) == D("780")

    response = api.post(url("order-finish", order.pk), {})
    assert response.status_code == 200, response.data
    assert response.data["status"] == FillingOrder.Status.QC_PENDING
    assert Lot.objects.get(pk=FillingRun.objects.get(pk=run_id).output_lot_id).status == (
        Lot.Status.QUARANTINE
    )

    response = api.get(url("order-report", order.pk))
    assert response.status_code == 200
    assert response.data["good_units"] == 1000


CAP_GTIN = "8690000000043"
BULK_GTIN = "8690000000050"


def test_run_uses_gs1_barcodes_for_lots(line: Line, planner, depo, filler):
    """Dolum ortak lot çözümünü kullanır (GS1 adım 7): bulk, ambalaj ve fire lotu GS1 barkoduyla
    ((01) GTIN + (10) lot) okutulur. Başka malzemenin barkodu o lotu bulur, servis
    `lot_material_mismatch` der; bilinmeyen lot `lot_not_found`, hatalı kontrol hanesi
    `gs1_check_digit`."""
    Material.objects.filter(pk=line.cap.pk).update(gtin=CAP_GTIN)
    Material.objects.filter(pk=line.bulk.pk).update(gtin=BULK_GTIN)
    run = started_run(line, planner, depo, filler)
    api = client(filler)
    cap, bulk = line.lots["cap"].lot_no, line.lots["bulk"].lot_no

    consumed = api.post(
        url("run-consume-bulk", run.pk), {"lot_no": f"(01)0{BULK_GTIN}(10){bulk}", "quantity": "10"}
    )
    assert consumed.status_code == 200, consumed.data
    scanned = api.post(url("run-scan", run.pk), {"lot_no": f"]C1010{CAP_GTIN}10{cap}"})
    assert scanned.status_code == 200, scanned.data
    wrong = api.post(url("run-scan", run.pk), {"lot_no": f"(01)0{BULK_GTIN}(10){bulk}"})
    assert wrong.status_code == 400 and wrong.data["code"] == "lot_material_mismatch"
    missing = api.post(url("run-scan", run.pk), {"lot_no": f"(01)0{CAP_GTIN}(10)YOK-1"})
    assert missing.status_code == 400 and missing.data["code"] == "lot_not_found"
    # Mesajda okutulan ham veri (AIM, GS) değil, barkoddaki lot no.
    raw_missing = api.post(
        url("run-scan", run.pk), {"lot_no": f"]C1010{CAP_GTIN}10YOK-1\x1d17281015"}, format="json"
    )
    assert raw_missing.data == {
        "code": "lot_not_found",
        "detail": "Ambalaj için YOK-1 lotu bulunamadı.",
    }
    # Lot kimliğiyle okutmada mesaj kimliği gösterir (lot no da gönderilse aranan kimliktir).
    missing_id = Lot.objects.latest("pk").pk + 1
    for body in ({"lot": missing_id}, {"lot": missing_id, "lot_no": "YOK-1"}):
        assert api.post(url("run-scan", run.pk), body, format="json").data == {
            "code": "lot_not_found",
            "detail": f"Ambalaj için {missing_id} lotu bulunamadı.",
        }
    bad = api.post(url("run-scan", run.pk), {"lot_no": f"(01)0{CAP_GTIN[:-1]}0(10){cap}"})
    assert bad.status_code == 400 and bad.data["code"] == "gs1_check_digit"
    scrap = {
        "kind": "PACKAGING",
        "reason_code": "DAMAGED_PACKAGING",
        "quantity": "2",
        "lot_no": f"(01)0{CAP_GTIN}(10){cap.lower()}",
    }
    response = api.post(url("run-scrap", run.pk), scrap)
    assert response.status_code == 200, response.data
    assert len(response.data["scraps"]) == 1
    # AIM'siz (17)+(10): baştaki ya da sondaki GS (FNC1) GS1 işaretidir, metin kırpılmaz; kenardaki
    # diğer boşlukları (NBSP, RS) lot çözümü atar.
    for start, end in (("\x1d", ""), ("", "\x1d"), ("\xa0\x1d", "\x1e")):
        consumed = api.post(
            url("run-consume-bulk", run.pk),
            {"lot_no": f"{start}17281015" + f"10{bulk}{end}", "quantity": "10"},
            format="json",
        )
        assert consumed.status_code == 200, (start, end, consumed.data)
        code = f"{start}17281015" + f"10{cap}{end}"
        scanned = api.post(url("run-scan", run.pk), {"lot_no": code}, format="json")
        assert scanned.status_code == 200, (start, end, scanned.data)
        response = api.post(url("run-scrap", run.pk), {**scrap, "lot_no": code}, format="json")
        assert response.status_code == 200, (start, end, response.data)
    assert len(response.data["scraps"]) == 4
    # Yalnız GS ve boşluk: lot okutulmamıştır.
    blank = " \x1d\r\n"
    scanned = api.post(url("run-scan", run.pk), {"lot_no": blank}, format="json")
    assert scanned.json()["errors"] == {"lot_no": ["Lot okutulmalı ya da seçilmelidir."]}
    response = api.post(url("run-scrap", run.pk), {**scrap, "lot_no": blank}, format="json")
    assert response.json()["errors"] == {"lot_no": ["Fire için lot okutulmalıdır."]}
    assert client(depo).post(url("run-scan", run.pk), {"lot_no": cap}).status_code == 403


def test_run_scan_reads_archived_case_gtins(line: Line, planner, depo, filler):
    """Dolum ortak lot çözümü eski koli GTIN'ini (arşiv: koli içi miktar değişince yerine yenisi
    verildi) güncel koli GTIN'i gibi okur: ambalajın eski koli barkodu lotu bulur; mamulün eski
    koli barkodu da lotunu bulur, servis `lot_material_mismatch` der ("lot bulunamadı" değil).
    Arşiv satırları doğrudan yazılır (okutma malzeme türüne bakmaz)."""
    run = started_run(line, planner, depo, filler)
    cases = {
        line.cap: ("38690000000013", "48690000000010"),  # (güncel, eski) koli GTIN'i
        line.finished: ("18690000000019", "28690000000016"),
    }
    for material, (current, old) in cases.items():
        conversion = MaterialUnitConversion.objects.create(
            material=material, unit=unit("KOLI"), factor_to_base=D("12"), gtin=current
        )
        RetiredGtin.objects.create(
            conversion=conversion, gtin=old, factor_to_base=D("6"), replaced_by=current
        )
    api = client(filler)
    cap_old, finished_old = cases[line.cap][1], cases[line.finished][1]
    cap = line.lots["cap"].lot_no

    scanned = api.post(url("run-scan", run.pk), {"lot_no": f"(01){cap_old}(10){cap}"})
    assert scanned.status_code == 200, scanned.data
    scrap = {
        "kind": "PACKAGING",
        "reason_code": "DAMAGED_PACKAGING",
        "quantity": "2",
        "lot_no": f"]C101{cap_old}10{cap.lower()}\x1d17281015",
    }
    response = api.post(url("run-scrap", run.pk), scrap, format="json")
    assert response.status_code == 200, response.data
    finished = stocked_lot(
        "24", material=line.finished, location=line.finished_store, source=Lot.Source.FILLING
    )
    wrong = api.post(
        url("run-scan", run.pk), {"lot_no": f"(01){finished_old}(10){finished.lot_no}"}
    )
    assert (wrong.status_code, wrong.data["code"]) == (400, "lot_material_mismatch")
    missing = api.post(url("run-scan", run.pk), {"lot_no": f"(01){cap_old}(10)YOK-1"})
    assert missing.data == {
        "code": "lot_not_found",
        "detail": "Ambalaj için YOK-1 lotu bulunamadı.",
    }
    denied = client(depo).post(url("run-scan", run.pk), {"lot_no": f"(01){cap_old}(10){cap}"})
    assert denied.status_code == 403


def test_run_detail_shows_line_stock(line: Line, planner, depo, filler):
    run = started_run(line, planner, depo, filler)
    response = client(filler).get(url("run-detail", run.pk))
    assert response.status_code == 200
    codes = {row["material_code"] for row in response.data["line_stock"]}
    assert {"SISE-750", "KAPAK-28", "ETIKET-750", "KOLI-12"} <= codes
    assert {row["lot_no"] for row in response.data["bulk_lots"]} == {line.lots["bulk"].lot_no}


def test_spec_create_with_lines(line: Line, planner):
    other = services.copy_spec(planner, line.spec)  # yalnızca kodu tekrar kullanmamak için
    body = {
        "finished_product": line.finished.pk,
        "bulk_product": line.bulk.pk,
        "fill_quantity": "0.75",
        "fill_unit": unit("LT").pk,
        "units_per_case": 12,
        "lines": [{"material": line.bottle.pk, "quantity_per_unit": "1"}],
    }
    response = client(planner).post(url("packaging-spec-list"), body, format="json")
    assert response.status_code == 201, response.data
    assert response.data["version_no"] == other.version_no + 1
