"""Kişiye özel ayarla İSG ve çevre (docs/plan/kisi-yetkileri.md §3.13, §10 5. adım): olaylar ve
ekler bölüm ve düzeyle denetlenir; olay bildirimi ve tehlike bilgisi okuması kişiden
kaldırılamaz; bildiren kendi olayını görür ve fotoğraf ekler (satır kuralı)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import records
from apps.core.access import CHANGE, VIEW
from apps.core.models import AccessOverride, User
from apps.core.permissions import MissingAccess
from apps.hse import services
from apps.hse.access import (
    HAZARDS,
    INCIDENT_REPORT,
    INCIDENTS,
    SDS,
    SETTINGS,
    STORAGE,
    SUMMARY,
    WASTE,
)
from apps.hse.models import HazardClass, Incident
from apps.hse.tests.factories import (
    contractor,
    hazardous_material,
    incident_data,
    report,
    sds,
    statement,
    waste_data,
)
from apps.inventory.tests.factories import storage_location
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = pytest.mark.usefixtures("invariants")
BASE = "/api/v1/hse"


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def required(response: Any) -> list[dict[str, str]]:
    return list(response.json()["required"])


def test_incidents_revoked_from_manager_leaves_own_reports(
    manager: User, depo: User, make_user: Callable[..., User]
) -> None:
    """Yönetimden Olaylar ve kazalar kaldırılınca: başkasının olayı görünmez, incelenemez,
    fotoğrafı eklenemez; kendi bildirdiği olay ve olay bildirimi (kilitli) açık kalır."""
    others = report(depo)
    revoked = override(make_user("yonetim"), INCIDENTS.key, VIEW)
    own = report(revoked)
    client = api(revoked)

    listing = client.get(f"{BASE}/incidents/")
    assert listing.status_code == 200
    assert [row["id"] for row in listing.json()["results"]] == [own.pk]
    assert client.get(f"{BASE}/incidents/{others.pk}/").status_code == 404
    refused = client.post(f"{BASE}/incidents/{own.pk}/investigate/", {}, format="json")
    assert refused.status_code == 403
    assert required(refused) == [{"key": INCIDENTS.key, "level": CHANGE}]
    with pytest.raises(MissingAccess):
        services.start_investigation(revoked, own)
    assert client.get(f"{BASE}/summary/").status_code == 200  # İSG özeti ayrı bölüm

    created = client.post(
        f"{BASE}/incidents/", {**incident_data(), "occurred_at": timezone.now()}, format="json"
    )
    assert created.status_code == 201, created.json()
    assert services.can_attach_incident(revoked, own)
    assert not services.can_attach_incident(revoked, others)
    assert records.can_view(revoked, own)
    assert not records.can_view(revoked, others)
    # Değişmeyen yönetici hepsini görür.
    assert api(manager).get(f"{BASE}/incidents/").json()["count"] == Incident.objects.count()


def test_incident_change_revoked_keeps_full_list(
    depo: User, make_user: Callable[..., User]
) -> None:
    others = report(depo)
    reader = override(make_user("yonetim"), INCIDENTS.key, CHANGE)
    client = api(reader)
    assert client.get(f"{BASE}/incidents/{others.pk}/").status_code == 200
    refused = client.post(f"{BASE}/incidents/{others.pk}/close/", {}, format="json")
    assert refused.status_code == 403
    assert required(refused) == [{"key": INCIDENTS.key, "level": CHANGE}]
    # HEAD ve OPTIONS bugünkü gibi Değiştirir ister.
    assert client.head(f"{BASE}/incidents/").status_code == 403
    assert client.options(f"{BASE}/incidents/").status_code == 403
    assert not services.can_attach_incident(reader, others)


def test_incident_report_is_locked(lab: User) -> None:
    """Olay bildirimi kilitlidir: kişiden kaldırılan ayar yok sayılır."""
    override(lab, INCIDENT_REPORT.key, CHANGE)
    override(lab, INCIDENT_REPORT.key, VIEW)
    incident = report(lab)
    assert api(lab).get(f"{BASE}/incidents/").json()["count"] == 1
    assert records.can_view(lab, incident)


def test_sds_follows_its_section(manager: User, depo: User, make_user: Callable[..., User]) -> None:
    sheet = sds(manager, MaterialFactory.create())
    blind = api(override(depo, SDS.key, VIEW))
    for path in ("sds/", f"sds/{sheet.pk}/", "sds-gaps/", "sds-gaps/export/", "settings/"):
        refused = blind.get(f"{BASE}/{path}")
        assert refused.status_code == 403, path
    assert required(blind.get(f"{BASE}/sds/")) == [{"key": SDS.key, "level": VIEW}]
    assert not records.can_view(depo, sheet)

    planner = override(make_user("planlama"), SDS.key, CHANGE, effect="grant")
    client = api(planner)
    for path in ("sds/", f"sds/{sheet.pk}/", "sds-gaps/", "settings/"):
        assert client.get(f"{BASE}/{path}").status_code == 200, path
    assert records.can_view(planner, sheet)
    assert services.can_attach_sds(planner, sheet)
    updated = client.patch(f"{BASE}/sds/{sheet.pk}/", {"revision_no": "2"}, format="json")
    assert updated.status_code == 200, updated.json()
    # Ayarları değiştirmek İSG ayarları ister.
    refused = client.patch(f"{BASE}/settings/", {"sds_max_age_months": 24}, format="json")
    assert refused.status_code == 403
    assert required(refused) == [{"key": SETTINGS.key, "level": CHANGE}]


def test_settings_change_revoked(manager: User) -> None:
    client = api(override(manager, SETTINGS.key, CHANGE))
    assert client.get(f"{BASE}/settings/").status_code == 200
    refused = client.patch(f"{BASE}/settings/", {"sds_max_age_months": 24}, format="json")
    assert refused.status_code == 403
    assert required(refused) == [{"key": SETTINGS.key, "level": CHANGE}]
    with pytest.raises(MissingAccess):
        services.update_settings(manager, {"sds_max_age_months": 24})


def test_hazard_change_revoked_keeps_locked_read(lab: User) -> None:
    material = MaterialFactory.create()
    client = api(override(lab, HAZARDS.key, CHANGE))
    url = f"{BASE}/materials/{material.pk}/hazard/"
    assert client.get(url).status_code == 200
    body = {"pictograms": ["GHS05"], "signal_word": "DANGER"}
    refused = client.put(url, body, format="json")
    assert refused.status_code == 403
    assert required(refused) == [{"key": HAZARDS.key, "level": CHANGE}]
    assert client.post(f"{BASE}/hazard-statements/", {}, format="json").status_code == 403
    # Görür kilitli: kaldırma yok sayılır.
    override(lab, HAZARDS.key, VIEW)
    assert client.get(f"{BASE}/hazard-statements/").status_code == 200
    assert client.get(f"{BASE}/material-hazards/").status_code == 200


def test_waste_granted_to_warehouse(manager: User, depo: User) -> None:
    firm = contractor(manager)
    record = services.record_waste(manager, waste_data(firm))
    client = api(depo)
    assert client.get(f"{BASE}/waste-records/").status_code == 403
    assert not records.can_view(depo, record)

    override(depo, WASTE.key, VIEW, effect="grant")
    assert client.get(f"{BASE}/waste-records/").status_code == 200
    assert client.get(f"{BASE}/waste-contractors/").status_code == 200
    assert records.can_view(depo, record)
    assert not services.can_attach_waste(depo, record)
    refused = client.post(f"{BASE}/waste-records/{record.pk}/cancel/", {"reason": "x"})
    assert refused.status_code == 403
    assert required(refused) == [{"key": WASTE.key, "level": CHANGE}]

    override(depo, WASTE.key, CHANGE, effect="grant")
    assert services.can_attach_waste(depo, record)
    cancelled = client.post(f"{BASE}/waste-records/{record.pk}/cancel/", {"reason": "Mükerrer"})
    assert cancelled.status_code == 200, cancelled.json()


def test_storage_and_summary_follow_their_sections(
    manager: User, depo: User, make_user: Callable[..., User]
) -> None:
    blind = api(override(depo, STORAGE.key, VIEW))
    assert blind.get(f"{BASE}/storage-limits/").status_code == 403
    assert blind.get(f"{BASE}/storage-utilisation/").status_code == 403

    planner = override(make_user("planlama"), SUMMARY.key, VIEW, effect="grant")
    assert api(planner).get(f"{BASE}/summary/").status_code == 200
    assert api(planner).get(f"{BASE}/waste-records/").status_code == 403
    assert api(override(manager, SUMMARY.key, VIEW)).get(f"{BASE}/summary/").status_code == 403

    limiter = override(make_user("depo"), STORAGE.key, CHANGE, effect="grant")
    body = {"location": storage_location().pk, "hazard_class": HazardClass.GHS05, "max_kg": "500"}
    created = api(limiter).post(f"{BASE}/storage-limits/", body, format="json")
    assert created.status_code == 201, created.json()


def test_unrouted_methods_keep_todays_rule(
    manager: User, lab: User, depo: User, make_user: Callable[..., User]
) -> None:
    """Bugün yalnız GET okumadır: HEAD, OPTIONS ve karşılanmayan metotlar yazma iznini ister;
    yalnız POST'u olan yoldaki GET okuma iznini ister; izinden sonra 405 döner."""
    operator = api(make_user("uretim"))
    nobody = api(make_user())
    lab_client, manager_client, depo_client = api(lab), api(manager), api(depo)
    h290 = statement("H290").pk
    incident = report(depo)
    sheet = sds(manager, hazardous_material(lab))
    firm = contractor(manager)

    # Tehlike ifadeleri.
    assert operator.get(f"{BASE}/hazard-statements/{h290}/activate/").status_code == 405
    assert nobody.get(f"{BASE}/hazard-statements/{h290}/activate/").status_code == 403
    assert operator.head(f"{BASE}/hazard-statements/").status_code == 403
    assert lab_client.head(f"{BASE}/hazard-statements/").status_code == 200
    assert operator.options(f"{BASE}/hazard-statements/").status_code == 403
    assert lab_client.put(f"{BASE}/hazard-statements/{h290}/", {}).status_code == 405
    assert operator.put(f"{BASE}/hazard-statements/{h290}/", {}).status_code == 403
    assert lab_client.delete(f"{BASE}/hazard-statements/{h290}/").status_code == 405
    # Malzeme tehlike bilgisi: listede her metot rolü olan herkese; kart sekmesinde yazma kuralı.
    assert operator.post(f"{BASE}/material-hazards/", {}).status_code == 405
    assert nobody.post(f"{BASE}/material-hazards/", {}).status_code == 403
    material = MaterialFactory.create()
    assert operator.head(f"{BASE}/materials/{material.pk}/hazard/").status_code == 403
    assert operator.delete(f"{BASE}/materials/{material.pk}/hazard/").status_code == 403
    assert lab_client.delete(f"{BASE}/materials/{material.pk}/hazard/").status_code == 405
    # GBF.
    assert depo_client.head(f"{BASE}/sds/").status_code == 403
    assert manager_client.put(f"{BASE}/sds/{sheet.pk}/", {}).status_code == 405
    assert depo_client.delete(f"{BASE}/sds/{sheet.pk}/").status_code == 403
    assert depo_client.post(f"{BASE}/sds-gaps/", {}).status_code == 405
    # Depolama.
    assert depo_client.head(f"{BASE}/storage-limits/").status_code == 403
    assert depo_client.post(f"{BASE}/storage-utilisation/", {}).status_code == 405
    # Atık: yalnız POST'u olan yolda GET okuma iznini ister.
    assert manager_client.get(f"{BASE}/waste-contractors/{firm.pk}/activate/").status_code == 405
    assert depo_client.get(f"{BASE}/waste-contractors/{firm.pk}/activate/").status_code == 403
    assert manager_client.delete(f"{BASE}/waste-contractors/{firm.pk}/").status_code == 405
    # Olaylar: GET herkese, HEAD ve OPTIONS yönetime.
    assert depo_client.get(f"{BASE}/incidents/{incident.pk}/close/").status_code == 405
    assert nobody.get(f"{BASE}/incidents/{incident.pk}/close/").status_code == 403
    assert depo_client.head(f"{BASE}/incidents/{incident.pk}/").status_code == 403
    assert manager_client.head(f"{BASE}/incidents/{incident.pk}/").status_code == 200
    assert depo_client.delete(f"{BASE}/incidents/{incident.pk}/").status_code == 403
    assert manager_client.delete(f"{BASE}/incidents/{incident.pk}/").status_code == 405
    # Özet ve ayarlar.
    assert depo_client.post(f"{BASE}/summary/", {}).status_code == 403
    assert manager_client.post(f"{BASE}/summary/", {}).status_code == 405
    assert depo_client.head(f"{BASE}/settings/").status_code == 403
    assert depo_client.put(f"{BASE}/settings/", {}).status_code == 403
    assert manager_client.put(f"{BASE}/settings/", {}).status_code == 405
    assert api(None).delete(f"{BASE}/incidents/{incident.pk}/").status_code == 401


