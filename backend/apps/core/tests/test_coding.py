"""Kodlama motoru: biçimler, kayıt, biçim değiştirme, öneri, kod alma, eski kodlar, API."""

import datetime
import threading

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, connection, transaction
from django.utils import timezone

from apps.core.coding import formats, registry, selectors, services
from apps.core.coding.formats import Format
from apps.core.exceptions import BusinessRuleError
from apps.core.models import (
    AuditLog,
    CodeHistory,
    CodeScheme,
    CodeSchemeRevision,
    CodeSequence,
    DocumentSequence,
)
from apps.core.roles import ADMIN, DEPO, PLANLAMA
from apps.core.tests.testapp.apps import TEST_LOT_COUNTERS
from apps.core.tests.testapp.models import TypedWidget, Widget

WIDGET = "core_testapp.widget"
TYPED = "core_testapp.typedwidget"


def widget_type() -> registry.CodeType:
    return registry.get_code_type(WIDGET)


def typed_type() -> registry.CodeType:
    return registry.get_code_type(TYPED)


@pytest.fixture
def admin(make_user):
    return make_user(ADMIN)


def activate(actor, key=WIDGET, **values):
    return services.update_scheme(actor, key, is_active=True, note="Etkinleştirildi", **values)


# --- biçimler --------------------------------------------------------------------------------


def test_master_code_and_number():
    assert formats.master_code("MLZ", 7, 24) == "MLZ-0000024"
    assert formats.master_number("MLZ-0000024", "MLZ", 7) == 24
    # Sıra hanesini aşan numara bir hane uzar; uzun biçimde ilk hane sıfır olamaz.
    assert formats.master_code("MLZ", 7, 10_000_000) == "MLZ-10000000"
    assert formats.master_number("MLZ-10000000", "MLZ", 7) == 10_000_000
    assert formats.master_number("MLZ-00000024", "MLZ", 7) is None
    assert formats.master_number("MLZ-024", "MLZ", 7) is None
    assert formats.master_number("MLZX-0000024", "MLZ", 7) is None
    assert formats.loose_number("MLZ-24", "MLZ") == 24
    assert formats.loose_number("MLZ-A1", "MLZ") is None
    # Yalnız ASCII rakam sıra no sayılır (biçim kapalıyken serbest kodlar sayacı bozmasın).
    assert formats.loose_number("MLZ-²", "MLZ") is None
    assert formats.loose_number("MLZ-٠٠٠٠٠٠١", "MLZ") is None
    assert formats.master_number("MLZ-٠٠٠٠٠٠١", "MLZ", 7) is None


def test_document_and_lot_numbers():
    day = datetime.date(2026, 11, 4)
    assert formats.document_number(Format("document", "UE", 5), 2026, 1) == "UE-2026-00001"
    assert formats.document_number(Format("document", "UE", 4, year_format="YY"), 2026, 7) == (
        "UE-26-0007"
    )
    assert formats.lot_number(Format("lot", "H", 3), day, 1) == "H-20261104-001"
    assert formats.lot_number(Format("lot", "H", 3, date_format="YYYYDDD"), day, 2) == (
        "H-2026308-002"
    )
    assert formats.lot_number(Format("lot", "H", 4, date_format="YYMMDD"), day, 3) == (
        "H-261104-0003"
    )


@pytest.mark.parametrize(
    ("code", "scanned", "underscore", "expected"),
    [
        ("MLZ-0000001", True, False, None),
        ("AKTIF_MADDE", False, True, None),
        ("AKTIF_MADDE", False, False, "invalid_characters"),
        ("REÇETE-1", False, False, "invalid_characters"),
        ("A B", False, False, "invalid_characters"),
        ("-AB", False, False, "invalid_characters"),
        ("1-AB", True, False, "code_must_start_with_letter"),
        ("", False, False, "code_required"),
        ("A" * 21, False, False, "code_too_long"),
    ],
)
def test_character_rule(code, scanned, underscore, expected):
    error = formats.character_error(
        code, scanned=scanned, allow_underscore=underscore, max_length=20
    )
    assert (error.code if error else None) == expected


def test_registry_lookup_and_order():
    assert registry.code_type("document.TD").label == "Deneme belgesi"
    assert registry.code_type("CORE_TESTAPP.WIDGET").key == WIDGET
    assert registry.code_type("document.td") is None
    kinds = [item.kind for item in registry.code_types()]
    assert kinds == sorted(kinds, key=registry.KINDS.index)
    with pytest.raises(ValueError):
        registry.register_master_code("x.y", label="X", model="x.y")


# --- biçim değiştirme ------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_scheme_requires_admin(make_user):
    with pytest.raises(PermissionDenied):
        services.update_scheme(make_user(PLANLAMA), WIDGET, width=5, note="Not")


@pytest.mark.django_db
def test_update_scheme_requires_note(admin):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, WIDGET, width=5, note="  ")
    assert exc.value.code == "note_required"
    assert not CodeScheme.objects.exists()


