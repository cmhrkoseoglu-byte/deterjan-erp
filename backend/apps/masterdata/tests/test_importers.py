import io
from decimal import Decimal

import pytest
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from apps.core.coding import formats, registry, selectors
from apps.core.coding import services as coding
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, CodeSequence
from apps.masterdata import importers, services
from apps.masterdata.models import Location, Material, Supplier
from apps.masterdata.tests.factories import (
    LocationFactory,
    MaterialCategoryFactory,
    MaterialFactory,
    WarehouseFactory,
    unit,
)

pytestmark = pytest.mark.django_db

MATERIAL_HEADERS = ["Kod", "Ad", "Tür", "Temel birim", "Kategori kodu", "Yoğunluk (g/ml)"]


def xlsx(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer


def csv_file(text, encoding="utf-8"):
    return io.BytesIO(text.encode(encoding))


def test_preview_reports_row_errors_and_writes_nothing():
    MaterialCategoryFactory(code="YA")
    upload = xlsx(
        [
            MATERIAL_HEADERS,
            ["hm-las", "LAS", "Hammadde", "kg", "ya", "1,05"],
            ["HM-X", "", "Bilinmeyen", "KG", None, "abc"],
            [None, None, None, None, None, None],  # boş satır atlanır
            ["HM-LAS", "Tekrar", "RAW", "KG", None, None],
        ]
    )

    report = importers.preview_import("materials", upload, "malzeme.xlsx").as_dict()

    assert Material.objects.count() == 0
    assert report["total"] == 3
    assert report["valid"] == 1
    assert report["invalid"] == 2
    first, second, third = report["rows"]
    assert first == {"row": 2, "code": "HM-LAS", "action": "create", "errors": []}
    columns = {error["column"] for error in second["errors"]}
    assert {"Ad", "Tür", "Yoğunluk (g/ml)"} <= columns
    assert third["row"] == 5
    assert "tekrar" in third["errors"][0]["message"]


def test_run_import_creates_and_updates_with_audit(make_user):
    user = make_user("planlama")
    existing = MaterialFactory(code="HM-SLES", name="Eski", density=Decimal("1.0300"))
    upload = xlsx(
        [
            MATERIAL_HEADERS,
            ["HM-SLES", "SLES %70", "Hammadde", "KG", None, None],
            ["AMB-SISE", "Şişe 1L", "Ambalaj", "ADET", None, None],
        ]
    )

    report = importers.run_import(user, "materials", upload, "m.xlsx").as_dict()

    assert (report["to_create"], report["to_update"]) == (1, 1)
    existing.refresh_from_db()
    assert existing.name == "SLES %70"
    assert existing.density == Decimal("1.0300")  # boş hücre mevcut değeri değiştirmez
    bottle = Material.objects.get(code="AMB-SISE")
    assert bottle.material_type == Material.Type.PACKAGING
    assert bottle.base_unit == unit("ADET")
    assert AuditLog.objects.filter(note="Excel içe aktarma").count() == 2


def test_run_import_with_errors_writes_nothing(make_user):
    upload = xlsx(
        [MATERIAL_HEADERS, ["OK1", "Tamam", "RAW", "KG", None, None], ["BAD", "x", "RAW", "YOK"]]
    )

    with pytest.raises(importers.ImportHasErrors) as exc:
        importers.run_import(make_user("planlama"), "materials", upload, "m.xlsx")

    assert exc.value.code == "import_has_errors"
    assert exc.value.report.as_dict()["invalid"] == 1
    assert Material.objects.count() == 0


def test_business_rule_errors_are_reported_per_row():
    MaterialFactory(code="HM-1", base_unit=unit("KG"))
    from apps.recipes.tests.factories import RecipeLineFactory

    RecipeLineFactory(material=Material.objects.get(code="HM-1"))
    upload = xlsx([MATERIAL_HEADERS, ["HM-1", "x", "RAW", "LT", None, None]])

    report = importers.preview_import("materials", upload, "m.xlsx").as_dict()

    error = report["rows"][0]["errors"][0]
    assert "temel birimi değiştirilemez" in error["message"]
    assert error["column"] == ""  # kodla ilgisiz kural satırın genelinde


def test_missing_required_column_is_a_file_error():
    upload = xlsx([["Kod", "Ad"], ["X", "Y"]])

    report = importers.preview_import("materials", upload, "m.xlsx").as_dict()

    assert report["file_errors"] == ["“Tür” sütunu bulunamadı.", "“Temel birim” sütunu bulunamadı."]


def test_csv_with_semicolon_and_turkish_encoding(make_user):
    text = "Kod;Ünvan;Vergi no;E-posta\nt001;Örnek Kimya A.Ş.;1234567890;satis@ornek.com\n"

    importers.run_import(make_user("planlama"), "suppliers", csv_file(text, "cp1254"), "t.csv")

    supplier = Supplier.objects.get()
    assert supplier.code == "T001"
    assert supplier.name == "Örnek Kimya A.Ş."


def test_invalid_email_is_reported():
    text = "Kod,Ünvan,E-posta\nM1,Müşteri,gecersiz\n"

    report = importers.preview_import("customers", csv_file(text), "m.csv").as_dict()

    assert report["rows"][0]["errors"][0]["column"] == "E-posta"


def test_unknown_file_type_and_kind_are_rejected():
    with pytest.raises(BusinessRuleError) as exc:
        importers.preview_import("materials", io.BytesIO(b"x"), "m.pdf")
    assert exc.value.code == "import_file_type"

    with pytest.raises(BusinessRuleError) as exc:
        importers.preview_import("lots", io.BytesIO(b"x"), "m.csv")
    assert exc.value.code == "unknown_import_kind"


def test_corrupt_xlsx_is_rejected():
    with pytest.raises(BusinessRuleError) as exc:
        importers.preview_import("materials", io.BytesIO(b"not a zip"), "m.xlsx")
    assert exc.value.code == "import_file_invalid"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.234,5", Decimal("1234.5")), ("1,05", Decimal("1.05")), (2.5, Decimal("2.5")), (7, 7)],
)
def test_parse_decimal(value, expected):
    assert importers.parse_decimal(value) == expected


