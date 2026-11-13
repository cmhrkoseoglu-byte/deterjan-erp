"""Kişiye özel ayarla bakım (docs/plan/kisi-yetkileri.md §10, 5. adım): kaldırılan yetki uç
noktada ve serviste düşer, okuma açık kalır. İş emrini sorumlu birim yürütür; öteki birimlerin
iş emirleri "Tüm birimlerin iş emirlerini yürütme" ister. Tank temizliği kaydında açılan iş
emrinin tamamlanması ardıl adımdır, sorumlu birim kuralıyla denetlenmez (plan §5.4)."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.core import records
from apps.core.access import CHANGE, VIEW
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.maintenance import services
from apps.maintenance.access import (
    ANY_UNIT,
    BREAKDOWNS,
    CALIBRATION,
    CLEANINGS,
    DOWNTIMES,
    PLANS,
    SETTINGS,
    UNCLEANED,
    WORK_ORDERS,
)
from apps.maintenance.models import Downtime, MaintenanceWorkOrder
from apps.maintenance.tests.factories import plan
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import BulkMaterialFactory, EquipmentFactory
from apps.production.access import BATCHES

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
Status = MaintenanceWorkOrder.Status
BASE = "/api/v1/maintenance"


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def bulk() -> Material:
    return BulkMaterialFactory.create()


def work_order(actor: User, responsible_role: str) -> MaintenanceWorkOrder:
    return services.create_work_order(
        actor,
        {
            "equipment": EquipmentFactory.create(),
            "title": "Periyodik bakım",
            "responsible_role": responsible_role,
        },
    )


def test_removing_any_unit_leaves_only_own_units_work_orders(manager: User) -> None:
    """Yönetimden "Tüm birimlerin iş emirlerini yürütme" kaldırılınca başka birimin iş emrini
    yürütemez (uç nokta Bakım iş emirleri: Değiştirir ile geçer, servis reddeder); kendi biriminin
    (sorumlu rol yönetim) iş emrini yürütür, iş emirlerini okur."""
    other = work_order(manager, "uretim")
    own = work_order(manager, "yonetim")
    client = api(override(manager, ANY_UNIT.key, CHANGE))

    assert client.get(f"{BASE}/work-orders/").status_code == 200
    assert client.get(f"{BASE}/work-orders/{other.pk}/").status_code == 200
    refused = client.post(f"{BASE}/work-orders/{other.pk}/start/")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": ANY_UNIT.key, "level": CHANGE}]
    cancel = client.post(f"{BASE}/work-orders/{other.pk}/cancel/", {"reason": "x"}, format="json")
    assert cancel.status_code == 403
    with pytest.raises(MissingAccess):
        services.complete_work_order(manager, other, work_done="x", checklist=[])
    other.refresh_from_db()
    assert other.status == Status.OPEN

    started = client.post(f"{BASE}/work-orders/{own.pk}/start/")
    assert started.status_code == 200, started.json()
    assert started.json()["status"] == Status.IN_PROGRESS


def test_granted_any_unit_lets_a_unit_run_other_units_work_orders(manager: User, lab: User) -> None:
    order = work_order(manager, "uretim")
    assert api(lab).post(f"{BASE}/work-orders/{order.pk}/start/").status_code == 403

    started = api(override(lab, ANY_UNIT.key, CHANGE, effect="grant")).post(
        f"{BASE}/work-orders/{order.pk}/start/"
    )
    assert started.status_code == 200, started.json()
    assert started.json()["status"] == Status.IN_PROGRESS


def test_removing_work_order_change_stops_own_units_work_orders_at_the_endpoint(
    manager: User, operator: User
) -> None:
    """Sorumlu birimde olmak yetmez: uç nokta bugünkü gibi "Bakım iş emirleri: Değiştirir"
    ister."""
    order = work_order(manager, "uretim")
    client = api(override(operator, WORK_ORDERS.key, CHANGE))

    assert client.get(f"{BASE}/work-orders/{order.pk}/").status_code == 200
    refused = client.post(f"{BASE}/work-orders/{order.pk}/start/")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": WORK_ORDERS.key, "level": CHANGE}]


def test_cleaning_by_a_granted_person_completes_the_work_order_without_responsible_unit(
    lab: User, filler: User
) -> None:
    """Plan §5.4 giriş noktası kuralı: "Tank temizliği: Değiştirir" eklenen laboratuvar kişisi
    temizlik kaydeder; açılan iş emrinin (sorumlu birim üretim) tamamlanması, kişinin sorumlu
    birimde olmamasına ve "Tüm birimlerin iş emirlerini yürütme"si olmamasına bakmaz."""
    tank = EquipmentFactory.create()
    assert tank.is_tank
    body = {"equipment": tank.pk, "work_done": "Yıkandı"}
    assert api(lab).post(f"{BASE}/cleanings/", body, format="json").status_code == 403

    response = api(override(lab, CLEANINGS.key, CHANGE, effect="grant")).post(
        f"{BASE}/cleanings/", body, format="json"
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == Status.COMPLETED
    assert response.json()["responsible_role"] == "uretim"

    order = services.record_cleaning(
        override(filler, CLEANINGS.key, CHANGE, effect="grant"), tank, work_done="Yıkandı"
    )
    assert order.status == Status.COMPLETED
    assert order.completed_by == filler


def test_removing_plans_change_stops_plans_and_manual_work_orders(operator: User) -> None:
    existing = plan(operator, EquipmentFactory.create())
    client = api(override(operator, PLANS.key, CHANGE))
    body = {"equipment": EquipmentFactory.create().pk, "title": "Bakım", "interval_days": 30}

    assert client.get(f"{BASE}/plans/").status_code == 200
    assert client.get(f"{BASE}/plans/{existing.pk}/").status_code == 200
    refused = client.post(f"{BASE}/plans/", body, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": PLANS.key, "level": CHANGE}]
    assert client.post(f"{BASE}/plans/{existing.pk}/deactivate/").status_code == 403
    work = {"equipment": body["equipment"], "title": "Elle"}
    assert client.post(f"{BASE}/work-orders/", work, format="json").status_code == 403
    # HEAD ve OPTIONS bugünkü gibi yazma yetkisiyle denetlenir.
    assert client.head(f"{BASE}/plans/").status_code == 403
    assert client.options(f"{BASE}/plans/").status_code == 403
    with pytest.raises(MissingAccess):
        services.set_plan_active(operator, existing, False)


def test_downtime_records_stay_readable_for_anyone_with_a_role(operator: User) -> None:
    """Duruş kayıtlarının "rolü olan herkes" okuması kişiden kapatılamaz (plan §3.12, §4);
    Görür'ü kaldırılan kişi kayıtları okur, duruş özetini ve yazmayı kaybeder."""
    downtime = services.start_downtime(operator, EquipmentFactory.create(), "OTHER")
    client = api(override(operator, DOWNTIMES.key, VIEW))

    assert client.get(f"{BASE}/downtimes/").status_code == 200
    assert client.get(f"{BASE}/downtimes/{downtime.pk}/").status_code == 200
    summary = client.get(f"{BASE}/downtime-summary/")
    assert summary.status_code == 403
    assert summary.json()["required"] == [{"key": DOWNTIMES.key, "level": VIEW}]
    ended = client.post(f"{BASE}/downtimes/{downtime.pk}/end/", {"note": "x"}, format="json")
    assert ended.status_code == 403
    assert client.head(f"{BASE}/downtimes/").status_code == 403
    with pytest.raises(MissingAccess):
        services.end_downtime(operator, downtime)
    downtime.refresh_from_db()
    assert downtime.ended_at is None


