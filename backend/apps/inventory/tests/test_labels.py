"""Lot, koli ve palet etiketleri; yazıcıya gönderim; barkod okutma çözümü (Adım 2.3)."""

from datetime import date

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import gs1_check_digit
from apps.core.roles import DEPO, DOLUM, LABORATUVAR
from apps.inventory import selectors, services
from apps.inventory.models import Lot, PalletLabel
from apps.inventory.tests.factories import stocked_lot
from apps.masterdata import services as masterdata
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import LocationFactory, MaterialFactory, PrinterFactory, unit

pytestmark = pytest.mark.django_db
LOTS = "/api/v1/inventory/lots/"
PALLETS = "/api/v1/inventory/pallet-labels/"
GTIN = "8690000000012"


def finished(gtin: str = GTIN, **kwargs: object) -> Material:
    return MaterialFactory.create(
        material_type=Material.Type.FINISHED, base_unit=unit("ADET"), gtin=gtin, **kwargs
    )


def finished_lot(gtin: str = GTIN, lot_no: str = "D-261015-001") -> Lot:
    return services.create_lot(
        None,
        material=finished(gtin),
        source=Lot.Source.FILLING,
        lot_no=lot_no,
        manufactured_at=date(2026, 10, 15),
        expiry_date=date(2028, 10, 15),
    )


def enable_sscc() -> None:
    masterdata.update_label_settings(None, {"gs1_company_prefix": "8691234"})  # type: ignore[arg-type]


# --- lot etiketi ---------------------------------------------------------------------------------


