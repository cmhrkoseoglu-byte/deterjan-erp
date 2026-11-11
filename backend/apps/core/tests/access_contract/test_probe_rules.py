"""Sonda "rules": kararı servisin verdiği iş kuralları (plan §5.5, 2. parça).

Uç nokta anlık görüntüsü yalnız DRF izin sınıfını görür. Burada uç noktanın geçirdiği ama kararı
servisin (ya da sorgu süzgecinin) verdiği yerler 14 personayla dondurulur:

- D-13 satın alma onayı (limit yok, limit içinde, sınırda, limit üstü, dövizli sipariş, yönetim
  onayındaki sipariş), sipariş ayrıntısındaki `can_approve` ve taslağa geri gönderme;
- satın alma talebini düzenleme ve iptal (kendi talebi ve başkasının);
- şartlı kabulün onayı ve reddi (başkasının önerisi ve kendi önerisi);
- bakım iş emri: her sorumlu birim × her eylem (sorumlu birim kuralı) ve tank temizliği kaydı;
- olay ve sorun bildirimi görünürlüğü (kendi kaydı ve başkasının; API ve kayıt paneli süzgeci);
- iki aşamalı doğrulama zorunluluğu (dört `OTP_REQUIRED_ROLES` ayarıyla).

Her deneme bir kayıt noktasında yapılır ve geri alınır; her persona kaydı aynı durumda dener.
Değer kararın kendisidir ("ok", "403 permission_denied", "400 <kod>"...). Mesaj metni yazılmaz:
planın §8 madde 4'ü mesajları değiştirir.
"""

from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal
from functools import partial
from typing import Any, cast

import pytest
from django.db import models, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core import records
from apps.core.models import User
from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.personas import PERSONAS, make_personas, persona_client
from apps.core.tests.factories import UserFactory
from apps.golive import services as golive
from apps.golive.models import ProblemReport
from apps.hse.models import Incident
from apps.hse.tests.factories import report as report_incident
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import storage_location
from apps.maintenance import services as maintenance
from apps.maintenance.api.views import WorkOrderViewSet
from apps.maintenance.models import ROLE_CHOICES
from apps.masterdata.tests.factories import EquipmentFactory, MaterialFactory, SupplierFactory
from apps.purchasing import services as purchasing
from apps.purchasing.models import PurchaseOrder, PurchaseRequest, PurchasingSettings
from apps.purchasing.tests.factories import draft_order
from apps.purchasing.tests.factories import line as order_line
from apps.quality import services as quality
from apps.quality.models import QualityDecision
from apps.quality.tests.factories import line as spec_line
from apps.quality.tests.factories import quarantined_raw_lot, sample_with_spec

pytestmark = pytest.mark.django_db

NAME = "probe_rules"
API = "/api/v1"
D = Decimal

Users = Mapping[str, User | None]
Cases = dict[str, dict[str, Any]]
Prepare = Callable[[User], None]

# D-13: (durum, limit TL, para birimi, kur, 100 kg'lık satırın birim fiyatı, onaya gönderildi mi).
APPROVAL_CASES: tuple[tuple[str, str | None, str, str, str, bool], ...] = (
    ("limit yok; tutar 1.000 TL", None, "TRY", "1", "10", False),
    ("limit 5.000 TL; tutar 1.000 TL", "5000", "TRY", "1", "10", False),
    ("limit 1.000 TL; tutar 1.000 TL", "1000", "TRY", "1", "10", False),
    ("limit 999,99 TL; tutar 1.000 TL", "999.99", "TRY", "1", "10", False),
    ("limit 1.000 TL; tutar 100 EUR x 40 = 4.000 TL", "1000", "EUR", "40", "1", False),
    ("yönetim onayında; limit 500 TL; tutar 1.000 TL", "500", "TRY", "1", "10", True),
)

# Sorumlu birim kuralı (`maintenance.services._can_work`) olan iş emri eylemleri → istek gövdesi.
WORK_ORDER_ACTIONS: dict[str, dict[str, Any]] = {
    "start": {},
    "complete": {"work_done": "Bakım yapıldı"},
    "cancel": {"reason": "Mükerrer kayıt"},
    "parts": {"quantity": "1", "description": "Conta", "unit_text": "adet"},
}

# Satır kuralıyla görünen kayıt türleri (`core.records`'ta `visible` süzgeci olanlar):
# kayıt türü → (model, API yolu).
ROW_RULES: dict[str, tuple[type[models.Model], str]] = {
    "hse.incident": (Incident, "hse/incidents"),
    "golive.problemreport": (ProblemReport, "golive/problems"),
}
VISIBILITY_PARTS = ("list", "retrieve [kendi]", "retrieve [başkasının]", "visible")