@pytest.mark.parametrize(("value", "expected"), [("Evet", True), ("HAYIR", False), ("1", True)])
def test_parse_bool(value, expected):
    assert importers.parse_bool(value) is expected


@pytest.mark.parametrize("kind", ["materials", "suppliers", "customers"])
def test_template_round_trip_is_valid(kind, make_user):
    """İndirilen şablon (örnek satırıyla) olduğu gibi önizlemeden hatasız geçer."""
    template = importers.build_template(kind)
    workbook = load_workbook(io.BytesIO(template))
    assert workbook.sheetnames[1] == "Açıklama"

    report = importers.preview_import(kind, io.BytesIO(template), "sablon.xlsx").as_dict()

    assert report["file_errors"] == []
    assert report["invalid"] == 0, report["rows"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Hammadde", "RAW"), ("raw", "RAW"), ("Yarı mamul", "BULK"), ("DÖKME", "BULK")],
)
def test_material_type_accepts_codes_labels_and_aliases(value, expected):
    parse = importers.SPECS["materials"].columns[2].parse

    assert parse(value) == expected


# --- Geçiş (Faz 5, Adım 5.6): depo, lokasyon, ekipman, birim dönüşümü --------------------------


def test_warehouse_location_equipment_import_in_order(make_user):
    from apps.masterdata.models import Equipment, Location, Warehouse

    user = make_user("planlama")
    importers.run_import(
        user, "warehouses", xlsx([["Kod", "Ad"], ["hmd", "Hammadde deposu"]]), "d.xlsx"
    )
    importers.run_import(
        user,
        "locations",
        xlsx(
            [
                ["Kod", "Ad", "Depo kodu", "Tür"],
                ["A-01", "Raf 1", "HMD", "Depolama"],
                ["TANK-01", "Tank yeri", "HMD", "Tank"],
            ]
        ),
        "l.xlsx",
    )
    report = importers.run_import(
        user,
        "equipment",
        xlsx(
            [
                ["Kod", "Ad", "Tür", "Kapasite", "Kapasite birimi", "Lokasyon kodu"],
                ["T-01", "Tank 1", "Karıştırma tankı", "5000", "KG", "TANK-01"],
                ["H-01", "Hat 1", "Dolum hattı", None, None, None],
            ]
        ),
        "e.xlsx",
    ).as_dict()

    assert report["to_create"] == 2
    assert Warehouse.objects.get(code="HMD").name == "Hammadde deposu"
    assert Location.objects.get(code="TANK-01").location_type == Location.Type.TANK
    tank = Equipment.objects.get(code="T-01")
    assert tank.location.code == "TANK-01"
    assert tank.capacity == Decimal("5000")


