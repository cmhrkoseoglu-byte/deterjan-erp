"""GTIN, yazıcılar, etiket ayarları, SSCC ve lokasyon etiketi (Adım 2.3)."""

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.labels import NO_BARCODE_QR, Barcode, QRCode, Text, gs1_check_digit, render_zpl
from apps.core.models import AuditLog
from apps.core.roles import ADMIN, DEPO, PLANLAMA
from apps.masterdata import labels, services
from apps.masterdata.models import Material, Printer
from apps.masterdata.tests.factories import LocationFactory, MaterialFactory, PrinterFactory, unit

pytestmark = pytest.mark.django_db


def test_material_gtin_is_validated_and_unique(make_user) -> None:
    actor = make_user(PLANLAMA)
    data = {
        "code": "MM-1",
        "name": "Bulaşık deterjanı 750 ml",
        "material_type": Material.Type.FINISHED,
        "base_unit": unit("ADET"),
    }
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(actor, Material, {**data, "gtin": "8690000000013"})
    assert exc.value.code == "invalid_gtin"
    material = services.create_record(actor, Material, {**data, "gtin": " 8690000000012 "})
    assert material.gtin == "8690000000012"
    # Boş GTIN birden çok malzemede olabilir; dolu GTIN benzersiz (14 haneli normal biçimde).
    MaterialFactory.create()
    MaterialFactory.create()
    for duplicate in ("8690000000012", "08690000000012"):
        with pytest.raises(BusinessRuleError) as dup:
            services.create_record(actor, Material, {**data, "code": "MM-2", "gtin": duplicate})
        assert dup.value.code == "gtin_taken"
        assert "Bu GTIN başka bir malzemede ya da koli dönüşümünde kayıtlı" in dup.value.message