def test_lot_label_pdf_a4_zpl(client_for, invariants) -> None:
    lot = stocked_lot()
    client = client_for(LABORATUVAR)
    pdf = client.get(f"{LOTS}{lot.pk}/label/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf["Content-Disposition"] == f'inline; filename="etiket-{lot.lot_no}.pdf"'
    a4 = client.get(f"{LOTS}{lot.pk}/label/", {"output": "a4", "copies": 4})
    assert a4.status_code == 200 and a4.content.startswith(b"%PDF")
    zpl = client.get(f"{LOTS}{lot.pk}/label/", {"output": "zpl", "copies": 2}).content.decode()
    assert zpl.count("^XA") == 2
    assert f"^FDLOT:{lot.lot_no}^FS" in zpl and f"^FDQA,LOT:{lot.lot_no}^FS" in zpl
    assert "^PW799" in zpl and "^LL1199" in zpl  # 100 × 150 mm, 203 dpi (D-8)
    too_many = client.get(f"{LOTS}{lot.pk}/label/", {"copies": 101})
    assert too_many.status_code == 400


def test_lot_label_prints_company_name(client_for) -> None:
    masterdata.update_label_settings(None, {"company_name": "Inncos Kimya"})  # type: ignore[arg-type]
    lot = stocked_lot()
    zpl = client_for(DEPO).get(f"{LOTS}{lot.pk}/label/", {"output": "zpl"}).content.decode()
    assert "^FDInncos Kimya^FS" in zpl


def test_goods_receipt_labels_zpl_and_print(
    client_for, make_user, fake_printer, invariants
) -> None:
    from decimal import Decimal

    from apps.inventory.tests.factories import quarantine_location, storage_location
    from apps.masterdata.tests.factories import SupplierFactory

    actor = make_user(DEPO)
    receipt = services.create_goods_receipt(
        actor,
        {
            "supplier": SupplierFactory.create(),
            "receipt_date": date(2026, 10, 15),
            "quarantine_location": quarantine_location(),
            "storage_location": storage_location(),
        },
        [
            {"material": MaterialFactory.create(), "quantity": Decimal("10"), "unit": unit("KG")},
            {"material": MaterialFactory.create(), "quantity": Decimal("5"), "unit": unit("KG")},
        ],
    )
    client = client_for(DEPO)
    printer = PrinterFactory.create(port=fake_printer.port)
    url = f"/api/v1/inventory/goods-receipts/{receipt.pk}/"
    empty = client.post(f"{url}print-labels/", {"printer": printer.pk})
    assert empty.status_code == 400 and empty.json()["code"] == "no_lots"
    services.post_goods_receipt(actor, receipt)
    lot_nos = list(Lot.objects.order_by("id").values_list("lot_no", flat=True))
    zpl = client.get(f"{url}labels/", {"output": "zpl"}).content.decode()
    assert all(f"^FDLOT:{no}^FS" in zpl for no in lot_nos)
    printed = client.post(f"{url}print-labels/", {"printer": printer.pk, "copies": 2})
    assert printed.status_code == 200 and printed.json()["printed"] == 4
    assert fake_printer.text().count("^XA") == 4


# --- koli etiketi (D-6) ---------------------------------------------------------------------


def test_case_label_is_gs1_128_when_material_has_gtin(client_for) -> None:
    lot = finished_lot()
    response = client_for(DOLUM).get(
        f"{LOTS}{lot.pk}/case-label/", {"output": "zpl", "units_per_case": 12}
    )
    assert response.status_code == 200
    zpl = response.content.decode()
    assert "^BCN,200,Y,N,N,D^FD(01)08690000000012(17)281015(10)D-261015-001^FS" in zpl
    assert "^FD12 adet^FS" in zpl
    assert client_for(DOLUM).get(f"{LOTS}{lot.pk}/case-label/").content.startswith(b"%PDF")


def test_case_label_without_gtin_uses_internal_code(client_for) -> None:
    lot = finished_lot(gtin="")
    zpl = client_for(DOLUM).get(f"{LOTS}{lot.pk}/case-label/", {"output": "zpl"}).content.decode()
    assert ",N,N,D^" not in zpl
    assert "^FDLOT:D-261015-001^FS" in zpl


def test_case_label_only_for_finished_goods(client_for) -> None:
    lot = stocked_lot()
    response = client_for(DEPO).get(f"{LOTS}{lot.pk}/case-label/")
    assert response.status_code == 400 and response.json()["code"] == "not_finished_goods"


def test_print_lot_and_case_label_to_printer(client_for, fake_printer) -> None:
    lot = finished_lot()
    printer = PrinterFactory.create(port=fake_printer.port)
    client = client_for(DOLUM)
    printed = client.post(
        f"{LOTS}{lot.pk}/print-label/", {"printer": printer.pk, "kind": "case", "copies": 3}
    )
    assert printed.status_code == 200, printed.content
    assert printed.json() == {"printed": 3, "printer": printer.code}
    zpl = fake_printer.text()
    assert zpl.count("^XA") == 3 and "(01)08690000000012" in zpl
    bad_kind = client.post(f"{LOTS}{lot.pk}/print-label/", {"printer": printer.pk, "kind": "x"})
    assert bad_kind.status_code == 400
    missing = client.post(f"{LOTS}{lot.pk}/print-label/", {"printer": 99999, "kind": "lot"})
    assert missing.status_code == 400 and missing.json()["code"] == "printer_not_found"


# --- palet etiketi (SSCC) ----------------------------------------------------------------------


def test_pallet_label_requires_gs1_prefix(make_user) -> None:
    lot = finished_lot()
    with pytest.raises(BusinessRuleError) as exc:
        services.create_pallet_label(make_user(DEPO), lot, 40)
    assert exc.value.code == "sscc_disabled"


def test_pallet_label_rules(make_user) -> None:
    enable_sscc()
    actor = make_user(DEPO)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_pallet_label(actor, stocked_lot(), 40)
    assert exc.value.code == "not_finished_goods"
    lot = finished_lot()
    with pytest.raises(BusinessRuleError) as exc:
        services.create_pallet_label(actor, lot, 0)
    assert exc.value.code == "invalid_case_count"
    Lot.objects.filter(pk=lot.pk).update(status=Lot.Status.REJECTED)
    lot.refresh_from_db()
    with pytest.raises(BusinessRuleError) as exc:
        services.create_pallet_label(actor, lot, 10)
    assert exc.value.code == "lot_rejected"
    assert not PalletLabel.objects.exists()


def test_pallet_label_api_and_output(client_for, fake_printer) -> None:
    enable_sscc()
    lot = finished_lot()
    assert (
        client_for(LABORATUVAR).post(PALLETS, {"lot": lot.pk, "case_count": 40}).status_code == 403
    )
    client = client_for(DOLUM)
    created = client.post(PALLETS, {"lot": lot.pk, "case_count": 40, "units_per_case": 12})
    assert created.status_code == 201, created.content
    body = created.json()
    sscc = body["sscc"]
    assert (
        len(sscc) == 18 and sscc.startswith("08691234") and gs1_check_digit(sscc[:-1]) == sscc[-1]
    )
    assert body["lot_no"] == lot.lot_no and body["case_count"] == 40

    zpl = client.get(f"{PALLETS}{body['id']}/label/", {"output": "zpl"}).content.decode()
    assert f"^FD(00){sscc}^FS" in zpl
    assert "^FD(02)08690000000012(37)40^FS" in zpl
    assert "^FD(17)281015(10)D-261015-001^FS" in zpl
    assert "^FD480 adet^FS" in zpl
    assert client.get(f"{PALLETS}{body['id']}/label/").content.startswith(b"%PDF")

    printer = PrinterFactory.create(port=fake_printer.port)
    printed = client.post(f"{PALLETS}{body['id']}/print-label/", {"printer": printer.pk})
    assert printed.status_code == 200 and f"(00){sscc}" in fake_printer.text()
    assert client.get(PALLETS, {"lot": lot.pk}).json()["count"] == 1
    # Sıradaki palet yeni SSCC alır.
    second = client.post(PALLETS, {"lot": lot.pk, "case_count": 10}).json()
    assert second["sscc"] != sscc


# --- okutma --------------------------------------------------------------------------------------


def test_scan_prefixes(client_for) -> None:
    lot = stocked_lot()
    location = LocationFactory.create(code="A-01")
    material = lot.material
    client = client_for(DEPO)

    def scan(code: str) -> dict:
        response = client.get("/api/v1/inventory/scan/", {"code": code})
        assert response.status_code == 200, response.content
        return response.json()

    found = scan(f"LOT:{lot.lot_no}")
    assert found["kind"] == "lot" and [x["id"] for x in found["lots"]] == [lot.pk]
    assert found["lots"][0]["material_code"] == material.code
    assert found["material"]["id"] == material.pk
    # Faz 1'de basılmış etiket: öneksiz lot no; küçük harf ve boşluk da çözülür.
    assert scan(f"  {lot.lot_no.lower()} ")["lots"][0]["id"] == lot.pk
    assert scan("LOC:A-01")["location"] == {
        "id": location.pk,
        "code": "A-01",
        "name": location.name,
        "warehouse_code": location.warehouse.code,
    }
    assert scan("a-01")["kind"] == "location"
    assert scan(f"MAT:{material.code}")["material"]["id"] == material.pk
    assert scan(material.code)["kind"] == "material"

    missing = client.get("/api/v1/inventory/scan/", {"code": "LOT:YOK-1"})
    assert missing.status_code == 400 and missing.json()["code"] == "scan_not_found"
    unknown = client.get("/api/v1/inventory/scan/", {"code": "XYZ"})
    assert unknown.status_code == 400 and unknown.json()["code"] == "scan_not_found"
    assert client.get("/api/v1/inventory/scan/", {"code": " "}).status_code == 400


def test_scan_gs1_case_and_pallet() -> None:
    lot = finished_lot()
    other = finished_lot(gtin="96385074", lot_no=lot.lot_no)  # aynı lot no, başka malzeme

    case = selectors.decode_scan("(01)08690000000012(17)281015(10)D-261015-001")
    assert case.kind == "lot" and case.lots == [lot] and case.gs1["17"] == "281015"
    # Okuyucunun gönderdiği ham veri: AIM öneki ]C1, değişken alandan sonra GS (\x1d).
    raw = selectors.decode_scan("]C1010869000000001210D-261015-001\x1d17281015")
    assert raw.lots == [lot]
    # GTIN-8 malzeme, 14 haneye tamamlanmış (01) ile bulunur.
    assert selectors.decode_scan("(01)00000096385074(10)D-261015-001").lots == [other]
    # Yalnız GTIN: malzeme.
    only = selectors.decode_scan("(01)08690000000012")
    assert only.kind == "material" and only.material == lot.material
    # Aynı lot no iki malzemede: öneksiz okutmada ikisi de döner (bileşen beklenen malzemeyi seçer).
    assert {x.pk for x in selectors.decode_scan(lot.lot_no).lots} == {lot.pk, other.pk}

    enable_sscc()
    pallet = services.create_pallet_label(None, lot, 20)  # type: ignore[arg-type]
    found = selectors.decode_scan(f"(00){pallet.sscc}")
    assert found.kind == "pallet" and found.pallet == pallet and found.lots == [lot]
    assert selectors.decode_scan(f"]C100{pallet.sscc}").pallet == pallet
    with pytest.raises(BusinessRuleError):
        selectors.decode_scan("(00)086912340000099999")
    with pytest.raises(BusinessRuleError):
        selectors.decode_scan("(01)08690000000029(10)X")


def test_parse_gs1_rejects_malformed() -> None:
    assert selectors.parse_gs1("(01)123") == {}
    assert selectors.parse_gs1("99ABC") == {}
    assert selectors.parse_gs1("(01)08690000000012(10)A1") == {"01": "08690000000012", "10": "A1"}


def test_scan_requires_login(api_client) -> None:
    assert api_client.get("/api/v1/inventory/scan/", {"code": "X"}).status_code == 401