@pytest.mark.django_db
def test_locked_type_cannot_be_changed(admin):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TK", width=6, note="Not")
    assert exc.value.code == "scheme_locked"


@pytest.mark.django_db
def test_update_scheme_writes_revision_and_audit(admin):
    row = services.update_scheme(admin, "document.TD", prefix="tx", width=6, note="Yeni önek")
    assert (row.prefix, row.width, row.year_format, row.revision) == ("TX", 6, "YYYY", 1)
    revision = CodeSchemeRevision.objects.get(scheme=row)
    assert (revision.revision, revision.prefix, revision.note) == (1, "TX", "Yeni önek")
    assert revision.changed_by == admin
    with pytest.raises(ValueError):
        revision.save()
    with pytest.raises(ValueError):
        revision.delete()
    update = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(CodeScheme),
        object_id=row.pk,
        action=AuditLog.Action.UPDATE,
    ).get()
    assert update.changes["prefix"] == ["TD", "TX"]
    assert update.changes["width"] == [5, 6]
    assert update.note == "Yeni önek"
    assert selectors.describe(registry.get_code_type("document.TD"))["next"].startswith("TX-")


@pytest.mark.django_db
def test_update_scheme_without_changes_is_rejected(admin):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TD", width=5, note="Aynı")
    assert exc.value.code == "no_change"
    assert not CodeScheme.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("key", "values", "code"),
    [
        ("document.TD", {"prefix": "1AB"}, "invalid_prefix"),
        ("document.TD", {"width": 8}, "invalid_width"),
        ("document.TD", {"year_format": "YYY"}, "invalid_year_format"),
        ("lot.Q", {"prefix": "QQQQQ"}, "invalid_prefix"),
        ("lot.Q", {"date_format": "DDMMYY"}, "invalid_date_format"),
        (WIDGET, {"prefix": "WD-G"}, "invalid_prefix"),
        (WIDGET, {"width": 1}, "invalid_width"),
        (WIDGET, {"prefix": "ABCDEFGHIJKL", "width": 9}, "pattern_too_long"),
        (TYPED, {"type_prefixes": {"ALPHA": "ALF"}}, "invalid_type_prefixes"),
    ],
)
def test_update_scheme_rejects_invalid_format(admin, key, values, code):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, key, note="Not", **values)
    assert exc.value.code == code


@pytest.mark.django_db
def test_prefix_cannot_be_taken_from_another_type(admin):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TD", prefix="TK", note="Not")
    assert exc.value.code == "prefix_in_use"
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, WIDGET, prefix="ALF", note="Not")
    assert exc.value.code == "prefix_in_use"


@pytest.mark.django_db
def test_former_prefix_stays_with_its_type(admin):
    services.update_scheme(admin, "document.TD", prefix="TX", note="Bir")
    services.update_scheme(admin, "document.TD", prefix="TD", note="Geri")  # kendi eski öneki
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TK", prefix="TX", note="Not")  # kilitli
    assert exc.value.code == "scheme_locked"
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TZ", prefix="TX", note="Not")
    assert exc.value.code == "prefix_in_use"


@pytest.mark.django_db
def test_sequence_cannot_be_narrower_than_counter(admin):
    year = timezone.localdate().year
    DocumentSequence.objects.create(prefix="TD", year=year, last_number=12_345)
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TD", width=4, note="Not")
    assert exc.value.code == "sequence_too_narrow"
    TEST_LOT_COUNTERS[("Q", timezone.localdate())] = 1_000
    try:
        with pytest.raises(BusinessRuleError) as exc:
            services.update_scheme(admin, "lot.Q", date_format="YYMMDD", note="Not")
        assert exc.value.code == "sequence_too_narrow"
    finally:
        TEST_LOT_COUNTERS.clear()


@pytest.mark.django_db
def test_is_active_only_for_master_codes(admin):
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, "document.TD", is_active=True, note="Not")
    assert exc.value.code == "not_applicable"


@pytest.mark.django_db
def test_counter_correction_is_audited(admin):
    Widget.objects.create(name="a", code="WDG-0007")
    activate(admin)
    assert selectors.suggest_code(widget_type()) == "WDG-0008"
    row = services.update_scheme(admin, WIDGET, counters={"WDG": 50}, note="Sayaç")
    assert CodeSequence.objects.get(key=WIDGET, stem="WDG-").last_number == 49
    assert selectors.suggest_code(widget_type()) == "WDG-0050"
    assert CodeSchemeRevision.objects.get(scheme=row, revision=2).counters == {"WDG": 50}
    log = AuditLog.objects.get(action=AuditLog.Action.CUSTOM, object_id=row.pk)
    assert log.changes == {"counters": {"WDG": [8, 50]}}
    # Geri alınan sayaç dolu numarayı atlar.
    services.update_scheme(admin, WIDGET, counters={"WDG": 7}, note="Geri")
    assert selectors.suggest_code(widget_type()) == "WDG-0008"
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, WIDGET, counters={"XYZ": 3}, note="Not")
    assert exc.value.code == "unknown_prefix"


