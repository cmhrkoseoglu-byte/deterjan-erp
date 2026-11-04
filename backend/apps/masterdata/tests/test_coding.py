"""Ana veri kodları ve kodlama sistematiği: öneri, biçim, kod kilidi, eski kodlar (arama, içe
aktarma, yönetim paneli) ve etikette kodun kesilmemesi."""

import io

import pytest
from django.contrib import admin as django_admin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import RequestFactory
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics

from apps.core.coding import registry, selectors
from apps.core.coding import services as coding
from apps.core.exceptions import BusinessRuleError
from apps.core.labels import FONT_BOLD, Text, register_fonts
from apps.core.models import AuditLog, CodeHistory, CodeMigrationRun, CodeSequence
from apps.core.services import save_with_audit
from apps.masterdata import importers, labels, services
from apps.masterdata.models import Equipment, Material, MaterialCategory, UnitOfMeasure
from apps.masterdata.tests.factories import (
    LocationFactory,
    MaterialCategoryFactory,
    MaterialFactory,
    unit,
)
from apps.masterdata.tests.test_importers import MATERIAL_HEADERS, xlsx

pytestmark = pytest.mark.django_db

MATERIAL = "masterdata.material"


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def planner(make_user):
    return make_user("planlama")


def activate(actor, key=MATERIAL):
    coding.update_scheme(actor, key, is_active=True, note="Biçim etkinleştirildi")


def material_data(**extra):
    return {
        "name": "LABSA",
        "material_type": Material.Type.RAW,
        "base_unit": unit("KG"),
        **extra,
    }


def test_registered_types_follow_live_conventions():
    master = {item.key: item for item in registry.code_types(registry.MASTER)}
    expected = {
        "masterdata.material": ("MLZ", 7),
        "masterdata.materialcategory": ("KAT", 4),
        "masterdata.warehouse": ("DEPO", 5),
        "masterdata.location": ("LOKASYON", 4),
        "masterdata.supplier": ("TED", 6),
        "masterdata.customer": ("MUS", 6),
        "masterdata.printer": ("YAZICI", 3),
        "recipes.recipe": ("REC", 7),
    }
    for key, (prefix, width) in expected.items():
        assert (master[key].default_prefix, master[key].default_width) == (prefix, width), key
    equipment = master["masterdata.equipment"]
    assert equipment.default_type_prefixes["MIXING_TANK"] == "TANK"
    assert equipment.default_type_prefixes["FILLING_LINE"] == "DOLUM"
    assert master["quality.testdefinition"].free
    standard = {item.key for item in registry.code_types(registry.STANDARD)}
    assert standard == {"masterdata.unitofmeasure", "hse.hazardstatement"}


def test_code_is_free_until_scheme_is_active(planner):
    created = services.create_record(planner, Material, material_data(code="serbest-1"))
    assert created.code == "SERBEST-1"
    with pytest.raises(ValidationError):  # biçim kapalıyken kod zorunlu
        services.create_record(planner, Material, material_data(code=""))


def test_active_scheme_suggests_and_enforces_format(admin, planner):
    MaterialFactory(code="MLZ-0000024")
    activate(admin)
    item = registry.get_code_type(MATERIAL)
    assert selectors.suggest_code(item) == "MLZ-0000025"
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(planner, Material, material_data(code="HM-1"))
    assert exc.value.code == "code_format"
    created = services.create_record(planner, Material, material_data(code="mlz-0000025"))
    assert created.code == "MLZ-0000025"
    assert CodeSequence.objects.get(key=MATERIAL, stem="MLZ-").last_number == 25
    assert selectors.suggest_code(item) == "MLZ-0000026"


def test_empty_code_gets_next_code_when_active(admin, planner):
    activate(admin)
    first = services.create_record(planner, Material, material_data(code=""))
    second = services.create_record(planner, Material, material_data(code="", name="SLES"))
    assert (first.code, second.code) == ("MLZ-0000001", "MLZ-0000002")


def test_existing_nonconforming_record_can_still_be_edited(admin, planner):
    legacy = MaterialFactory(code="ESKI-KOD")
    activate(admin)
    updated = services.update_record(planner, legacy, {"name": "Yeni ad"})
    assert (updated.code, updated.name) == ("ESKI-KOD", "Yeni ad")


def test_only_admin_changes_code_and_old_code_is_kept(admin, planner):
    material = MaterialFactory(code="MLZ-0000001")
    with pytest.raises(PermissionDenied):
        services.update_record(planner, material, {"code": "MLZ-0000009"})
    # Aynı kod (büyük/küçük harf farkı) değişiklik sayılmaz.
    services.update_record(planner, material, {"name": "Yeni ad", "code": "mlz-0000001"})
    updated = services.update_record(admin, material, {"code": "MLZ-0000009"})
    assert updated.code == "MLZ-0000009"
    history = CodeHistory.objects.get(object_id=material.pk)
    assert (history.code, history.reason, history.created_by) == ("MLZ-0000001", "change", admin)
    # Kullanılmış kod başka kayda verilmez; kayıt kendi eski koduna dönebilir.
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(planner, Material, material_data(code="MLZ-0000001"))
    assert exc.value.code == "code_reserved"
    back = services.update_record(admin, updated, {"code": "MLZ-0000001"})
    assert back.code == "MLZ-0000001"
    assert selectors.former_codes(back) == ["MLZ-0000009"]