def test_equipment_status_reads_with_calibration_or_batch_weighing(
    operator: User, lab: User, depo: User
) -> None:
    """Plan §5.4: kalibrasyon ve tank temizliği durumu "Kalibrasyon: Görür" ya da "Şarj ve
    tartım: Değiştirir" ile okunur."""
    params = {"equipment": EquipmentFactory.create().pk, "product": bulk().pk}
    weigher = api(override(operator, CALIBRATION.key, VIEW))
    assert weigher.get(f"{BASE}/calibration/").status_code == 200
    assert weigher.get(f"{BASE}/cleaning-check/", params).status_code == 200

    reader = api(override(lab, CALIBRATION.key, VIEW))
    refused = reader.get(f"{BASE}/calibration/")
    assert refused.status_code == 403
    assert refused.json() == {
        "code": "permission_denied",
        "detail": "Bu işlem için yetkiniz yok.",
        "required": [
            {"key": CALIBRATION.key, "level": VIEW},
            {"key": BATCHES.key, "level": CHANGE},
        ],
    }
    assert reader.get(f"{BASE}/cleaning-check/", params).status_code == 403

    granted = api(override(depo, CALIBRATION.key, VIEW, effect="grant"))
    assert granted.get(f"{BASE}/calibration/").status_code == 200
    # Bakım'ı gören herkes bakım ayarlarının değerlerini okur; değiştiremez.
    assert granted.get(f"{BASE}/settings/").status_code == 200
    assert granted.patch(f"{BASE}/settings/", {"plan_lead_days": 3}).status_code == 403
    assert granted.get(f"{BASE}/plans/").status_code == 403