def test_each_service_names_its_section_and_level(
    manager: User, lab: User, depo: User, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi plan §3.13'teki bölüme ve düzeye bağlıdır."""
    material = hazardous_material(lab)
    h290 = statement("H290")
    sheet = sds(manager, material)
    limit = services.create_storage_limit(
        manager,
        {"location": storage_location(), "hazard_class": HazardClass.GHS05, "max_kg": Decimal(1)},
    )
    firm = contractor(manager)
    record = services.record_waste(manager, waste_data(firm))
    incident = report(depo)
    nobody = make_user()
    calls: list[tuple[str, Callable[[], object], tuple[str, str]]] = [
        ("update_settings", lambda: services.update_settings(nobody, {}), (SETTINGS.key, CHANGE)),
        ("create_statement", lambda: services.create_statement(nobody, {}), (HAZARDS.key, CHANGE)),
        (
            "update_statement",
            lambda: services.update_statement(nobody, h290, {}),
            (HAZARDS.key, CHANGE),
        ),
        (
            "set_statement_active",
            lambda: services.set_statement_active(nobody, h290, False),
            (HAZARDS.key, CHANGE),
        ),
        (
            "set_material_hazard",
            lambda: services.set_material_hazard(nobody, material, {}),
            (HAZARDS.key, CHANGE),
        ),
        ("create_sds", lambda: services.create_sds(nobody, {}), (SDS.key, CHANGE)),
        ("update_sds", lambda: services.update_sds(nobody, sheet, {}), (SDS.key, CHANGE)),
        (
            "create_storage_limit",
            lambda: services.create_storage_limit(nobody, {}),
            (STORAGE.key, CHANGE),
        ),
        (
            "update_storage_limit",
            lambda: services.update_storage_limit(nobody, limit, {}),
            (STORAGE.key, CHANGE),
        ),
        (
            "set_storage_limit_active",
            lambda: services.set_storage_limit_active(nobody, limit, False),
            (STORAGE.key, CHANGE),
        ),
        ("create_contractor", lambda: services.create_contractor(nobody, {}), (WASTE.key, CHANGE)),
        (
            "update_contractor",
            lambda: services.update_contractor(nobody, firm, {}),
            (WASTE.key, CHANGE),
        ),
        (
            "set_contractor_active",
            lambda: services.set_contractor_active(nobody, firm, False),
            (WASTE.key, CHANGE),
        ),
        ("record_waste", lambda: services.record_waste(nobody, {}), (WASTE.key, CHANGE)),
        (
            "cancel_waste_record",
            lambda: services.cancel_waste_record(nobody, record, "x"),
            (WASTE.key, CHANGE),
        ),
        (
            "report_incident",
            lambda: services.report_incident(nobody, {}),
            (INCIDENT_REPORT.key, CHANGE),
        ),
        (
            "start_investigation",
            lambda: services.start_investigation(nobody, incident),
            (INCIDENTS.key, CHANGE),
        ),
        (
            "update_investigation",
            lambda: services.update_investigation(nobody, incident, {}),
            (INCIDENTS.key, CHANGE),
        ),
        (
            "close_incident",
            lambda: services.close_incident(nobody, incident, {}),
            (INCIDENTS.key, CHANGE),
        ),
        (
            "cancel_incident",
            lambda: services.cancel_incident(nobody, incident, "x"),
            (INCIDENTS.key, CHANGE),
        ),
    ]
    wrong: list[str] = []
    for name, call, need in calls:
        try:
            call()
        except MissingAccess as error:
            if error.required != (need,):
                wrong.append(f"{name}: {error.required} != {(need,)}")
            if not str(error).endswith("yetkiniz yok."):
                wrong.append(f"{name}: mesaj {error}")
        else:
            wrong.append(f"{name}: reddedilmedi")
    assert not wrong, "\n".join(wrong)


def test_roleless_user_sees_no_hse_records(manager: User, make_user: Callable[..., User]) -> None:
    """Rolsüz kullanıcı GBF, atık ve olay kayıtlarının yorum, geçmiş ve ekini görmez (bugünkü
    `roles=` kuralı); kendi açtığı olay olsa bile (Olay bildirimi rolü olan herkese)."""
    nobody = make_user()
    sheet = sds(manager, MaterialFactory.create())
    record = services.record_waste(manager, waste_data(contractor(manager)))
    incident = report(manager)
    Incident.objects.filter(pk=incident.pk).update(created_by=nobody)
    incident.refresh_from_db()
    for obj in (sheet, record, incident):
        assert not records.can_view(nobody, obj), obj
        assert records.can_view(manager, obj), obj