def test_material_api_exposes_gtin(client_for) -> None:
    client = client_for(PLANLAMA)
    response = client.post(
        "/api/v1/masterdata/materials/",
        {
            "code": "mm-3",
            "name": "Yumuşatıcı",
            "material_type": "FINISHED",
            "base_unit": unit("ADET").pk,
            "gtin": "96385074",
        },
    )
    assert response.status_code == 201, response.content
    assert response.json()["gtin"] == "96385074"
    bad = client.patch(f"/api/v1/masterdata/materials/{response.json()['id']}/", {"gtin": "123"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_gtin"


def test_printer_crud_is_admin_only(client_for) -> None:
    payload = {"code": "zebra-1", "name": "Dolum hattı Zebra", "host": "192.168.1.50"}
    assert client_for(PLANLAMA).post("/api/v1/masterdata/printers/", payload).status_code == 403
    admin = client_for(ADMIN)
    created = admin.post("/api/v1/masterdata/printers/", payload)
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["code"] == "ZEBRA-1" and body["port"] == 9100 and body["dpi"] == 203
    assert body["printer_type"] == "ZPL" and body["printer_type_display"] == "Zebra (ZPL)"
    assert client_for(DEPO).get("/api/v1/masterdata/printers/").status_code == 200
    bad = admin.patch(f"/api/v1/masterdata/printers/{body['id']}/", {"host": "a b"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_host"
    bad_dpi = admin.patch(f"/api/v1/masterdata/printers/{body['id']}/", {"dpi": 250})
    assert bad_dpi.status_code == 400


def test_printer_test_label_is_sent_over_tcp(client_for, fake_printer) -> None:
    printer = PrinterFactory.create(port=fake_printer.port)
    response = client_for(DEPO).post(f"/api/v1/masterdata/printers/{printer.pk}/test/")
    assert response.status_code == 200, response.content
    assert response.json() == {"printed": 1, "printer": printer.code}
    zpl = fake_printer.text()
    assert zpl.startswith("^XA") and "Deneme etiketi" in zpl and "ĞÜŞİÖÇ" in zpl
    log = AuditLog.objects.filter(object_id=printer.pk, action=AuditLog.Action.CUSTOM).get()
    assert log.note.startswith(f"Etiket yazdırıldı: {printer.code}")


def test_unreachable_or_inactive_printer(make_user, settings) -> None:
    settings.PRINTER_TIMEOUT_SECONDS = 0.5
    actor = make_user(DEPO)
    # Kapalı port: bağlantı reddedilir.
    printer = PrinterFactory.create(port=1)
    with pytest.raises(BusinessRuleError) as exc:
        services.send_to_printer(actor, printer, "^XA^XZ")
    assert exc.value.code == "printer_unreachable"
    printer.is_active = False
    with pytest.raises(BusinessRuleError) as exc:
        services.send_to_printer(actor, printer, "^XA^XZ")
    assert exc.value.code == "inactive"


def test_label_settings_and_sscc(client_for, make_user) -> None:
    url = "/api/v1/masterdata/label-settings/"
    reader = client_for(DEPO)
    initial = reader.get(url).json()
    assert initial["sscc_enabled"] is False and initial["gs1_company_prefix"] == ""
    assert reader.put(url, {"company_name": "X"}).status_code == 403

    with pytest.raises(BusinessRuleError) as exc:
        services.next_sscc(None)
    assert exc.value.code == "sscc_disabled"

    admin = client_for(ADMIN)
    # GS1 alanları burada salt okunurdur (Sistem > Kodlama sistematiği > GS1): yok sayılır.
    ignored = admin.put(url, {"gs1_company_prefix": "8691234", "company_name": "Inncos Kimya"})
    assert ignored.status_code == 200
    assert ignored.json()["company_name"] == "Inncos Kimya"
    assert ignored.json()["sscc_enabled"] is False and ignored.json()["gs1_company_prefix"] == ""
    gs1 = admin.patch(
        "/api/v1/masterdata/gs1-settings/",
        {"company_prefix": "8691234", "note": "GS1 üyeliği"},
        format="json",
    )
    assert gs1.status_code == 200, gs1.json()
    assert reader.get(url).json()["sscc_enabled"] is True

    first, second = services.next_sscc(None), services.next_sscc(None)
    assert first == "0" + "8691234" + "000000001" + gs1_check_digit("08691234000000001")
    assert len(first) == 18 and second[:-1].endswith("2")
    assert gs1_check_digit(second[:-1]) == second[-1]
    assert reader.get(url).json()["next_sscc_serial"] == 3


def test_location_label_pdf_zpl_and_print(client_for, fake_printer) -> None:
    location = LocationFactory.create(code="A-01-02", name="Raf A1")
    client = client_for(DEPO)
    pdf = client.get(f"/api/v1/masterdata/locations/{location.pk}/label/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    zpl = client.get(f"/api/v1/masterdata/locations/{location.pk}/label/", {"output": "zpl"})
    assert zpl["Content-Disposition"] == 'attachment; filename="lokasyon-A-01-02.zpl"'
    assert "^FDLOC:A-01-02^FS" in zpl.content.decode()
    assert (
        client.get(
            f"/api/v1/masterdata/locations/{location.pk}/label/", {"output": "xls"}
        ).status_code
        == 400
    )

    printer = PrinterFactory.create(port=fake_printer.port)
    printed = client.post(
        f"/api/v1/masterdata/locations/{location.pk}/print-label/",
        {"printer": printer.pk, "copies": 2},
    )
    assert printed.status_code == 200 and printed.json()["printed"] == 2
    assert fake_printer.text().count("^XA") == 2
    inactive = PrinterFactory.create(is_active=False)
    denied = client.post(
        f"/api/v1/masterdata/locations/{location.pk}/print-label/", {"printer": inactive.pk}
    )
    assert denied.status_code == 400 and denied.json()["code"] == "inactive"
    assert Printer.objects.count() == 2


def test_location_code_with_turkish_letters_gets_no_code128(client_for) -> None:
    """Code128 Türkçe harfi taşımaz (reportlab sessizce atar: LOC:RAF-Ş1 → LOC:RAF-1, başka
    lokasyon okutulurdu; kodlama sistematiği kapalıyken kod serbest yazılır). Böyle kodda Code128
    basılmaz; QR aynen kalır, barkodun yerinde QR'ın okutulacağı yazılır."""
    location = LocationFactory.create(code="RAF-Ş1")
    label = labels.location_label(location)
    assert not [element for element in label.elements if isinstance(element, Barcode)]
    notes = [e for e in label.elements if isinstance(e, Text) and e.text == NO_BARCODE_QR]
    assert len(notes) == 1 and notes[0].bold
    assert [e.data for e in label.elements if isinstance(e, QRCode)] == ["LOC:RAF-Ş1"]
    assert "^BC" not in render_zpl([label])
    zpl = client_for(DEPO).get(
        f"/api/v1/masterdata/locations/{location.pk}/label/", {"output": "zpl"}
    )
    text = zpl.content.decode()
    assert "^BC" not in text and "^FDQA,LOC:RAF-Ş1^FS" in text and NO_BARCODE_QR in text

    # ASCII kodda Code128 aynen basılır.
    plain = labels.location_label(LocationFactory.create(code="RAF-S1"))
    assert [e.data for e in plain.elements if isinstance(e, Barcode)] == ["LOC:RAF-S1"]
    assert NO_BARCODE_QR not in [e.text for e in plain.elements if isinstance(e, Text)]


def test_location_code_with_a_greater_than_sign_gets_no_code128(client_for) -> None:
    """ZPL `^BC`'de ">" kip (invocation) önekidir (Zebra tablosunda "><" = "^"): LOC:RAF>1 yazıcıda
    başka kod olurdu. Böyle kodda da Code128 basılmaz; QR aynen kalır, yerinde QR'ın okutulacağı
    yazılır."""
    location = LocationFactory.create(code="RAF>1")
    label = labels.location_label(location)
    assert not [element for element in label.elements if isinstance(element, Barcode)]
    assert NO_BARCODE_QR in [e.text for e in label.elements if isinstance(e, Text)]
    assert [e.data for e in label.elements if isinstance(e, QRCode)] == ["LOC:RAF>1"]
    zpl = client_for(DEPO).get(
        f"/api/v1/masterdata/locations/{location.pk}/label/", {"output": "zpl"}
    )
    text = zpl.content.decode()
    assert "^BC" not in text and "^FDQA,LOC:RAF>1^FS" in text and NO_BARCODE_QR in text