def test_reserved_code_is_rechecked_when_the_code_is_claimed(admin, planner, monkeypatch):
    """Yeni kaydın eski kod denetiminden sonra öteki kayıt kodu bırakırsa (eşzamanlı kod
    değişikliği) kod, kaydetme sırasındaki denetimle yine verilmez."""
    holder = MaterialFactory(code="MLZ-0000001")
    original = coding.check_master_code

    def check_then_release(item, instance, *, previous_code):
        original(item, instance, previous_code=previous_code)
        if instance.pk is None:
            Material.objects.filter(pk=holder.pk).update(code="MLZ-0000009")
            holder.refresh_from_db()
            coding.record_code_change(admin, item, holder, "MLZ-0000001")

    monkeypatch.setattr(coding, "check_master_code", check_then_release)
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(planner, Material, material_data(code="MLZ-0000001"))
    assert exc.value.code == "code_reserved"
    assert Material.objects.count() == 1


def test_recode_record_rules(admin):
    """Kod göçü kancası: kodu değiştirir, günlüğe ve eski kod geçmişine yazar; başka kaydın
    güncel ya da eski kodunu vermez; kayıt kendi eski koduna dönebilir."""
    first = MaterialFactory(code="ESKI-1")
    second = MaterialFactory(code="MLZ-0000002")
    run = CodeMigrationRun.objects.create(
        key=MATERIAL, kind=CodeMigrationRun.Kind.APPLY, mapping=[], note="Göç", created_by=admin
    )
    recoded = services.recode_record(admin, first, "mlz-0000001", "Kod göçü", run.pk, "migration")
    assert recoded.code == "MLZ-0000001"
    log = AuditLog.objects.get(
        content_type=ContentType.objects.get_for_model(Material),
        object_id=first.pk,
        action=AuditLog.Action.UPDATE,
    )
    assert (log.changes, log.note) == ({"code": ["ESKI-1", "MLZ-0000001"]}, "Kod göçü")
    history = CodeHistory.objects.get(object_id=first.pk)
    assert (history.code, history.reason, history.run_id, history.created_by) == (
        "ESKI-1",
        "migration",
        run.pk,
        admin,
    )
    for taken in ("MLZ-0000001", "ESKI-1"):  # güncel kod, eski kod
        with pytest.raises(BusinessRuleError) as exc:
            services.recode_record(admin, second, taken, "Not")
        assert exc.value.code == "recode_conflict"
    second.refresh_from_db()
    assert second.code == "MLZ-0000002"
    assert not CodeHistory.objects.filter(object_id=second.pk).exists()
    back = services.recode_record(admin, first, "ESKI-1", "Geri", None, "revert")
    assert back.code == "ESKI-1"
    assert CodeHistory.objects.filter(
        object_id=first.pk, code="MLZ-0000001", reason="revert"
    ).exists()
    with pytest.raises(ValueError):  # standart kod (birim) göçe girmez
        services.recode_record(admin, unit("KG"), "KGM", "Not")


def test_backfill_reserves_codes_changed_before_the_feature(admin, planner, client_for):
    """Sistematikten önce kodu değişen kaydın eski kodu yalnızca denetim günlüğündeydi;
    `backfill_code_history` ile başka kayda verilmez ve eski koduyla bulunur."""
    material = MaterialFactory(code="ESKI-1")
    material.code = "MLZ-0000001"
    save_with_audit(material, planner)  # önceki sürümde kod değişikliği yalnız günlüğe yazılırdı
    assert selectors.find_by_code(Material, "ESKI-1") == (None, False)
    call_command("backfill_code_history", stdout=io.StringIO())
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(planner, Material, material_data(code="ESKI-1"))
    assert exc.value.code == "code_reserved"
    assert selectors.find_by_code(Material, "ESKI-1") == (material, True)
    body = client_for("planlama").get("/api/v1/masterdata/materials/", {"search": "eski"}).json()
    assert [(row["code"], row["former_codes"]) for row in body["results"]] == [
        ("MLZ-0000001", ["ESKI-1"])
    ]


def test_equipment_code_prefix_follows_type(admin, planner):
    activate(admin, "masterdata.equipment")
    item = registry.get_code_type("masterdata.equipment")
    assert selectors.suggest_code(item, type_value="FILLING_LINE") == "DOLUM-00001"
    other = services.create_record(
        planner,
        Equipment,
        {"code": "", "name": "Kompresör", "equipment_type": Equipment.Type.OTHER},
    )
    assert other.code == "EKIPMAN-00001"
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(
            planner,
            Equipment,
            {"code": "TANK-00001", "name": "Kantar", "equipment_type": Equipment.Type.SCALE},
        )
    assert exc.value.code == "code_format"


# --- API -------------------------------------------------------------------------------------