def test_location_import_rejects_unknown_warehouse_and_tank_without_location():
    report = importers.preview_import(
        "locations",
        xlsx([["Kod", "Ad", "Depo kodu", "Tür"], ["A-01", "Raf", "YOK", "Depolama"]]),
        "l.xlsx",
    ).as_dict()
    assert report["invalid"] == 1
    assert "Depo bulunamadı" in report["rows"][0]["errors"][0]["message"]

    report = importers.preview_import(
        "equipment",
        xlsx([["Kod", "Ad", "Tür"], ["T-09", "Tank", "Karıştırma tankı"]]),
        "e.xlsx",
    ).as_dict()
    assert report["invalid"] == 1
    assert "lokasyon zorunludur" in report["rows"][0]["errors"][0]["message"]


def test_conversion_import_keys_on_material_and_unit(make_user):
    from apps.masterdata.models import MaterialUnitConversion

    user = make_user("planlama")
    MaterialFactory(code="MM-1L", base_unit=unit("ADET"))
    headers = ["Malzeme kodu", "Birim", "Temel birim karşılığı"]

    first = importers.run_import(
        user, "conversions", xlsx([headers, ["MM-1L", "KOLI", 12]]), "c.xlsx"
    ).as_dict()
    second = importers.preview_import(
        "conversions",
        xlsx([headers, ["mm-1l", "koli", 6], ["MM-1L", "KOLI", 8]]),
        "c.xlsx",
    ).as_dict()

    assert first["rows"][0] == {"row": 2, "code": "MM-1L / KOLI", "action": "create", "errors": []}
    assert second["rows"][0]["action"] == "update"
    assert "tekrar" in second["rows"][1]["errors"][0]["message"]
    importers.run_import(user, "conversions", xlsx([headers, ["MM-1L", "KOLI", 6]]), "c.xlsx")
    assert MaterialUnitConversion.objects.get().factor_to_base == Decimal("6")


@pytest.mark.parametrize("kind", ["warehouses", "locations", "equipment", "conversions"])
def test_new_kinds_have_templates(kind):
    workbook = load_workbook(io.BytesIO(importers.build_template(kind)))
    headers = [cell.value for cell in workbook.worksheets[0][1]]
    assert headers == [c.header for c in importers.get_spec(kind).columns]


# --- kodlama sistematiği: boş kod, dosyadaki kodlar, tekrar, şablon örnekleri ----------------


@pytest.fixture
def activate(make_user):
    """`activate("masterdata.material")`: türün biçimini etkinleştirir (admin)."""
    admin = make_user("admin")

    def _activate(key):
        coding.update_scheme(admin, key, is_active=True, note="Biçim etkinleştirildi")

    return _activate


def material_row(code, name):
    return [code, name, "Hammadde", "KG", None, None]