# Test ayarı (boş), karar 11'in hedefi (admin, yonetim); "yonetim" tek başına süper kullanıcı
# kuralını, "depo" pasif kullanıcıyı gösterir.
OTP_SETTINGS: tuple[tuple[str, ...], ...] = ((), ("admin", "yonetim"), ("yonetim",), ("depo",))
OTP_PARTS = ("me.otp_setup_required", "security.otp_required", "api_block")

# D-13: 6 onay + 6 can_approve + taslağa geri gönderme; talep 4; şartlı kabul 4;
# bakım 5 birim × 4 eylem + temizlik; görünürlük 2 tür × 4; iki aşamalı doğrulama 4 ayar × 3.
EXPECTED_CASES = 13 + 4 + 4 + 21 + 8 + 12


class _Rollback(Exception):
    """Denemenin yazdıklarını geri almak için fırlatılır."""


def attempt(call: Callable[[], Any]) -> Any:
    """`call`'ı bir kayıt noktasında çalıştırır, sonucunu döner ve yazdıklarını geri alır."""
    results: list[Any] = []
    try:
        with transaction.atomic():
            results.append(call())
            raise _Rollback
    except _Rollback:
        pass
    return results[0]


def client_for(user: User | None) -> APIClient:
    return persona_client(user)


def outcome(response: Any) -> str:
    """Yanıtın kararı: 2xx için "ok", değilse durum ve hata kodu."""
    if response.status_code < 300:
        return "ok"
    try:
        code = response.json().get("code", "")
    except ValueError:
        code = ""
    return f"{response.status_code} {code}".strip()


def each(users: Users, call: Callable[[User | None], Any]) -> dict[str, Any]:
    """Her persona için `call(user)`; her deneme ayrı ayrı geri alınır."""
    return {persona: attempt(partial(call, user)) for persona, user in users.items()}


def request(
    method: str, path: str, body: Mapping[str, Any] | None = None, prepare: Prepare | None = None
) -> Callable[[User | None], str]:
    """Personanın isteğini deneyen çağrı. `prepare` istekten önce kaydı personaya bağlar."""

    def call(user: User | None) -> str:
        if prepare is not None and user is not None:
            prepare(user)
        send = getattr(client_for(user), method)
        return outcome(send(path, dict(body or {}), format="json"))

    return call


def owned_by(model: type[models.Model], pk: int, field: str) -> Prepare:
    """Kaydı (yalnız denemenin içinde) personaya bağlar: talebi açan, kararı öneren..."""

    def prepare(user: User) -> None:
        model._default_manager.filter(pk=pk).update(**{field: user})

    return prepare


def _user(username: str, role: str) -> User:
    return cast(User, UserFactory(username=username, roles=[role]))


# --- D-13 satın alma onayı ---------------------------------------------------------------------


def _can_approve(path: str, user: User | None) -> Any:
    """Sipariş ayrıntısındaki `can_approve`; siparişi okuyamayana yanıtın kararı."""
    response = client_for(user).get(path)
    return response.json()["can_approve"] if response.status_code == 200 else outcome(response)


def approval_cases(users: Users) -> Cases:
    """D-13 (`purchasing.services.can_approve`): onay uç noktası satın alma ve yönetime açık,
    limit kararını servis verir. Taslağa geri göndermeyi servis yalnız yönetime bırakır."""
    buyer = _user("sonda_satin_alma", "satin_alma")
    settings_pk = purchasing.get_settings().pk
    material = MaterialFactory.create()
    supplier = SupplierFactory.create()
    cases: Cases = {}
    pending: PurchaseOrder | None = None
    for label, limit, currency, rate, price, submitted in APPROVAL_CASES:
        PurchasingSettings.objects.filter(pk=settings_pk).update(
            approval_limit_try=None if limit is None else D(limit)
        )
        order = draft_order(
            buyer,
            [order_line(material, quantity="100", price=price)],
            supplier=supplier,
            currency=currency,
            exchange_rate=D(rate),
        )
        if submitted:
            order = pending = purchasing.submit_for_approval(buyer, order)
        path = f"{API}/purchasing/orders/{order.pk}/"
        cases[f"purchasing.order.approve [{label}]"] = each(
            users, request("post", f"{path}approve/")
        )
        cases[f"purchasing.order.can_approve [{label}]"] = each(users, partial(_can_approve, path))
    assert pending is not None
    cases["purchasing.order.return_to_draft [yönetim onayında]"] = each(
        users,
        request(
            "post",
            f"{API}/purchasing/orders/{pending.pk}/return-to-draft/",
            {"note": "Fiyat yeniden görüşülecek"},
        ),
    )
    return cases


# --- satın alma talebi -------------------------------------------------------------------------