def test_settings_and_changeovers_follow_their_sections(manager: User, lab: User) -> None:
    client = api(override(manager, SETTINGS.key, CHANGE))
    assert client.get(f"{BASE}/settings/").status_code == 200
    refused = client.patch(f"{BASE}/settings/", {"plan_lead_days": 3})
    assert refused.status_code == 403
    assert refused.json()["required"] == [{"key": SETTINGS.key, "level": CHANGE}]
    assert client.head(f"{BASE}/settings/").status_code == 403

    rule = services.create_changeover_rule(lab, {"from_product": bulk(), "to_product": bulk()})
    tester = api(override(lab, UNCLEANED.key, CHANGE))
    assert tester.get(f"{BASE}/changeover-rules/").status_code == 200
    assert tester.post(f"{BASE}/changeover-rules/{rule.pk}/deactivate/").status_code == 403
    assert tester.head(f"{BASE}/changeover-rules/").status_code == 403


def test_record_panel_follows_work_order_read(manager: User, filler: User) -> None:
    """Yorum, geçmiş ve ek: iş emrini "Bakım iş emirleri" okuması olan görür."""
    order = work_order(manager, "dolum")
    assert records.can_view(filler, order)
    assert not records.can_view(override(filler, WORK_ORDERS.key, VIEW), order)