@pytest.mark.parametrize("typed_first", [False, True])
def test_auto_code_skips_codes_typed_in_the_same_file(activate, make_user, typed_first):
    """Boş kodlu satıra dosyada elle yazılmış kod önerilmez ve kaydedilen kod önizlemede
    gösterilendir; satır sırası sonucu değiştirmez."""
    MaterialFactory(code="MLZ-0000024")
    activate("masterdata.material")
    blanks = [material_row(None, "A"), material_row(None, "B")]
    typed = [material_row("mlz-0000025", "C"), material_row("MLZ-0000027", "D")]
    rows = [MATERIAL_HEADERS, *(typed + blanks if typed_first else blanks + typed)]

    preview = importers.preview_import("materials", xlsx(rows), "m.xlsx").as_dict()

    assert preview["invalid"] == 0, preview["rows"]
    assert {row["code"] for row in preview["rows"]} == {
        "MLZ-0000026 (otomatik)",
        "MLZ-0000028 (otomatik)",
        "MLZ-0000025",
        "MLZ-0000027",
    }
    report = importers.run_import(make_user("planlama"), "materials", xlsx(rows), "m.xlsx")
    assert [row["code"] for row in report.as_dict()["rows"]] == [
        row["code"] for row in preview["rows"]
    ]
    saved = Material.objects.filter(name__in=["A", "B", "C", "D"]).values_list("name", "code")
    assert dict(saved) == {
        "A": "MLZ-0000026",
        "B": "MLZ-0000028",
        "C": "MLZ-0000025",
        "D": "MLZ-0000027",
    }


def test_auto_code_skips_long_typed_runs_in_few_lookups(activate, monkeypatch):
    """Elle sıralanmış uzun listede boş satır ilk boş numarayı alır (dosyadaki ve sistemdeki
    kodlar atlanır); ardışık kodlar tek seferde atlanır, her kod için ayrı sorgu yapılmaz."""
    MaterialFactory(code="MLZ-0000024")
    MaterialFactory(code="MLZ-0000075")  # sistemde dolu; sayaç 24'te
    CodeSequence.objects.create(key="masterdata.material", stem="MLZ-", last_number=24)
    activate("masterdata.material")
    numbers = [*range(25, 75), *range(76, 125)]
    typed = [material_row(f"MLZ-{n:07d}", f"M{n}") for n in numbers]
    rows = [MATERIAL_HEADERS, material_row(None, "A"), *typed, material_row(None, "B")]
    lookups = []
    next_free = selectors.next_free

    def counted(*args):
        lookups.append(args)
        return next_free(*args)

    monkeypatch.setattr(selectors, "next_free", counted)

    preview = importers.preview_import("materials", xlsx(rows), "m.xlsx").as_dict()

    assert preview["invalid"] == 0
    codes = [preview["rows"][0]["code"], preview["rows"][-1]["code"]]
    assert codes == ["MLZ-0000125 (otomatik)", "MLZ-0000126 (otomatik)"]
    assert len(lookups) <= 4


def _take_as_current(code):
    MaterialFactory(code=code)  # başka kullanıcı bu kodla kayıt açtı


def _take_as_former(code):
    other = MaterialFactory(code="MLZ-0000099")  # başka kaydın kodu değişti, eski kodu bu oldu
    coding.record_code_change(None, registry.get_code_type("masterdata.material"), other, code)


@pytest.mark.parametrize("take", [_take_as_current, _take_as_former])
def test_write_error_is_reported_on_its_row(activate, make_user, monkeypatch, take):
    """Önizlemedeki kodu bu arada başka kayıt aldıysa aktarma o satırın hatasıyla reddedilir
    (genel "Gönderilen bilgiler geçersiz" hatası değil); hiçbir satır yazılmaz."""
    MaterialFactory(code="MLZ-0000024")
    activate("masterdata.material")
    build = importers._build_report

    def racing_build(spec, upload, filename):
        report = build(spec, upload, filename)
        take(report.rows[1].data["code"])
        return report

    monkeypatch.setattr(importers, "_build_report", racing_build)
    rows = [MATERIAL_HEADERS, material_row(None, "A"), material_row(None, "B")]

    with pytest.raises(importers.ImportHasErrors) as exc:
        importers.run_import(make_user("planlama"), "materials", xlsx(rows), "m.xlsx")

    first, second = exc.value.report.as_dict()["rows"]
    assert first["errors"] == []
    assert [error["column"] for error in second["errors"]] == ["Kod"]
    assert list(Material.objects.values_list("code", flat=True)) == ["MLZ-0000024"]