@pytest.mark.django_db
def test_counter_correction_is_bounded(admin):
    item = widget_type()
    # Sayaç sınırını aşan kod (biçim kapalıyken girilmiş) sayacın başlangıcını taşırmaz.
    Widget.objects.create(name="dev", code="WDG-" + "9" * 16)
    assert selectors.highest_number(item, "WDG") == 0
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(admin, WIDGET, counters={"WDG": formats.MAX_COUNTER + 1}, note="Not")
    assert exc.value.code == "invalid_counter"
    # Sıradaki numarayla kod türün en uzun kod sınırını aşamaz (deneme parçası: 20 karakter).
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(
            admin, WIDGET, prefix="WDGXYZ", counters={"WDGXYZ": 10**14}, note="Not"
        )
    assert exc.value.code == "invalid_counter"
    assert "22 karakter" in exc.value.message
    assert not CodeSequence.objects.exists() and not CodeScheme.objects.exists()
    services.update_scheme(admin, WIDGET, counters={"WDG": formats.MAX_COUNTER}, note="Sınır")
    assert CodeSequence.objects.get(key=WIDGET).last_number == formats.MAX_COUNTER - 1
    assert selectors.describe(item)["next"] == f"WDG-{formats.MAX_COUNTER}"


@pytest.mark.django_db
def test_type_prefixes_only_for_types_with_type_field(admin):
    """Türe göre önek yalnız önekini kaydın türünden alan kodda geçerlidir; öteki türde yok
    sayılır, sayaç düzeltmesine önek olarak giremez."""
    with pytest.raises(BusinessRuleError) as exc:
        services.update_scheme(
            admin, WIDGET, type_prefixes={"x": "ÇÖP"}, counters={"ÇÖP": 5}, note="Not"
        )
    assert exc.value.code == "unknown_prefix"
    assert not CodeSequence.objects.exists()
    row = services.update_scheme(
        admin, WIDGET, type_prefixes={"x": "ÇÖP"}, counters={"WDG": 25}, note="Sayaç"
    )
    assert row.type_prefixes == {}
    assert list(CodeSequence.objects.values_list("stem", "last_number")) == [("WDG-", 24)]
    assert CodeSchemeRevision.objects.get(scheme=row).counters == {"WDG": 25}
    preview = selectors.preview(widget_type(), {"type_prefixes": {"x": "ÇÖP"}})
    assert preview["valid"] and preview["example"]["type_prefixes"] == {}


# --- öneri, kod alma, eski kodlar ------------------------------------------------------------


@pytest.mark.django_db
def test_suggestion_only_when_active_and_skips_used_and_former_codes(admin):
    assert selectors.suggest_code(widget_type()) is None
    first = Widget.objects.create(name="a", code="WDG-0001")
    Widget.objects.create(name="b", code="WDG-0003")
    activate(admin)
    assert selectors.suggest_code(widget_type()) == "WDG-0004"
    services.record_code_change(admin, widget_type(), first, "WDG-0004")
    assert selectors.suggest_code(widget_type()) == "WDG-0005"


@pytest.mark.django_db
def test_type_based_prefix(admin):
    TypedWidget.objects.create(code="ALF-001", name="a", kind="ALPHA")
    activate(admin, TYPED)
    assert selectors.suggest_code(typed_type(), type_value="ALPHA") == "ALF-002"
    assert selectors.suggest_code(typed_type(), type_value="BETA") == "BET-001"
    assert selectors.suggest_code(typed_type(), type_value="GAMMA") is None
    beta = TypedWidget(code="ALF-002", name="b", kind="BETA")
    with pytest.raises(BusinessRuleError) as exc:
        services.check_master_code(typed_type(), beta, previous_code=None)
    assert exc.value.code == "code_format"
    beta.code = "BET-001"
    services.check_master_code(typed_type(), beta, previous_code=None)


@pytest.mark.django_db
def test_check_master_code_rules(admin):
    item = widget_type()
    old = Widget.objects.create(name="eski", code="WDG-0002")
    services.record_code_change(admin, item, old, "ESKI-1")
    other = Widget(name="yeni", code="ESKI-1")
    # Kullanılmış kod biçim kapalıyken de başka kayda verilmez.
    with pytest.raises(BusinessRuleError) as exc:
        services.check_master_code(item, other, previous_code=None)
    assert exc.value.code == "code_reserved"
    # Kayıt kendi eski koduna dönebilir.
    old.code = "ESKI-1"
    services.check_master_code(item, old, previous_code="WDG-0002")
    # Biçim kapalıyken serbest.
    other.code = "SERBEST"
    services.check_master_code(item, other, previous_code=None)
    activate(admin)
    with pytest.raises(BusinessRuleError) as exc:
        services.check_master_code(item, other, previous_code=None)
    assert exc.value.code == "code_format"
    other.code = "WDG-ÇÜ"
    with pytest.raises(BusinessRuleError) as exc:
        services.check_master_code(item, other, previous_code=None)
    assert exc.value.code == "invalid_characters"
    # Kodu değişmeyen eski kayıt düzenlenebilir.
    legacy = Widget.objects.create(name="biçimsiz", code="ESKI-KOD")
    services.check_master_code(item, legacy, previous_code="ESKI-KOD")