def test_each_service_names_its_section_and_level(
    manager: User, lab: User, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi planın §3.12 tablosundaki bölüme ve düzeye bağlıdır: rolü olmayan kişi
    her birinde, işin kurallarından önce, o yetkiyi söyleyen 403 alır."""
    nobody = make_user()
    equipment = EquipmentFactory.create()
    existing = plan(manager, EquipmentFactory.create())
    order = work_order(manager, "uretim")
    downtime = services.start_downtime(manager, EquipmentFactory.create(), "OTHER")
    rule = services.create_changeover_rule(lab, {"from_product": bulk(), "to_product": bulk()})
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        ("update_settings", lambda: services.update_settings(nobody, {}), (SETTINGS.key, CHANGE)),
        ("create_plan", lambda: services.create_plan(nobody, {}), (PLANS.key, CHANGE)),
        ("update_plan", lambda: services.update_plan(nobody, existing, {}), (PLANS.key, CHANGE)),
        (
            "set_plan_active",
            lambda: services.set_plan_active(nobody, existing, False),
            (PLANS.key, CHANGE),
        ),
        ("create_work_order", lambda: services.create_work_order(nobody, {}), (PLANS.key, CHANGE)),
        (
            "report_breakdown",
            lambda: services.report_breakdown(nobody, equipment, "x"),
            (BREAKDOWNS.key, CHANGE),
        ),
        (
            "start_work_order",
            lambda: services.start_work_order(nobody, order),
            (ANY_UNIT.key, CHANGE),
        ),
        (
            "complete_work_order",
            lambda: services.complete_work_order(nobody, order, work_done="x"),
            (ANY_UNIT.key, CHANGE),
        ),
        (
            "cancel_work_order",
            lambda: services.cancel_work_order(nobody, order, "x"),
            (ANY_UNIT.key, CHANGE),
        ),
        (
            "add_part",
            lambda: services.add_part(nobody, order, quantity=D("1"), description="x"),
            (ANY_UNIT.key, CHANGE),
        ),
        (
            "record_cleaning",
            lambda: services.record_cleaning(nobody, equipment, work_done="x"),
            (CLEANINGS.key, CHANGE),
        ),
        (
            "start_downtime",
            lambda: services.start_downtime(nobody, equipment, "OTHER"),
            (DOWNTIMES.key, CHANGE),
        ),
        (
            "end_downtime",
            lambda: services.end_downtime(nobody, downtime),
            (DOWNTIMES.key, CHANGE),
        ),
        (
            "create_changeover_rule",
            lambda: services.create_changeover_rule(nobody, {}),
            (UNCLEANED.key, CHANGE),
        ),
        (
            "set_changeover_active",
            lambda: services.set_changeover_active(nobody, rule, False),
            (UNCLEANED.key, CHANGE),
        ),
    ]

    wrong: list[str] = []
    for name, call, required in calls:
        try:
            call()
        except MissingAccess as error:
            if error.required != (required,):
                wrong.append(f"{name}: {error.required} != {(required,)}")
        else:
            wrong.append(f"{name}: reddedilmedi")
    assert not wrong, "\n".join(wrong)
    order.refresh_from_db()
    assert order.status == Status.OPEN
    assert not Downtime.objects.filter(equipment=equipment).exists()


def test_unrouted_methods_keep_todays_rule(
    manager: User,
    operator: User,
    planner: User,
    depo: User,
    lab: User,
    make_user: Callable[..., User],
) -> None:
    """Görünümün karşılamadığı metotlar ve yalnız GET'i okuma sayan görünümlerin HEAD ve
    OPTIONS'ı (sözleşme testinin dışındaki yollar dahil) bugünkü kararı verir: yazma rolüyle
    denetlenir, sonra 405 döner; karşılanmayan yoldaki GET okuma kuralıyla."""
    existing = plan(manager, EquipmentFactory.create())
    order = work_order(manager, "uretim")
    downtime = services.start_downtime(manager, EquipmentFactory.create(), "OTHER")
    production, planning, warehouse, testing = api(operator), api(planner), api(depo), api(lab)
    management, roleless = api(manager), api(make_user())

    cases: list[tuple[APIClient, str, str, int]] = [
        # Planlar: yazma, HEAD, OPTIONS PLAN_ROLES (planlama hariç); karşılanmayan GET okuma.
        (production, "delete", f"plans/{existing.pk}/", 405),
        (planning, "delete", f"plans/{existing.pk}/", 403),
        (planning, "get", f"plans/{existing.pk}/activate/", 405),
        (warehouse, "get", f"plans/{existing.pk}/activate/", 403),
        (planning, "head", f"plans/{existing.pk}/activate/", 403),
        (production, "head", f"plans/{existing.pk}/activate/", 405),
        (planning, "get", "plans/", 200),
        (planning, "head", "plans/", 403),
        (production, "head", "plans/", 200),
        # İş emirleri: yalnız create yazma rolünde; öteki metotlar bakım birimlerinde.
        (planning, "delete", f"work-orders/{order.pk}/", 405),
        (warehouse, "delete", f"work-orders/{order.pk}/", 403),
        (planning, "get", f"work-orders/{order.pk}/start/", 405),
        (planning, "head", "work-orders/", 200),
        (warehouse, "head", "work-orders/", 403),
        # Duruşlar: GET rolü olan herkes; HEAD, OPTIONS ve öteki metotlar duruş girenler.
        (warehouse, "get", "downtimes/", 200),
        (warehouse, "head", "downtimes/", 403),
        (warehouse, "options", "downtimes/", 403),
        (warehouse, "get", f"downtimes/{downtime.pk}/end/", 405),
        (roleless, "get", f"downtimes/{downtime.pk}/end/", 403),
        (warehouse, "put", f"downtimes/{downtime.pk}/", 403),
        (production, "put", f"downtimes/{downtime.pk}/", 405),
        # Temizliksiz geçişler: HEAD ve öteki metotlar yalnız laboratuvar.
        (production, "head", "changeover-rules/", 403),
        (testing, "head", "changeover-rules/", 200),
        (production, "delete", "changeover-rules/1/", 403),
        (testing, "delete", "changeover-rules/1/", 405),
        # Ayarlar: GET Bakım'ı gören; HEAD, OPTIONS ve öteki metotlar yönetim.
        (production, "head", "settings/", 403),
        (management, "head", "settings/", 200),
        (production, "post", "settings/", 403),
        (management, "post", "settings/", 405),
        # Tek kurallı uç noktalar: her metot aynı kuralla.
        (roleless, "get", "breakdowns/", 403),
        (warehouse, "get", "breakdowns/", 405),
        (warehouse, "options", "breakdowns/", 200),
        (warehouse, "post", "calibration/", 403),
        (production, "post", "calibration/", 405),
        (planning, "post", "cleaning-check/", 405),
        (warehouse, "get", "cleanings/", 403),
        (planning, "get", "cleanings/", 405),
        (warehouse, "post", "downtime-summary/", 403),
        (planning, "post", "downtime-summary/", 405),
        (api(None), "get", "plans/", 401),
        (api(None), "delete", f"plans/{existing.pk}/", 401),
    ]
    wrong: list[str] = []
    for client, method, path, expected in cases:
        status = getattr(client, method)(f"{BASE}/{path}").status_code
        if status != expected:
            user = getattr(client.handler, "_force_user", None)
            wrong.append(f"{method.upper()} {path} [{user}]: {status} != {expected}")
    assert not wrong, "\n".join(wrong)