def test_api_confirm_returns_row_report_for_write_error(activate, client_for, monkeypatch):
    """Yazarken çıkan hata API'de de satır raporuyla döner (`import_has_errors`)."""
    MaterialFactory(code="MLZ-0000024")
    activate("masterdata.material")
    build = importers._build_report

    def racing_build(spec, upload, filename):
        report = build(spec, upload, filename)
        _take_as_current(report.rows[0].data["code"])
        return report

    monkeypatch.setattr(importers, "_build_report", racing_build)
    url = reverse("masterdata:import", args=["materials"])

    def upload():
        file = xlsx([MATERIAL_HEADERS, material_row(None, "A")])
        file.name = "m.xlsx"
        return {"file": file, "confirm": "true"}

    assert client_for("depo").post(url, upload(), format="multipart").status_code == 403
    response = client_for("planlama").post(url, upload(), format="multipart")

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "import_has_errors"
    assert body["report"]["rows"][0]["errors"][0]["column"] == "Kod"
    assert not Material.objects.filter(name="A").exists()


def test_write_rule_error_unrelated_to_code_is_a_row_error(make_user, monkeypatch):
    """Kodla ilgisiz yazma hatası da satıra eklenir (sütunsuz, satırın genelinde)."""

    def fail(*args, **kwargs):
        raise BusinessRuleError("inactive_reference", "Pasif birim seçilemez: KG.")

    monkeypatch.setattr(importers.services, "create_record", fail)
    upload = xlsx([MATERIAL_HEADERS, material_row("HM-A", "A")])

    with pytest.raises(importers.ImportHasErrors) as exc:
        importers.run_import(make_user("planlama"), "materials", upload, "m.xlsx")

    assert exc.value.report.as_dict()["rows"][0]["errors"] == [
        {"column": "", "message": "Pasif birim seçilemez: KG."}
    ]


def test_code_rule_error_is_shown_under_code_column(activate):
    activate("masterdata.material")
    upload = xlsx([MATERIAL_HEADERS, material_row("HM-1", "A")])

    report = importers.preview_import("materials", upload, "m.xlsx").as_dict()

    [error] = report["rows"][0]["errors"]
    assert error["column"] == "Kod"
    assert "biçimine uymuyor" in error["message"]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("code_format", True),
        ("code_reserved", True),
        ("code_taken", True),
        ("code_too_long", True),
        ("code_must_start_with_letter", True),
        ("invalid_characters", True),
        ("duplicate", True),
        ("inactive_reference", False),
        ("recipe_product_not_bulk", False),
        ("tank_location_required", False),
    ],
)
def test_is_code_error_separates_code_rules_from_other_rules(code, expected):
    assert importers.is_code_error(BusinessRuleError(code, "x")) is expected


@pytest.mark.parametrize("former_first", [True, False])
def test_former_and_current_code_of_one_record_is_a_repeat(make_user, former_first):
    """Eski kod da kaydı bulduğundan aynı kaydın eski ve güncel kodlu iki satırı tekrar sayılır;
    kayıt iki kez güncellenmez."""
    material = MaterialFactory(code="ESKI-1", name="Eski ad")
    services.update_record(make_user("admin"), material, {"code": "MLZ-0000001"})
    former, current = material_row("eski-1", "Ad X"), material_row("MLZ-0000001", "Ad Y")
    rows = [MATERIAL_HEADERS, *([former, current] if former_first else [current, former])]

    report = importers.preview_import("materials", xlsx(rows), "m.xlsx").as_dict()

    first, second = report["rows"]
    assert (first["action"], first["errors"]) == ("update", [])
    assert second["errors"] == [
        {"column": "Kod", "message": "Kayıt dosyada tekrar ediyor (satır 2)."}
    ]
    with pytest.raises(importers.ImportHasErrors):
        importers.run_import(make_user("planlama"), "materials", xlsx(rows), "m.xlsx")
    material.refresh_from_db()
    assert material.name == "Eski ad"