def test_api_search_and_former_codes(client_for, admin):
    material = MaterialFactory(code="ESKI-1")
    services.update_record(admin, material, {"code": "MLZ-0000001"})
    MaterialFactory(code="MLZ-0000002")
    client = client_for("planlama")
    body = client.get("/api/v1/masterdata/materials/", {"search": "eski"}).json()
    assert [row["code"] for row in body["results"]] == ["MLZ-0000001"]
    assert body["results"][0]["former_codes"] == ["ESKI-1"]
    detail = client.get(f"/api/v1/masterdata/materials/{material.pk}/").json()
    assert detail["former_codes"] == ["ESKI-1"]
    # Arama güncel kodda ve adda çalışmaya devam eder.
    assert client.get("/api/v1/masterdata/materials/", {"search": "0000002"}).json()["count"] == 1


def test_api_code_change_requires_admin(client_for):
    material = MaterialFactory(code="MLZ-0000001")
    url = f"/api/v1/masterdata/materials/{material.pk}/"
    denied = client_for("planlama").patch(url, {"code": "MLZ-0000002"}, format="json")
    assert denied.status_code == 403
    assert denied.json() == {"code": "permission_denied", "detail": coding.CODE_LOCK_MESSAGE}
    allowed = client_for("admin").patch(url, {"code": "MLZ-0000002"}, format="json")
    assert allowed.status_code == 200 and allowed.json()["former_codes"] == ["MLZ-0000001"]


def test_api_suggestion_for_material(client_for, admin):
    activate(admin)
    body = client_for("planlama").get(f"/api/v1/coding/suggest/{MATERIAL}/").json()
    assert body == {"key": MATERIAL, "active": True, "code": "MLZ-0000001", "format": "MLZ-0000000"}
    assert client_for("depo").get(f"/api/v1/coding/suggest/{MATERIAL}/").status_code == 403


# --- içe aktarma -----------------------------------------------------------------------------


def test_import_matches_former_code_and_updates(admin, planner):
    material = MaterialFactory(code="ESKI-1", name="Eski ad")
    services.update_record(admin, material, {"code": "MLZ-0000001"})
    upload = xlsx([MATERIAL_HEADERS, ["eski-1", "Yeni ad", "Hammadde", "KG", None, None]])
    report = importers.run_import(planner, "materials", upload, "m.xlsx").as_dict()
    assert report["rows"][0]["code"] == "ESKI-1 → MLZ-0000001"
    assert report["rows"][0]["action"] == "update"
    assert list(Material.objects.values_list("code", "name")) == [("MLZ-0000001", "Yeni ad")]


def test_import_assigns_codes_to_empty_rows_when_active(admin, planner):
    MaterialFactory(code="MLZ-0000024")
    activate(admin)
    rows = [
        MATERIAL_HEADERS,
        [None, "A", "Hammadde", "KG", None, None],
        [None, "B", "Hammadde", "KG", None, None],
    ]
    preview = importers.preview_import("materials", xlsx(rows), "m.xlsx").as_dict()
    assert [row["code"] for row in preview["rows"]] == [
        "MLZ-0000025 (otomatik)",
        "MLZ-0000026 (otomatik)",
    ]
    assert preview["invalid"] == 0
    importers.run_import(planner, "materials", xlsx(rows), "m.xlsx")
    codes = dict(Material.objects.filter(name__in=["A", "B"]).values_list("name", "code"))
    assert codes == {"A": "MLZ-0000025", "B": "MLZ-0000026"}


def test_import_empty_code_rejected_when_inactive():
    upload = xlsx([MATERIAL_HEADERS, [None, "A", "Hammadde", "KG", None, None]])
    report = importers.preview_import("materials", upload, "m.xlsx").as_dict()
    assert report["invalid"] == 1
    assert report["rows"][0]["errors"][0]["message"] == "Zorunlu alan boş."


def test_code_lookup_accepts_former_code(admin):
    category = MaterialCategoryFactory(code="YA")
    services.update_record(admin, category, {"code": "KAT-0001"})
    parse = importers.code_lookup_parser(MaterialCategory, "Kategori")
    assert parse("ya") == category
    assert parse("KAT-0001") == category


# --- yönetim paneli ve etiket -----------------------------------------------------------------


def test_admin_panel_cannot_add_or_recode_coded_types(admin):
    request = RequestFactory().get("/")
    request.user = admin
    material_admin = django_admin.site._registry[Material]
    assert not material_admin.has_add_permission(request)
    assert "code" in material_admin.get_readonly_fields(request, MaterialFactory())
    unit_admin = django_admin.site._registry[UnitOfMeasure]
    assert "code" not in unit_admin.get_readonly_fields(request, unit("KG"))


def test_location_label_code_shrinks_instead_of_being_cut():
    register_fonts()
    location = LocationFactory(code="LOKASYON-0001")
    label = labels.location_label(location)
    text = next(e for e in label.elements if isinstance(e, Text) and e.text == location.code)
    assert text.size < 30
    assert pdfmetrics.stringWidth(text.text, FONT_BOLD, text.size) <= labels.INNER * mm
    short = LocationFactory(code="A-01")
    label = labels.location_label(short)
    assert next(e for e in label.elements if isinstance(e, Text) and e.text == "A-01").size == 30
