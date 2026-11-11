"""Denetim günlüğü sondası (plan §5.5, 2. parça; §5.6 "Kayıt geçmişi ve denetim günlüğü").

Bugün denetim günlüğünü (`GET /api/v1/audit-log/`) admin, yönetim ve süper kullanıcı okur; üçü de
bütün kayıtları bütün alanları ve notlarıyla görür. 6. adımdaki süzme (kayıt defteriyle) varsayılan
paketlerde bunu değiştirmemelidir. Bilerek değişenler (§8 madde 7: satın alma onay notlarındaki
tutarlar alanlara geçer; madde 8: yeni işçilik oranının notu) izin listesine bağlanır.

Kayıt izi bugünkü servislerle (ve API'nin giriş uçlarıyla) üretilir; denetim kaydı elle yazılmaz.
Yalnız `model: ...` durumları, her proje modeli için birer sentetik kayıtla alan düzeyindeki
süzmeyi dondurur (her modeli gerçek servisle üretmek mümkün değil).

Durumlar (persona başına). `read: list` ve `read: detail` her persona için yazılır; öteki durumlar
yalnız okuyabilen personalar için, `trail:` durumları da yalnız o kaydı görenler için:

- `read: list`, `read: fields`: liste isteğinin HTTP durumu ve bir kaydın alanları;
- `read: detail ...`: seçili hassas kayıtların ayrıntısı (kaydın imzası ya da HTTP durumu);
- `trail: <imza>`: görünen kayıt sayısı. İmza: model, işlem, değişen alanlar (iç içe kayıtlar,
  ör. silinen satır, `line.unit_price` biçiminde) ve not; tutar taşıyan alan ve not `$` ile
  işaretli. İmzada kimlik, zaman ve değer yoktur;
- `amounts: ...`: görünen tutarlı alanlar ve notlar;
- `search: ...`: `?search=` (kayıt adı ve not) sonuçları: tutarlar ve bir personelin soyadı.
  Ücret ve gider oranı gibi kayıtların adında tutar geçer (ör. "2 45678.90 (2020-01-01)");
- `model: <model>`: sentetik kaydın görünürlüğü (`full`: bütün alanlar ve not).
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import services as core
from apps.core.coding import services as coding
from apps.core.models import Attachment, AuditLog, User
from apps.core.roles import ADMIN, DEPO, DOLUM, LABORATUVAR, PLANLAMA, SATIN_ALMA, URETIM, YONETIM
from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.personas import make_personas
from apps.core.tests.factories import DEFAULT_PASSWORD
from apps.costing import services as costing
from apps.costing.models import CostStage
from apps.costing.tests.factories import build_chain
from apps.golive import services as golive
from apps.hse import services as hse
from apps.hse.models import Incident
from apps.inventory import services as inventory
from apps.inventory.models import GoodsReceiptExtraCost
from apps.inventory.testing import assert_stock_invariants
from apps.masterdata import services as masterdata
from apps.masterdata.tests.factories import MaterialFactory
from apps.personnel import services as personnel
from apps.personnel.models import AttendanceStatus, PayrollItemCategory
from apps.personnel.tests.factories import document, employee
from apps.production.models import ProductionBatch
from apps.purchasing import services as purchasing
from apps.purchasing.tests.factories import draft_order, line, raw_material
from apps.reporting import services as reporting
from apps.reporting.reports import REPORTS
from apps.workflow import services as workflow

pytestmark = pytest.mark.django_db

NAME = "probe_audit"
URL = "/api/v1/audit-log/"
Commit = Callable[[], AbstractContextManager[Any]]

# Tutar taşıyan alan adları: bugünkü kodun fiyat listeleri (satın alma `PRICE_FIELDS`, mal kabul
# `RECEIPT_PRICE_FIELDS` ve ek masraf tutarı), lot maliyeti alanları, maliyet ve ücret tutarları
# (plan §3.18, §5.6). Kod sabitleri import edilmez: sonraki adımlar onları değiştirebilir.
AMOUNT_FIELDS = frozenset(
    {
        "unit_price",
        "line_total",
        "total",
        "total_try",
        "currency",
        "exchange_rate",
        "approval_total_try",
        "approval_limit_try",
        "amount",
        "unit_cost",
        "cost_is_estimated",
        "total_cost",
        "finished_scrap_cost",
        "rate_per_kg",
        "gross_monthly",
    }
)
# Metindeki tutar: `format_money` biçimi (12.345,60).
MONEY = re.compile(r"\d,\d{2}(?!\d)")
MASK = "***"

# Personel kartının adı; soyadı personel araması için (Faker'ın Türkçe adlarında yok).
EMPLOYEE_NAME = "Zeynep Sondaş"
WAGE = Decimal("45678.90")
# Arama terimleri ayraçlı tutar ya da uydurma soyadıdır: kayıt adlarındaki kimliklerle ve rastgele
# kişi adlarıyla çakışmaz.
SEARCHES = {
    "12.345,60": "satın alma onay notları",
    "7.777,77": "mal kabul fiyat düzeltmesi notu ve ondan türeyen maliyet notları",
    "1.500,00": "bordro kaleminin personel kartı notu",
    "45678.90": "ücret kaydının adı",
    "Sondaş": "personel adı",
}

# Ayrıntısı (`GET /audit-log/{id}/`) dondurulan kayıtlar, ilk eşleşen: (model, işlem,
# değişikliklerde bulunması gereken alan, o alanın yeni değeri).
Detail = tuple[str | None, str, str | None, str | None]
DETAILS: dict[str, Detail] = {
    "core.user login": ("core.user", AuditLog.Action.LOGIN, None, None),
    "personnel.employeewage create": ("personnel.employeewage", AuditLog.Action.CREATE, None, None),
    "personnel.payrollitem create": ("personnel.payrollitem", AuditLog.Action.CREATE, None, None),
    "bordro erişimi (kayıtsız)": (None, AuditLog.Action.CUSTOM, "month", None),
    "costing.costrate create (işçilik notu)": (
        "costing.costrate",
        AuditLog.Action.CREATE,
        "note",
        None,
    ),
    "costing.lotcost create": ("costing.lotcost", AuditLog.Action.CREATE, None, None),
    "inventory.goodsreceipt update (silinen ek masraf)": (
        "inventory.goodsreceipt",
        AuditLog.Action.UPDATE,
        "extra_cost",
        None,
    ),
    "purchasing.purchaseorder status_change": (
        "purchasing.purchaseorder",
        AuditLog.Action.STATUS_CHANGE,
        None,
        None,
    ),
    "workflow.task create (satın alma onayı)": (
        "workflow.task",
        AuditLog.Action.CREATE,
        "rule_code",
        "purchase_order_approval",
    ),
    "hse.incident create": ("hse.incident", AuditLog.Action.CREATE, None, None),
    "workflow.comment create (olaya)": ("workflow.comment", AuditLog.Action.CREATE, None, None),
    "core.attachment create (olay fotoğrafı)": (
        "core.attachment",
        AuditLog.Action.CREATE,
        None,
        None,
    ),
    "golive.problemreport create": ("golive.problemreport", AuditLog.Action.CREATE, None, None),
}

# Sentetik kayıtlar (`model: ...`).
MARKER = "SONDA-MODEL"
MARKER_NOTE = f"{MARKER}: tutar 1.234,56 TL"
# Denetim günlüğüne hiç girmeyen alanlar (core.audit.EXCLUDED_FIELDS ile aynı).
UNTRACKED = frozenset(
    {"password", "last_login", "created_at", "created_by", "updated_at", "updated_by"}
)
# Proje modeli sayısı: yeni modelin denetim günlüğünde kime görüneceği bir karardır.
# 1. adım: core.accessoverride ve core.accesscatalogsnapshot eklendi (plan §5.2).
EXPECTED_MODELS = 124


# --- kayıt izi ---------------------------------------------------------------------------------


def _user(users: Mapping[str, User | None], persona: str) -> User:
    user = users[persona]
    assert user is not None
    return user


def _accounts(users: Mapping[str, User | None], commit: Commit) -> None:
    """Giriş, şifre değişikliği, çıkış ve başarısız giriş (API'den); kullanıcı açma ve rol."""
    admin = _user(users, ADMIN)
    browser = APIClient()
    login = {"username": _user(users, PLANLAMA).username, "password": DEFAULT_PASSWORD}
    assert browser.post("/api/v1/auth/login/", login, format="json").status_code == 200
    change = {"old_password": DEFAULT_PASSWORD, "new_password": "Yeni.Sifre-4567"}
    assert browser.post("/api/v1/auth/password/", change, format="json").status_code == 204
    assert browser.post("/api/v1/auth/logout/").status_code == 204
    wrong = {"username": _user(users, DEPO).username, "password": "yanlis-sifre"}
    assert APIClient().post("/api/v1/auth/login/", wrong, format="json").status_code == 400
    with commit():
        newcomer, _password = core.create_user(
            admin, username="iz.kullanici", full_name="İz Kullanıcı", roles=[DEPO]
        )
        core.update_user(admin, newcomer, roles=[DEPO, SATIN_ALMA])


def _personnel(users: Mapping[str, User | None], commit: Commit) -> None:
    """Personel kartı, ücret, puantaj (Eylül 2026 onaylı), bordro kalemi, özlük belgesi ve
    bordro çıktısı erişimi."""
    manager = _user(users, YONETIM)
    with commit():
        card = employee(manager, full_name=EMPLOYEE_NAME, department="Üretim", title="Operatör")
        card = personnel.update_employee(
            manager, card, {"title": "Kıdemli operatör", "national_id": "10000000146"}
        )
        personnel.add_wage(
            manager,
            {"employee": card, "gross_monthly": WAGE, "valid_from": date(2020, 1, 1)},
        )
        personnel.set_attendance_day(
            manager, card, date(2026, 9, 15), status=AttendanceStatus.ANNUAL_LEAVE
        )
        personnel.approve_attendance_month(manager, 2026, 9)
        personnel.add_payroll_item(
            manager,
            {
                "employee": card,
                "year": 2026,
                "month": 10,
                "category": PayrollItemCategory.PREMIUM,
                "description": "",
                "amount": Decimal("1500"),
            },
        )
        sheet = document(manager, card)
        personnel.record_document_access(manager, sheet)
        personnel.record_payroll_access(manager, 2026, 10, "Ön bordro PDF")


def _production_and_costs(users: Mapping[str, User | None], commit: Commit) -> None:
    """Fiyatlı ve ek masraflı mal kabul, şarj, lot maliyetleri (costing'in test zinciri); şarjı
    Eylül'e taşıyıp o ayın personel maliyetinden işçilik oranı; mal kabulde fiyat düzeltmesi
    (satır fiyatı, silinen ek masraf, tutarlı not) ve ondan doğan yeni maliyet sürümleri."""
    roles = (DEPO, URETIM, LABORATUVAR, PLANLAMA, YONETIM, DOLUM, SATIN_ALMA)
    staff = {role: _user(users, role) for role in roles}
    chain = build_chain(staff, commit, fill=False)
    assert chain.batch is not None
    september = timezone.make_aware(datetime(2026, 9, 15, 12, 0))
    ProductionBatch.objects.filter(pk=chain.batch.pk).update(finished_at=september)
    manager = staff[YONETIM]
    with commit():
        costing.set_department_cost_center(manager, "Üretim", CostStage.PRODUCTION)
        costing.add_labor_rate_from_personnel_cost(
            manager, 2026, 9, CostStage.PRODUCTION, timezone.localdate() + timedelta(days=2)
        )
    receipt = chain.receipt
    first = receipt.lines.order_by("line_no")[0]
    freight = receipt.extra_costs.get(kind=GoodsReceiptExtraCost.Kind.FREIGHT)
    kept = {
        "id": freight.pk,
        "kind": freight.kind,
        "amount": freight.amount,
        "allocation": freight.allocation,
    }
    with commit():
        inventory.set_receipt_costs(
            staff[SATIN_ALMA],
            receipt,
            lines=[{"id": first.pk, "unit_price": Decimal("1.75")}],
            extra_costs=[kept],
            note="Fatura farkı 7.777,77 TL",
        )


def _purchase_order(users: Mapping[str, User | None], commit: Commit) -> None:
    """Fiyatlı sipariş: iki satır, taslakta satır silme, onaya gönderme ve yönetim onayı (notlarda
    tutar; onay görevinin açıklamasında tutar)."""
    buyer = _user(users, SATIN_ALMA)
    material = raw_material()
    with commit():
        order = draft_order(buyer, [line(material, "1000", "12.3456"), line(material, "10", "5")])
        kept = order.lines.order_by("line_no")[0]
        values = {
            "id": kept.pk,
            "material": material,
            "quantity": kept.quantity,
            "unit": kept.unit,
            "unit_price": kept.unit_price,
            "expected_date": kept.expected_date,
        }
        purchasing.update_order(buyer, order, {}, [values])
        order = purchasing.submit_for_approval(buyer, order)
        purchasing.approve_order(_user(users, YONETIM), order)


def _incident_and_problem(users: Mapping[str, User | None], commit: Commit) -> None:
    """Yaralanmalı olay (bildirenin yorumu ve fotoğrafı, yönetimin incelemesi); sorun bildirimi
    ve bildirenin yorumu."""
    reporter = _user(users, DEPO)
    photo = SimpleUploadedFile("olay.jpg", b"\xff\xd8\xff" + b"0" * 64, content_type="image/jpeg")
    with commit():
        incident = hse.report_incident(
            reporter,
            {
                "incident_type": Incident.Type.WORK_ACCIDENT,
                "occurred_at": timezone.now() - timedelta(hours=2),
                "place": "Dolum hattı",
                "description": "Elini kapağa sıkıştırdı.",
                "injury": True,
                "injured_person": "Ali Yaralı",
                "severity": Incident.Severity.LOW,
            },
        )
        workflow.add_comment(
            reporter, content_type="hse.incident", object_id=incident.pk, body="Fotoğraf ekledim."
        )
        core.add_attachment(
            reporter,
            target_type="hse.incident",
            object_id=incident.pk,
            file=photo,
            kind=Attachment.Kind.PHOTO,
        )
        hse.start_investigation(_user(users, YONETIM), incident)
    worker = _user(users, URETIM)
    with commit():
        problem = golive.report_problem(
            worker, description="Tartım ekranı donuyor.", page_url="/uretim", page_title="Üretim"
        )
        workflow.add_comment(
            worker,
            content_type="golive.problemreport",
            object_id=problem.pk,
            body="Yeniden denedim, yine oldu.",
        )


def _coding_and_report(users: Mapping[str, User | None], commit: Commit) -> None:
    """Kodlama sistematiği değişikliği ve malzeme kodu değişikliği (admin); rapor indirme."""
    admin = _user(users, ADMIN)
    with commit():
        coding.update_scheme(admin, "document.AT", width=6, note="Atık kaydı numarası 6 haneli")
        masterdata.update_record(
            admin, MaterialFactory.create(), {"code": "SONDA-KOD"}, note="Kod sistematiğine uyum"
        )
    reporting.export_report(_user(users, DEPO), REPORTS["stock-status"], {}, "xlsx")


def build_trail(users: Mapping[str, User | None], commit: Commit) -> None:
    """Bugünkü servislerle temsilî bir denetim izi (olaylar commit sonrası işlenir)."""
    _accounts(users, commit)
    _personnel(users, commit)
    _production_and_costs(users, commit)
    _purchase_order(users, commit)
    _incident_and_problem(users, commit)
    _coding_and_report(users, commit)


# --- kayıtların imzası --------------------------------------------------------------------------


def _leaves(name: str, value: Any) -> dict[str, list[Any]]:
    """Değişikliğin yaprak alanları ve değerleri. Değerler `[eski, yeni]`; iç içe kayıtların
    (silinen satır, ek masraf, sayaçlar) alanları `ad.alan` olarak açılır."""
    if isinstance(value, dict) and value:
        out: dict[str, list[Any]] = {}
        for key, sub in value.items():
            for leaf, values in _leaves(f"{name}.{key}", sub).items():
                out.setdefault(leaf, []).extend(values)
        return out
    pair = value if isinstance(value, list) and len(value) == 2 else [value]
    if any(isinstance(side, dict) and side for side in pair):
        out = {}
        for side in pair:
            if isinstance(side, dict):
                for leaf, values in _leaves(name, side).items():
                    out.setdefault(leaf, []).extend(values)
        return out
    return {name: list(pair)}


def _fields(changes: Mapping[str, Any]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for name, value in changes.items():
        out.update(_leaves(name, value))
    return out


def _present(value: Any) -> bool:
    return value not in (None, "", [], {}, MASK)


def _amount(name: str, values: Iterable[Any]) -> bool:
    """Alan tutar taşıyor mu: tutar alanı ve değeri dolu ya da metninde tutar geçiyor."""
    values = list(values)
    if name.rsplit(".", 1)[-1] in AMOUNT_FIELDS and any(_present(v) for v in values):
        return True
    return any(isinstance(v, str) and MONEY.search(v) for v in values)


def signature(entry: Mapping[str, Any]) -> str:
    """Kaydın kimlik, zaman ve değer içermeyen imzası."""
    fields = _fields(entry["changes"] or {})
    names = ", ".join(
        f"{name}$" if _amount(name, values) else name for name, values in sorted(fields.items())
    )
    note = entry["note"] or ""
    text = f"{entry['content_type'] or '-'} {entry['action']} [{names}]"
    if note:
        text += " note$" if MONEY.search(note) else " note"
    return text


def _amounts(entries: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Görünen tutarlı alanlar (`model alan`) ve tutarlı notlar (`model işlem`)."""
    fields: set[str] = set()
    notes: set[str] = set()
    for entry in entries:
        model = entry["content_type"] or "-"
        changed = _fields(entry["changes"] or {})
        fields.update(
            f"{model} {name}" for name, values in changed.items() if _amount(name, values)
        )
        if MONEY.search(entry["note"] or ""):
            notes.add(f"{model} {entry['action']}")
    return {"fields": sorted(fields), "notes": sorted(notes)}


def _counted(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    counts = Counter(f"{entry['content_type'] or '-'} {entry['action']}" for entry in entries)
    return [name if n == 1 else f"{name} ×{n}" for name, n in sorted(counts.items())]


# --- istekler ------------------------------------------------------------------------------------


def _client(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _list(client: APIClient, **params: str) -> tuple[int, list[dict[str, Any]]]:
    """Bütün sayfalar; okuyamayan için (durum, [])."""
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        response = client.get(URL, {**params, "page": str(page), "page_size": "500"})
        if response.status_code != 200:
            return response.status_code, []
        data = response.json()
        rows.extend(data["results"])
        if not data["next"]:
            return 200, rows
        page += 1


def _detail_targets() -> dict[str, int]:
    """Ayrıntısı denenecek kayıtlar: her tanımın ilk (en eski) kaydı. Kayıtlar veritabanından
    seçilir; böylece bir personadan gizlenen kayıt ayrıntıda da fark olarak görünür."""
    targets: dict[str, int] = {}
    for label, (model, action, field, value) in DETAILS.items():
        entries = AuditLog.objects.filter(action=action)
        if model is None:
            entries = entries.filter(content_type__isnull=True)
        else:
            app_label, _, name = model.partition(".")
            entries = entries.filter(content_type__app_label=app_label, content_type__model=name)
        if field is not None:
            entries = entries.filter(changes__has_key=field)
        if field is not None and value is not None:
            entries = entries.filter(**{f"changes__{field}__1": value})  # [eski, yeni]
        first = entries.order_by("pk").values_list("pk", flat=True).first()
        assert first is not None, f"Kayıt izinde yok: {label}"
        targets[label] = first
    return targets


def trail_cases(clients: Mapping[str, APIClient]) -> dict[str, dict[str, Any]]:
    """Okuma kararı ve ayrıntı her persona için; içerik durumları yalnız okuyabilenler için,
    `trail:` durumları yalnız o imzadaki kaydı görenler için yazılır."""
    cases: dict[str, dict[str, Any]] = {}
    targets = _detail_targets()
    for persona, client in clients.items():
        status, rows = _list(client)
        cases.setdefault("read: list", {})[persona] = status
        for label, pk in targets.items():
            response = client.get(f"{URL}{pk}/")
            shown = signature(response.json()) if response.status_code == 200 else None
            cases.setdefault(f"read: detail {label}", {})[persona] = shown or response.status_code
        if status != 200:
            continue
        cases.setdefault("read: fields", {})[persona] = sorted(rows[0]) if rows else []
        for key, amounts in _amounts(rows).items():
            cases.setdefault(f"amounts: {key}", {})[persona] = amounts
        for name, count in Counter(signature(row) for row in rows).items():
            cases.setdefault(f"trail: {name}", {})[persona] = count
        for term in SEARCHES:
            found_status, found = _list(client, search=term)
            results = _counted(found) if found_status == 200 else found_status
            cases.setdefault(f"search: {term}", {})[persona] = results
    return cases


# --- her model: sentetik kayıtlar ----------------------------------------------------------------


def project_models() -> list[type[models.Model]]:
    """Projenin somut modelleri (test uygulaması hariç), etikete göre sıralı."""
    found = [
        model
        for model in apps.get_models()
        if model._meta.app_config is not None
        and model._meta.app_config.name.startswith("apps.")
        and not model._meta.app_config.name.startswith("apps.core.tests")
        and not model._meta.proxy
    ]
    return sorted(found, key=lambda model: model._meta.label_lower)


def _synthetic_changes(model: type[models.Model]) -> dict[str, list[str]]:
    return {
        field.name: ["eski", "yeni"]
        for field in model._meta.concrete_fields
        if not field.primary_key and field.name not in UNTRACKED
    }


def write_synthetic_entries(actor: User) -> dict[str, dict[str, list[str]]]:
    """Her modele bütün izlenen alanlarıyla birer kayıt (varsa ilk kaydına bağlı)."""
    written: dict[str, dict[str, list[str]]] = {}
    entries = []
    for model in project_models():
        label = model._meta.label_lower
        changes = _synthetic_changes(model)
        written[label] = changes
        first = model._base_manager.order_by("pk").values_list("pk", flat=True).first()
        entries.append(
            AuditLog(
                actor=actor,
                action=AuditLog.Action.UPDATE,
                content_type=ContentType.objects.get_for_model(model),
                object_id=first if isinstance(first, int) else None,
                object_repr=f"{MARKER} {label}",
                changes=changes,
                note=MARKER_NOTE,
            )
        )
    AuditLog.objects.bulk_create(entries)
    return written


def _visibility(written: Mapping[str, list[str]], entry: Mapping[str, Any] | None) -> Any:
    if entry is None:
        return "absent"
    shown = entry["changes"] or {}
    if shown == written and entry["note"] == MARKER_NOTE:
        return "full"
    return {
        "missing": sorted(set(written) - set(shown)),
        "changed": sorted(
            name for name in written if name in shown and shown[name] != written[name]
        ),
        "note": entry["note"] == MARKER_NOTE,
    }


def model_cases(
    clients: Mapping[str, APIClient], written: Mapping[str, dict[str, list[str]]]
) -> dict[str, dict[str, Any]]:
    """Okuyabilen her persona için her modelin sentetik kaydı: `full`, `absent` ya da eksikler."""
    cases: dict[str, dict[str, Any]] = {}
    for persona, client in clients.items():
        status, rows = _list(client, search=MARKER)
        if status != 200:
            continue
        by_model = {row["content_type"]: row for row in rows}
        assert len(by_model) == len(rows), "Bir modelin iki sentetik kaydı görünüyor"
        for label, changes in written.items():
            shown = _visibility(changes, by_model.get(label))
            cases.setdefault(f"model: {label}", {})[persona] = shown
    return cases


# --- anlık görüntü -------------------------------------------------------------------------------

FILE_NOTE = (
    "Okuyamayan persona (bkz. 'read: list') içerik durumlarında yer almaz; 'trail:' durumlarında "
    "o imzadaki kaydı görmeyen persona da yazılmaz. Fark satırındaki <yok> bunu anlatır."
)


def encode(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {"_note": FILE_NOTE, **{case: dict(values) for case, values in cases.items()}}


def decode(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {case: dict(values) for case, values in data.items() if not case.startswith("_")}


def test_audit_log_matches_snapshot(
    django_capture_on_commit_callbacks: Callable[..., AbstractContextManager[Any]],
) -> None:
    users = make_personas()

    def commit() -> AbstractContextManager[Any]:
        return django_capture_on_commit_callbacks(execute=True)

    build_trail(users, commit)
    assert_stock_invariants()
    clients = {persona: _client(user) for persona, user in users.items()}
    cases = trail_cases(clients)
    written = write_synthetic_entries(_user(users, ADMIN))
    assert len(written) == EXPECTED_MODELS, (
        f"Proje modeli sayısı {len(written)} (beklenen {EXPECTED_MODELS}). Yeni modelin denetim "
        "günlüğünde kime görüneceği bir karardır: anlık görüntü ve izin listesi (plan §5.5) ile "
        "birlikte güncellenir."
    )
    cases.update(model_cases(clients, written))
    snapshot.check(NAME, cases, encode=encode, decode=decode)