def request_cases(users: Users) -> Cases:
    """Talebi açan kişi ya da satın alma ve yönetim düzenler ve iptal eder
    (`purchasing.services._can_edit_request`); uç nokta talep açan bütün rollere açıktır."""
    requester = _user("sonda_planlama", "planlama")
    purchase_request = purchasing.create_request(
        requester,
        {
            "material": MaterialFactory.create(),
            "quantity": D("10"),
            "need_date": date(2026, 12, 1),
            "reason": "Stok azaldı",
        },
    )
    path = f"{API}/purchasing/requests/{purchase_request.pk}/"
    own = owned_by(PurchaseRequest, purchase_request.pk, "created_by")
    update = {"reason": "Miktar güncellendi"}
    cancel = {"reason": "Gerek kalmadı"}
    return {
        "purchasing.request.update [başkasının talebi]": each(
            users, request("patch", path, update)
        ),
        "purchasing.request.update [kendi talebi]": each(
            users, request("patch", path, update, own)
        ),
        "purchasing.request.cancel [başkasının talebi]": each(
            users, request("post", f"{path}cancel/", cancel)
        ),
        "purchasing.request.cancel [kendi talebi]": each(
            users, request("post", f"{path}cancel/", cancel, own)
        ),
    }


# --- şartlı kabul ------------------------------------------------------------------------------


def conditional_release_cases(users: Users) -> Cases:
    """Şartlı kabulün onayı ve reddi (`quality.services.review_conditional_release`). "Kendi
    önerisi": kararı öneren (`decided_by`) personanın kendisidir (planın §8 madde 5'i)."""
    lab = _user("sonda_laboratuvar", "laboratuvar")
    lot, _quarantine = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    quality.record_result(lab, sample, spec_line(sample, "PH"), numeric_value=D("8.3"))
    quality.record_result(lab, sample, spec_line(sample, "GORUNUS"), text_value="Berrak")
    decision = quality.decide(
        lab,
        sample,
        QualityDecision.Decision.CONDITIONAL_RELEASE,
        "pH sınırda",
        release_location=storage_location(),
    )
    path = f"{API}/quality/decisions/{decision.pk}/review/"
    own = owned_by(QualityDecision, decision.pk, "decided_by")
    approve = {"approve": True, "note": "Uygun"}
    refuse = {"approve": False, "note": "Uygun değil"}
    return {
        "quality.conditional_release.approve [başkasının önerisi]": each(
            users, request("post", path, approve)
        ),
        "quality.conditional_release.approve [kendi önerisi]": each(
            users, request("post", path, approve, own)
        ),
        "quality.conditional_release.refuse [başkasının önerisi]": each(
            users, request("post", path, refuse)
        ),
        "quality.conditional_release.refuse [kendi önerisi]": each(
            users, request("post", path, refuse, own)
        ),
    }


# --- bakım: sorumlu birim ----------------------------------------------------------------------


def maintenance_cases(users: Users) -> Cases:
    """İş emrini sorumlu birim ya da yönetim yürütür (`maintenance.services._can_work`); uç
    noktalar bakımı okuyan bütün birimlere açıktır. Tank temizliğini üretim ve yönetim girer."""
    actions = {cast(Any, action).url_path for action in WorkOrderViewSet.get_extra_actions()}
    assert actions == set(WORK_ORDER_ACTIONS), f"İş emri eylemleri değişti: {sorted(actions)}"
    roles = [role for role, _label in ROLE_CHOICES]
    assert len(roles) == 5, f"Sorumlu birim seçenekleri değişti: {roles}"
    manager = _user("sonda_yonetim", "yonetim")
    equipment = EquipmentFactory.create()
    cases: Cases = {}
    for role in roles:
        order = maintenance.create_work_order(
            manager,
            {
                "equipment": equipment,
                "title": f"Periyodik bakım ({role})",
                "responsible_role": role,
            },
        )
        for action, body in WORK_ORDER_ACTIONS.items():
            path = f"{API}/maintenance/work-orders/{order.pk}/{action}/"
            cases[f"maintenance.work_order.{action} [sorumlu birim: {role}]"] = each(
                users, request("post", path, body)
            )
    tank = EquipmentFactory.create()
    assert tank.is_tank
    cases["maintenance.cleaning.record [tank]"] = each(
        users,
        request(
            "post", f"{API}/maintenance/cleanings/", {"equipment": tank.pk, "work_done": "Yıkandı"}
        ),
    )
    return cases


# --- olay ve sorun bildirimi görünürlüğü --------------------------------------------------------


def _listed(response: Any, names: Mapping[int, str]) -> Any:
    if response.status_code != 200:
        return outcome(response)
    data = response.json()
    rows = data["results"] if isinstance(data, dict) else data
    return sorted(names.get(row["id"], "diğer") for row in rows)