def follows_default_format(key, code, type_value=None):
    item = registry.get_code_type(key)
    fmt = selectors.default_format(item)
    prefix = selectors.type_prefix(item, fmt, type_value)
    return prefix is not None and formats.master_number(code, prefix, fmt.width) is not None


@pytest.mark.parametrize(
    ("kind", "header", "key"),
    [
        ("materials", "Kod", "masterdata.material"),
        ("suppliers", "Kod", "masterdata.supplier"),
        ("customers", "Kod", "masterdata.customer"),
        ("warehouses", "Kod", "masterdata.warehouse"),
        ("locations", "Kod", "masterdata.location"),
        ("locations", "Depo kodu", "masterdata.warehouse"),
        ("equipment", "Kod", "masterdata.equipment"),
        ("equipment", "Lokasyon kodu", "masterdata.location"),
        ("conversions", "Malzeme kodu", "masterdata.material"),
    ],
)
def test_template_example_codes_follow_default_formats(kind, header, key):
    """Şablon örnekleri kodlama sistematiğinin varsayılan biçimindedir (MLZ-0000001 gibi)."""
    spec = importers.get_spec(kind)
    example = next(c.example for c in spec.columns if c.header == header)
    # Önek türe göreyse (ekipman) örnek satırın türü: Karıştırma tankı → TANK.
    item = registry.get_code_type(key)
    types = [c.parse(c.example) for c in spec.columns if c.field == item.type_field]

    assert follows_default_format(key, example, types[0] if types else None), example


@pytest.mark.parametrize("kind", ["materials", "suppliers", "customers", "warehouses"])
def test_template_round_trip_is_valid_when_format_is_active(kind, activate):
    """Biçim etkinken de indirilen şablon olduğu gibi önizlemeden hatasız geçer."""
    activate(services.code_type_of(importers.get_spec(kind).model).key)
    template = importers.build_template(kind)

    report = importers.preview_import(kind, io.BytesIO(template), "sablon.xlsx").as_dict()

    assert report["file_errors"] == []
    assert report["invalid"] == 0, report["rows"]


@pytest.mark.parametrize("kind", ["locations", "equipment"])
def test_referencing_template_is_valid_when_example_records_exist(kind, activate):
    """Lokasyon ve ekipman şablonunun örnekleri birbirine uyar: örnek depo (DEPO-00001) ve tank
    lokasyonu (LOKASYON-0002) varken biçim etkin olsa da şablon olduğu gibi geçer."""
    LocationFactory(
        code="LOKASYON-0002",
        location_type=Location.Type.TANK,
        warehouse=WarehouseFactory(code="DEPO-00001"),
    )
    activate(services.code_type_of(importers.get_spec(kind).model).key)
    template = importers.build_template(kind)

    report = importers.preview_import(kind, io.BytesIO(template), "sablon.xlsx").as_dict()

    assert report["file_errors"] == []
    assert report["invalid"] == 0, report["rows"]
    assert report["to_create"] == 1


@pytest.mark.parametrize(
    ("kind", "key", "expected"),
    [
        ("suppliers", "masterdata.supplier", "TED-000001"),
        ("customers", "masterdata.customer", "MUS-000001"),
    ],
)
def test_partner_code_may_be_left_blank_when_active(kind, key, expected, activate, make_user):
    """Tedarikçi ve müşteri şablonu da kodun boş bırakılabileceğini söyler; sistem kodu verir."""
    spec = importers.get_spec(kind)
    assert "boş bırakılabilir" in next(c.help for c in spec.columns if c.field == "code")
    activate(key)
    upload = csv_file("Kod;Ünvan\n;Örnek Kimya A.Ş.\n")

    report = importers.run_import(make_user("planlama"), kind, upload, "t.csv").as_dict()

    assert report["rows"][0]["code"] == f"{expected} (otomatik)"
    assert spec.model._default_manager.get().code == expected