@pytest.mark.django_db
def test_claim_advances_counter_only_within_window(admin):
    item = widget_type()
    activate(admin)
    services.claim_master_code(item, Widget(name="a", code="WDG-0001"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 1
    services.claim_master_code(item, Widget(name="b", code="WDG-0011"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 11
    # Pencerenin dışındaki numara kabul edilir ama sayacı ilerletmez.
    services.claim_master_code(item, Widget(name="c", code="WDG-0500"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 11
    # Biçime uymayan kod (biçim kapalıyken girilmiş) sayaca dokunmaz.
    services.claim_master_code(item, Widget(name="d", code="SERBEST"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 11


@pytest.mark.django_db
def test_counter_window_is_measured_from_the_suggestion(admin):
    """Pencere önerilen numaradan ölçülür: sayacın hemen üstünde dolu numaralar olsa da öneriyi
    kaydetmek sayacı ilerletir (sayaç takılı kalmaz)."""
    item = widget_type()
    for number in range(1, 16):
        Widget.objects.create(name=f"w{number}", code=formats.master_code("WDG", 4, number))
    activate(admin)
    services.update_scheme(admin, WIDGET, counters={"WDG": 3}, note="Sayaç geri alındı")
    assert selectors.suggest_code(item) == "WDG-0016"
    services.claim_master_code(item, Widget(name="a", code="WDG-0016"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 16
    # Öneri WDG-0017: en çok 10 ileri (WDG-0027) sayacı ilerletir, daha ilerisi ilerletmez.
    services.claim_master_code(item, Widget(name="b", code="WDG-0027"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 27
    services.claim_master_code(item, Widget(name="c", code="WDG-0039"), previous_code=None)
    assert CodeSequence.objects.get(key=WIDGET).last_number == 27


@pytest.mark.django_db
def test_claim_rechecks_reserved_code(admin):
    """Kod alınırken eski kod denetimi yinelenir: kodu bu arada bırakan kaydın eski kodu yeni
    kayda verilmez; kayıt kendi eski koduna dönebilir."""
    item = widget_type()
    first = Widget.objects.create(name="a", code="WDG-0002")
    services.record_code_change(admin, item, first, "WDG-0001")
    services.record_code_change(admin, item, first, "ESKI-1")
    for code in ("WDG-0001", "ESKI-1"):  # biçime uyan ve uymayan (sayaç kilidi yok) kod
        with pytest.raises(BusinessRuleError) as exc:
            services.claim_master_code(item, Widget(name="b", code=code), previous_code=None)
        assert exc.value.code == "code_reserved"
    first.code = "WDG-0001"
    services.claim_master_code(item, first, previous_code="WDG-0002")


@pytest.mark.django_db
def test_claim_rejects_code_taken_meanwhile(admin):
    item = widget_type()
    activate(admin)
    Widget.objects.create(name="ilk", code="WDG-0001")
    with pytest.raises(BusinessRuleError) as exc:
        services.claim_master_code(item, Widget(name="ikinci", code="WDG-0001"), previous_code=None)
    assert exc.value.code == "code_taken"
    assert "WDG-0002" in exc.value.message


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_of_same_code():
    item = widget_type()
    workers = 6
    barrier = threading.Barrier(workers)
    results: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        try:
            barrier.wait()
            with transaction.atomic():
                widget = Widget(name=f"w{index}", code="WDG-0001")
                services.claim_master_code(item, widget, previous_code=None)
                widget.save()
            outcome = "ok"
        except BusinessRuleError as exc:
            outcome = exc.code
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["code_taken"] * (workers - 1) + ["ok"]
    assert Widget.objects.filter(code="WDG-0001").count() == 1


@pytest.mark.django_db
def test_history_lookup_and_code_as_of(admin):
    item = widget_type()
    widget = Widget.objects.create(name="a", code="A-1")
    created = widget.created_at
    services.record_code_change(admin, item, widget, "A-1")
    Widget.objects.filter(pk=widget.pk).update(code="A-2")
    widget.refresh_from_db()
    first_change = timezone.now()
    services.record_code_change(admin, item, widget, "A-2", reason=CodeHistory.Reason.MIGRATION)
    Widget.objects.filter(pk=widget.pk).update(code="A-3")
    widget.refresh_from_db()

    assert selectors.find_by_code(Widget, "A-3") == (widget, False)
    assert selectors.find_by_code(Widget, "A-1") == (widget, True)
    assert selectors.find_by_code(Widget, "YOK") == (None, False)
    assert selectors.former_codes(widget) == ["A-2", "A-1"]
    assert selectors.former_code_map(Widget, [widget.pk]) == {widget.pk: ["A-2", "A-1"]}
    assert selectors.code_as_of(widget, created) == "A-1"
    assert selectors.code_as_of(widget, first_change) == "A-2"
    assert selectors.code_as_of(widget, timezone.now()) == "A-3"
    history = CodeHistory.objects.filter(object_id=widget.pk).order_by("valid_to")
    assert history[0].valid_to == history[1].valid_from
    with pytest.raises(ValueError):
        history[0].delete()


@pytest.mark.django_db
def test_describe_and_preview(admin):
    Widget.objects.create(name="a", code="WDG-0009")
    body = selectors.describe(widget_type())
    assert (body["format"], body["next"], body["last_number"]) == ("WDG-0000", "WDG-0010", 9)
    assert body["is_active"] is False and body["samples"] == ["WDG-0009"]
    preview = selectors.preview(widget_type(), {"prefix": "PRC", "width": 6})
    assert preview["valid"] and preview["example"]["next"] == "PRC-000001"
    assert not CodeScheme.objects.exists()
    bad = selectors.preview(widget_type(), {"prefix": "ALF"})
    assert bad == {
        "valid": False,
        "error": {"code": "prefix_in_use", "detail": bad["error"]["detail"]},
        "example": None,
    }
    typed = selectors.describe(typed_type())
    assert [(t["value"], t["next"]) for t in typed["types"]] == [
        ("ALPHA", "ALF-001"),
        ("BETA", "BET-001"),
    ]
    lot = selectors.describe(registry.get_code_type("lot.Q"))
    assert lot["next"] == f"Q-{timezone.localdate():%Y%m%d}-001"


# --- API -------------------------------------------------------------------------------------

BASE = "/api/v1/coding"


@pytest.mark.django_db
def test_api_requires_admin(client_for, api_client):
    assert api_client.get(f"{BASE}/types/").status_code == 401
    planner = client_for(PLANLAMA)
    assert planner.get(f"{BASE}/types/").status_code == 403
    assert planner.get(f"{BASE}/types/{WIDGET}/").status_code == 403
    assert planner.put(f"{BASE}/types/{WIDGET}/", {"note": "x"}, format="json").status_code == 403
    assert planner.post(f"{BASE}/types/{WIDGET}/preview/", {}, format="json").status_code == 403
    assert planner.get(f"{BASE}/types/{WIDGET}/revisions/").status_code == 403


@pytest.mark.django_db
def test_api_list_detail_update_preview_and_revisions(client_for):
    client = client_for(ADMIN)
    listing = client.get(f"{BASE}/types/", {"kind": "document"}).json()
    keys = [item["key"] for item in listing["results"]]
    assert "document.TD" in keys and WIDGET not in keys
    assert client.get(f"{BASE}/types/yok.yok/").status_code == 404

    response = client.put(
        f"{BASE}/types/{WIDGET}/",
        {"prefix": "prc", "width": 5, "is_active": True, "note": "Biçim"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["next"] == "PRC-00001" and response.json()["is_active"] is True

    blank = client.put(f"{BASE}/types/{WIDGET}/", {"width": 6, "note": ""}, format="json")
    assert blank.status_code == 400 and blank.json()["code"] == "note_required"

    preview = client.post(
        f"{BASE}/types/{WIDGET}/preview/", {"prefix": "ABCDEFGHIJKL", "width": 9}, format="json"
    ).json()
    assert preview["valid"] is False and preview["error"]["code"] == "pattern_too_long"

    revisions = client.get(f"{BASE}/types/{WIDGET}/revisions/").json()
    assert [row["note"] for row in revisions["results"]] == ["Biçim"]


@pytest.mark.django_db
def test_api_preview_with_counters_writes_nothing(client_for):
    """Önizleme sıradaki numarayı biçim değiştirmedeki kurallarla denetler ve örneği sayaç
    düzeltilmiş gibi gösterir; hiçbir şey yazılmaz."""
    Widget.objects.create(name="a", code="WDG-0007")
    TypedWidget.objects.create(code="ALF-001", name="t", kind="ALPHA")
    client = client_for(ADMIN)
    logs = AuditLog.objects.count()
    url = f"{BASE}/types/{WIDGET}/preview/"

    def example(body):
        response = client.post(url, body, format="json")
        assert response.status_code == 200, response.json()
        return response.json()["example"]

    body = example({})
    assert (body["next"], body["last_number"]) == ("WDG-0008", 7)
    body = example({"counters": {"wdg": 50}})
    assert (body["next"], body["last_number"]) == ("WDG-0050", 49)
    # Geri alınan sayaç dolu numarayı atlar (kaydedilince olacağı gibi).
    body = example({"counters": {"WDG": 7}})
    assert (body["next"], body["last_number"]) == ("WDG-0008", 6)
    # Önek de değişiyorsa sayaç yeni önektedir.
    assert example({"prefix": "PRC", "counters": {"PRC": 12}})["next"] == "PRC-0012"
    typed = client.post(
        f"{BASE}/types/{TYPED}/preview/", {"counters": {"ALF": 5, "BET": 3}}, format="json"
    ).json()["example"]
    assert [(t["prefix"], t["next"], t["last_number"]) for t in typed["types"]] == [
        ("ALF", "ALF-005", 4),
        ("BET", "BET-003", 2),
    ]
    assert (typed["next"], typed["last_number"]) == ("ALF-005", 4)

    for key, body, code in [
        (WIDGET, {"counters": {"XYZ": 3}}, "unknown_prefix"),
        (WIDGET, {"prefix": "WDGXYZ", "counters": {"WDGXYZ": 10**14}}, "invalid_counter"),
        ("document.TD", {"counters": {"TD": 3}}, "counters_not_allowed"),
    ]:
        response = client.post(f"{BASE}/types/{key}/preview/", body, format="json").json()
        assert (response["valid"], response["error"]["code"]) == (False, code), response
    for value in (0, formats.MAX_COUNTER + 1, 2**63):
        response = client.post(url, {"counters": {"WDG": value}}, format="json")
        assert response.status_code == 400 and response.json()["code"] == "validation_error"

    assert not CodeSequence.objects.exists() and not CodeScheme.objects.exists()
    assert not CodeSchemeRevision.objects.exists() and AuditLog.objects.count() == logs


@pytest.mark.django_db
def test_api_preview_of_standard_and_locked_types(client_for):
    client = client_for(ADMIN)
    for key in ("masterdata.unitofmeasure", "document.TK"):
        response = client.post(f"{BASE}/types/{key}/preview/", {}, format="json")
        assert response.status_code == 200, response.json()
        body = response.json()
        assert (body["valid"], body["error"]["code"], body["example"]) == (
            False,
            "scheme_locked",
            None,
        )


@pytest.mark.django_db
def test_api_counter_correction_rejects_huge_numbers(client_for):
    client = client_for(ADMIN)
    for value in (formats.MAX_COUNTER + 1, 2**63 + 1):
        response = client.put(
            f"{BASE}/types/{WIDGET}/", {"counters": {"WDG": value}, "note": "x"}, format="json"
        )
        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        assert "WDG" in response.json()["errors"]["counters"]
    assert not CodeSequence.objects.exists()


@pytest.mark.django_db
def test_api_suggestion_for_write_roles(client_for, make_user):
    planner = client_for(PLANLAMA)
    inactive = planner.get(f"{BASE}/suggest/{WIDGET}/").json()
    assert inactive == {"key": WIDGET, "active": False, "code": None, "format": "WDG-0000"}
    activate(make_user(ADMIN))
    assert planner.get(f"{BASE}/suggest/{WIDGET}/").json()["code"] == "WDG-0001"
    assert client_for(DEPO).get(f"{BASE}/suggest/{WIDGET}/").status_code == 403
    # Yazma rolü tanımlanmamış tür yalnız admin'e açık.
    assert planner.get(f"{BASE}/suggest/{TYPED}/").status_code == 403
    assert client_for(ADMIN).get(f"{BASE}/suggest/{TYPED}/", {"type": "BETA"}).status_code == 200
    assert planner.get(f"{BASE}/suggest/yok.yok/").status_code == 404


# --- belge ve lot numaraları -----------------------------------------------------------------


@pytest.mark.django_db
def test_document_numbers_follow_coding_settings(admin):
    from apps.core import services as core

    assert core.next_document_number("TD", year=2026) == "TD-2026-00001"
    services.update_scheme(admin, "document.TD", year_format="YY", width=4, note="Kısa yıl")
    # Önek aynı: sayaç devam eder.
    assert core.next_document_number("TD", year=2026) == "TD-26-0002"
    services.update_scheme(admin, "document.TD", prefix="TX", note="Yeni önek")
    # Yeni önekte sayaç 1'den başlar; eski numaralar değişmez.
    assert core.next_document_number("TD", year=2026) == "TX-26-0001"
    assert DocumentSequence.objects.get(prefix="TD", year=2026).last_number == 2
    # Kayıtsız önek (yalnızca testler) bugünkü biçimde kalır.
    assert core.next_document_number("QQ", year=2026) == "QQ-2026-00001"


def test_every_document_prefix_in_source_is_registered():
    """Kaynaktaki her sabit belge öneki kayıtlı bir belge türüdür ve her kayıtlı tür kullanılır;
    yeni bir belge türü kodlama ayarını atlayamaz."""
    import pathlib
    import re

    from apps.inventory.services import LOT_PREFIXES

    apps_dir = pathlib.Path(__file__).resolve().parents[2]
    patterns = [
        re.compile(r'create_document\((?:.|\n){0,400}?prefix="([A-Z][A-Z0-9]{0,9})"'),
        re.compile(r'next_document_number\(\s*"([A-Z][A-Z0-9]{0,9})"'),
    ]
    found: dict[str, str] = {}
    for path in apps_dir.rglob("*.py"):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            for match in pattern.finditer(text):
                found.setdefault(match.group(1), str(path.relative_to(apps_dir)))
    registered = {
        item.default_prefix
        for item in registry.code_types(registry.DOCUMENT)
        if not item.model.startswith("core_testapp") and item.default_prefix not in {"TK", "TZ"}
    }
    assert len(found) == 17
    assert set(found) == registered, {p: f for p, f in found.items() if p not in registered}
    assert registry.document_type("SV").locked
    assert all(registry.lot_type(prefix) for prefix in LOT_PREFIXES.values())


@pytest.mark.django_db
def test_api_all_revisions_for_history(client_for, make_user):
    admin = make_user(ADMIN)
    services.update_scheme(admin, "document.TD", width=6, note="Birinci")
    activate(admin)
    client = client_for(ADMIN)
    rows = client.get(f"{BASE}/revisions/").json()["results"]
    assert [(row["key"], row["label"], row["note"]) for row in rows] == [
        (WIDGET, "Deneme parçası", "Etkinleştirildi"),
        ("document.TD", "Deneme belgesi", "Birinci"),
    ]
    assert client_for(PLANLAMA).get(f"{BASE}/revisions/").status_code == 403


# --- kod göçü --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_recode_preview_apply_and_revert(admin):
    from apps.core.coding import migration
    from apps.core.models import CodeMigrationRun

    first = Widget.objects.create(name="a", code="ESKI-A")
    keep = Widget.objects.create(name="b", code="WDG-0003")
    third = Widget.objects.create(name="c", code="X")
    plan = migration.preview_recode(WIDGET)
    rows = {row["id"]: row for row in plan["rows"]}
    assert (rows[first.pk]["action"], rows[first.pk]["new"]) == ("change", "WDG-0004")
    assert (rows[keep.pk]["action"], rows[keep.pk]["new"]) == ("keep", "WDG-0003")
    assert rows[third.pk]["new"] == "WDG-0005"
    assert (plan["change_count"], plan["keep_count"], plan["problem_count"]) == (2, 1, 0)
    assert not CodeMigrationRun.objects.exists()

    with pytest.raises(BusinessRuleError) as exc:
        migration.apply_recode(admin, WIDGET, checksum="eski", note="Göç")
    assert exc.value.code == "recode_stale"
    with pytest.raises(BusinessRuleError) as exc:
        migration.apply_recode(admin, WIDGET, checksum=plan["checksum"], note=" ")
    assert exc.value.code == "note_required"

    run = migration.apply_recode(admin, WIDGET, checksum=plan["checksum"], note="Canlı göç")
    first.refresh_from_db()
    third.refresh_from_db()
    assert (first.code, third.code) == ("WDG-0004", "WDG-0005")
    assert run.mapping == [
        {"id": first.pk, "label": "a", "old": "ESKI-A", "new": "WDG-0004"},
        {"id": third.pk, "label": "c", "old": "X", "new": "WDG-0005"},
    ]
    assert CodeHistory.objects.filter(run=run).count() == 2
    log = AuditLog.objects.get(object_id=first.pk, action=AuditLog.Action.UPDATE)
    assert log.changes == {"code": ["ESKI-A", "WDG-0004"]}
    assert log.note == f"Kod göçü #{run.pk}: Canlı göç"
    assert CodeSequence.objects.get(key=WIDGET, stem="WDG-").last_number == 5
    assert selectors.find_by_code(Widget, "ESKI-A") == (first, True)
    again = migration.preview_recode(WIDGET)
    assert again["change_count"] == 0
    with pytest.raises(BusinessRuleError) as exc:
        migration.apply_recode(admin, WIDGET, checksum=again["checksum"], note="Boş")
    assert exc.value.code == "recode_nothing"

    # Göçten sonra kodu değişen kayıt geri alınmaz.
    Widget.objects.filter(pk=third.pk).update(code="WDG-0099")
    preview = migration.preview_revert(run.pk)
    assert [(row["id"], row["action"]) for row in preview["rows"]] == [
        (first.pk, "revert"),
        (third.pk, "skip"),
    ]
    revert = migration.revert_recode(admin, run.pk, note="Geri al")
    first.refresh_from_db()
    assert first.code == "ESKI-A" and revert.reverts == run
    assert revert.mapping == [{"id": first.pk, "label": "a", "old": "WDG-0004", "new": "ESKI-A"}]
    # Geri alınan yeni kod da eski kod olarak saklanır; başka kayda verilmez.
    assert selectors.code_reserved(widget_type(), "WDG-0004", exclude_pk=third.pk)
    with pytest.raises(BusinessRuleError) as exc:
        migration.revert_recode(admin, run.pk, note="Tekrar")
    assert exc.value.code == "already_reverted"
    with pytest.raises(BusinessRuleError) as exc:
        migration.revert_recode(admin, revert.pk, note="Geri almanın geri alması")
    assert exc.value.code == "revert_not_allowed"


@pytest.mark.django_db
def test_recode_rules(admin, make_user):
    from apps.core.coding import migration

    with pytest.raises(PermissionDenied):
        migration.apply_recode(make_user(PLANLAMA), WIDGET, checksum="", note="Göç")
    with pytest.raises(BusinessRuleError) as exc:
        migration.preview_recode(TYPED)  # göç kancası kayıtlı değil
    assert exc.value.code == "recode_not_allowed"
    with pytest.raises(BusinessRuleError) as exc:
        migration.preview_recode("document.TD")
    assert exc.value.code == "recode_not_allowed"


@pytest.mark.django_db
def test_recode_api(client_for):
    Widget.objects.create(name="a", code="ESKI-A")
    client = client_for(ADMIN)
    preview = client.get(f"{BASE}/recode/{WIDGET}/").json()
    assert preview["change_count"] == 1 and preview["rows"][0]["new"] == "WDG-0001"
    applied = client.post(
        f"{BASE}/recode/{WIDGET}/apply/",
        {"checksum": preview["checksum"], "note": "Göç"},
        format="json",
    )
    assert applied.status_code == 201, applied.json()
    run = applied.json()
    assert (run["kind"], run["count"], run["reverted"], run["label"]) == (
        "apply",
        1,
        False,
        "Deneme parçası",
    )
    runs = client.get(f"{BASE}/runs/").json()["results"]
    assert [row["id"] for row in runs] == [run["id"]]
    revert_preview = client.get(f"{BASE}/runs/{run['id']}/revert-preview/").json()
    assert revert_preview["revert_count"] == 1
    reverted = client.post(f"{BASE}/runs/{run['id']}/revert/", {"note": "Geri"}, format="json")
    assert reverted.status_code == 201 and reverted.json()["reverts"] == run["id"]
    assert client.get(f"{BASE}/runs/").json()["results"][1]["reverted"] is True

    planner = client_for(PLANLAMA)
    assert planner.get(f"{BASE}/recode/{WIDGET}/").status_code == 403
    apply_url = f"{BASE}/recode/{WIDGET}/apply/"
    assert planner.post(apply_url, {"checksum": "x", "note": "x"}, format="json").status_code == 403
    assert planner.get(f"{BASE}/runs/").status_code == 403
    assert planner.get(f"{BASE}/runs/{run['id']}/revert-preview/").status_code == 403
    assert planner.post(f"{BASE}/runs/{run['id']}/revert/", {"note": "x"}).status_code == 403


def test_busy_lock_errors_become_business_errors():
    """Kilit bekleme süresi dolması (55P03) ve kilitlenme (40P01) göçü `recode_busy` ile
    reddeder; öteki veritabanı hataları olduğu gibi geçer."""
    from apps.core.coding import migration

    class Cause(Exception):
        def __init__(self, sqlstate: str) -> None:
            super().__init__(sqlstate)
            self.sqlstate = sqlstate

    def failing(sqlstate: str):
        @migration._reject_when_busy
        def run() -> None:
            raise OperationalError("kilit") from Cause(sqlstate)

        return run

    for sqlstate in ("55P03", "40P01"):
        with pytest.raises(BusinessRuleError) as exc:
            failing(sqlstate)()
        assert exc.value.code == "recode_busy"
    with pytest.raises(OperationalError):
        failing("08006")()


@pytest.mark.django_db(transaction=True)
def test_recode_is_rejected_while_records_are_locked(client_for, monkeypatch):
    """Kayıtlar başka bir işlemde kilitliyken göç ve geri alma beklemez: 400 `recode_busy`,
    hiçbir şey değişmez."""
    from apps.core.coding import migration
    from apps.core.models import CodeMigrationRun

    monkeypatch.setattr(migration, "LOCK_TIMEOUT_MS", 100)
    widget = Widget.objects.create(name="a", code="ESKI-A")
    CodeSequence.objects.create(key=WIDGET, stem="WDG-", last_number=0)
    client = client_for(ADMIN)

    def while_locked(lock, call):
        """`lock` başka bir bağlantının açık işleminde kilitliyken `call`'ı çalıştırır."""
        locked, release = threading.Event(), threading.Event()

        def hold() -> None:
            try:
                with transaction.atomic():
                    lock()
                    locked.set()
                    release.wait(10)
            finally:
                connection.close()

        thread = threading.Thread(target=hold)
        thread.start()
        try:
            assert locked.wait(10)
            return call()
        finally:
            release.set()
            thread.join()

    checksum = client.get(f"{BASE}/recode/{WIDGET}/").json()["checksum"]
    body = {"checksum": checksum, "note": "Göç"}
    busy = while_locked(
        lambda: CodeSequence.objects.select_for_update().get(key=WIDGET),
        lambda: client.post(f"{BASE}/recode/{WIDGET}/apply/", body, format="json"),
    )
    assert busy.status_code == 400 and busy.json()["code"] == "recode_busy", busy.json()
    assert not CodeMigrationRun.objects.exists()
    applied = client.post(f"{BASE}/recode/{WIDGET}/apply/", body, format="json")
    assert applied.status_code == 201, applied.json()

    run_id = applied.json()["id"]
    busy = while_locked(
        lambda: Widget.objects.select_for_update().get(pk=widget.pk),
        lambda: client.post(f"{BASE}/runs/{run_id}/revert/", {"note": "Geri"}, format="json"),
    )
    assert busy.status_code == 400 and busy.json()["code"] == "recode_busy", busy.json()
    widget.refresh_from_db()
    assert widget.code == "WDG-0001"
    assert CodeMigrationRun.objects.count() == 1