def _visibility(label: str, own_pk: int, other_pk: int, user: User | None) -> dict[str, Any]:
    """Kendi kaydı (denemede `created_by` = persona) ve başkasının kaydı: API listesi, ayrıntı ve
    kayıt panelinin `visible` süzgeci (`core.records`)."""
    model, endpoint = ROW_RULES[label]
    access = records.record_access(label)
    assert access is not None and access.visible is not None
    if user is not None:
        model._default_manager.filter(pk=own_pk).update(created_by=user)
    names = {own_pk: "kendi", other_pk: "başkasının"}
    client = client_for(user)
    base = f"{API}/{endpoint}/"
    # Süzgeç anonimi de kabul eder (`getattr(user, ...)`); kayıt paneli onu önceden reddeder.
    visible = cast(Any, access.visible)(user, model._default_manager.all())
    return {
        "list": _listed(client.get(base), names),
        "retrieve [kendi]": outcome(client.get(f"{base}{own_pk}/")),
        "retrieve [başkasının]": outcome(client.get(f"{base}{other_pk}/")),
        "visible": sorted(names.get(pk, "diğer") for pk in visible.values_list("pk", flat=True)),
    }


def visibility_cases(users: Users) -> Cases:
    """Olayı bildiren ve yönetim görür (`hse.services.incidents_visible_to`); sorun bildirimini
    bildiren ve admin görür (`golive.selectors.problem_reports_visible_to`)."""
    registered = {
        label
        for label in records.registered_record_types()
        if (access := records.record_access(label)) is not None and access.visible is not None
    }
    assert registered == set(ROW_RULES), f"Satır kurallı kayıt türleri değişti: {registered}"
    reporter = _user("sonda_depo", "depo")
    created: dict[str, list[models.Model]] = {
        "hse.incident": [report_incident(reporter, place=place) for place in ("Depo", "Dolum")],
        "golive.problemreport": [
            golive.report_problem(reporter, description=text)
            for text in ("Ekran açılmıyor", "Etiket basılmıyor")
        ],
    }
    cases: Cases = {}
    for label in ROW_RULES:
        own, other = created[label]
        observed = each(users, partial(_visibility, label, own.pk, other.pk))
        for part in VISIBILITY_PARTS:
            cases[f"{label}.{part}"] = {persona: value[part] for persona, value in observed.items()}
    return cases


# --- iki aşamalı doğrulama ---------------------------------------------------------------------


def _otp(user: User | None) -> dict[str, Any]:
    """`/auth/me/` ve `/auth/security/` bayrakları; oturumla açılan istekte ara katmanın engeli
    (`core.middleware`, `security.otp_setup_required`). Kimsenin doğrulayıcısı kurulu değildir."""
    client = client_for(user)
    me = client.get(f"{API}/auth/me/")
    status = client.get(f"{API}/auth/security/")
    session = APIClient()
    if user is not None:
        session.force_login(user)
    return {
        "me.otp_setup_required": (
            me.json()["otp_setup_required"] if me.status_code == 200 else outcome(me)
        ),
        "security.otp_required": (
            status.json()["otp_required"] if status.status_code == 200 else outcome(status)
        ),
        "api_block": outcome(session.get(f"{API}/masterdata/company/")),
    }


def otp_cases(users: Users) -> Cases:
    """Kimin iki aşamalı doğrulama kurması gerekir (`core.security.otp_required_for`)."""
    cases: Cases = {}
    for required in OTP_SETTINGS:
        label = ", ".join(required) or "boş"
        with override_settings(OTP_REQUIRED_ROLES=list(required)):
            observed = each(users, _otp)
        for part in OTP_PARTS:
            cases[f"core.otp.{part} [OTP_REQUIRED_ROLES: {label}]"] = {
                persona: value[part] for persona, value in observed.items()
            }
    return cases


# --- test --------------------------------------------------------------------------------------


def current_decisions() -> Cases:
    users = make_personas()
    cases: Cases = {}
    for collect in (
        approval_cases,
        request_cases,
        conditional_release_cases,
        maintenance_cases,
        visibility_cases,
        otp_cases,
    ):
        part = collect(users)
        assert not set(part) & set(cases), sorted(set(part) & set(cases))
        cases.update(part)
    assert_stock_invariants()
    return cases


def test_service_rules_match_snapshot() -> None:
    cases = current_decisions()
    assert len(cases) == EXPECTED_CASES, len(cases)
    snapshot.check(NAME, cases)


def test_snapshot_covers_every_rule() -> None:
    """Anlık görüntüde her kural ve her personanın bir değeri var."""
    if snapshot.updating():
        pytest.skip("anlık görüntü yazılıyor")
    cases = snapshot.load(NAME)
    assert len(cases) == EXPECTED_CASES, len(cases)
    for case, values in cases.items():
        assert set(values) == set(PERSONAS), case
