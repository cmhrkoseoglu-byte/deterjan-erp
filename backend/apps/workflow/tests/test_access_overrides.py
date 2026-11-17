"""Kişiye özel ayarla görevler (docs/plan/kisi-yetkileri.md §5.7, §8 madde 6, karar 5; 7. adım).

Görevin rolündeki kişi görevi kuralın gerektirdiği yetkiyle görür ve üstlenir; kişiye atanan görev
görünür ama üstlenmek yine yetki ister; üstlenmiş olmak tek başına yetmez. "Tüm birimlerin
görevleri: Görür" başka rollerin görevlerini gösterir, üstlenme vermez. Kuralsız görevde bugünkü
rol kuralı geçerlidir. Satın alma onayı görevinin açıklaması Fiyatları görür ister.
"""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.models import AccessOverride, User
from apps.workflow import selectors, services
from apps.workflow.models import Task

pytestmark = pytest.mark.django_db

BASE = "/api/v1/workflow/tasks"
MakeUser = Callable[..., User]


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def titles(response) -> list[str]:
    assert response.status_code == 200
    return [item["title"] for item in response.json()["results"]]


def prep_task() -> Task:
    """Malzeme hazırlama görevi: depo rolüne, "Malzeme hazırlama: Değiştirir" ister."""
    return services.create_task(
        None, title="Malzemeyi hazırla", role="depo", rule_code="material_prep"
    )


def plain_task() -> Task:
    return services.create_task(None, title="Kuralsız depo işi", role="depo")


def approval_task() -> Task:
    return services.create_task(
        None,
        title="Satın alma siparişini onayla",
        description="Tedarikçi: Kimya AŞ · Tutar: 125.000,00 TL",
        role="yonetim",
        rule_code="purchase_order_approval",
    )


# --- Kendi rolünün görevi: rol ve kuralın yetkisi (karar 5) -----------------------------------


def test_revoked_requirement_hides_own_role_task_but_not_rule_less_task(make_user: MakeUser):
    task = prep_task()
    plain_task()
    depo = override(make_user("depo"), "production.prep", CHANGE)
    client = api(depo)

    assert titles(client.get(f"{BASE}/")) == ["Kuralsız depo işi"]
    assert titles(client.get(f"{BASE}/", {"mine": "true", "open": "true"})) == ["Kuralsız depo işi"]
    assert client.get(f"{BASE}/{task.pk}/").status_code == 404
    assert client.post(f"{BASE}/{task.pk}/claim/").status_code == 404
    assert not selectors.user_can_act_on_task(depo, task)


def test_requirement_without_role_does_not_open_task(make_user: MakeUser):
    task = prep_task()
    uretim = override(make_user("uretim"), "production.prep", CHANGE, effect="grant")

    assert titles(api(uretim).get(f"{BASE}/")) == []
    assert not selectors.user_can_act_on_task(uretim, task)


def test_role_member_with_requirement_sees_and_acts(make_user: MakeUser):
    task = prep_task()
    client = api(make_user("depo"))

    item = client.get(f"{BASE}/{task.pk}/").json()
    assert item["can_act"] is True
    assert client.post(f"{BASE}/{task.pk}/claim/").status_code == 200


# --- Üstlenen yetkisini kaybedince (§8 madde 6) ------------------------------------------------


def test_claimer_who_loses_requirement_neither_sees_nor_completes(make_user: MakeUser):
    task = prep_task()
    claimer = make_user("depo")
    assert api(claimer).post(f"{BASE}/{task.pk}/claim/").status_code == 200

    override(claimer, "production.prep", CHANGE)
    client = api(claimer)
    assert titles(client.get(f"{BASE}/", {"mine": "true"})) == []
    assert client.post(f"{BASE}/{task.pk}/complete/").status_code == 404

    other = api(make_user("depo"))
    done = other.post(f"{BASE}/{task.pk}/complete/")
    assert done.status_code == 200
    assert done.json()["status"] == "DONE"


def test_claimer_who_leaves_role_no_longer_sees_rule_less_task(make_user: MakeUser):
    task = plain_task()
    claimer = make_user("depo")
    services.claim_task(claimer, task)

    claimer.groups.clear()
    claimer.refresh_access()

    assert titles(api(claimer).get(f"{BASE}/")) == []
    assert not selectors.user_can_act_on_task(claimer, task)


# --- Kişiye atanan görev (§5.7) -------------------------------------------------------------------


def test_assigned_user_sees_but_acts_only_with_requirement(make_user: MakeUser):
    assignee = make_user("uretim")
    task = services.create_task(
        None, title="Kişiye hazırlık", user=assignee, rule_code="material_prep"
    )
    client = api(assignee)

    item = client.get(f"{BASE}/{task.pk}/").json()
    assert item["can_act"] is False
    assert titles(client.get(f"{BASE}/", {"mine": "true"})) == ["Kişiye hazırlık"]
    denied = client.post(f"{BASE}/{task.pk}/claim/")
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    override(assignee, "production.prep", CHANGE, effect="grant")
    assert api(assignee).post(f"{BASE}/{task.pk}/claim/").status_code == 200


def test_rule_less_task_assigned_to_user_keeps_todays_rule(make_user: MakeUser):
    assignee = make_user()
    task = services.create_task(None, title="Kişisel iş", user=assignee)

    assert api(assignee).post(f"{BASE}/{task.pk}/claim/").status_code == 200


def test_unknown_rule_code_keeps_role_only_rule(make_user: MakeUser):
    task = services.create_task(None, title="Eski kural", role="depo", rule_code="artik_yok")
    depo = override(make_user("depo"), "production.prep", CHANGE)

    assert titles(api(depo).get(f"{BASE}/")) == ["Eski kural"]
    assert selectors.user_can_act_on_task(depo, task)


# --- Tüm birimlerin görevleri -------------------------------------------------------------------


def test_all_tasks_grant_shows_other_roles_tasks_without_acting(make_user: MakeUser):
    task = prep_task()
    lab = services.create_task(None, title="Lab işi", role="laboratuvar")
    dolum = override(make_user("dolum"), "workflow.all_tasks", VIEW, effect="grant")
    client = api(dolum)

    assert sorted(titles(client.get(f"{BASE}/"))) == ["Lab işi", "Malzemeyi hazırla"]
    assert titles(client.get(f"{BASE}/", {"mine": "true"})) == []
    item = client.get(f"{BASE}/{task.pk}/").json()
    assert item["can_act"] is False
    for action in ("claim", "complete"):
        response = client.post(f"{BASE}/{lab.pk}/{action}/")
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


def test_all_tasks_revoked_from_management_hides_other_roles_tasks(make_user: MakeUser):
    task = prep_task()
    own = services.create_task(None, title="Yönetim işi", role="yonetim")
    yonetim = override(make_user("yonetim"), "workflow.all_tasks", VIEW)
    client = api(yonetim)

    assert titles(client.get(f"{BASE}/")) == ["Yönetim işi"]
    assert client.get(f"{BASE}/{task.pk}/").status_code == 404
    assert client.post(f"{BASE}/{task.pk}/complete/").status_code == 404
    assert client.get(f"{BASE}/{own.pk}/").json()["can_act"] is True


def test_all_tasks_does_not_reopen_own_role_task_without_requirement(make_user: MakeUser):
    task = services.create_task(
        None, title="Olayı incele", role="yonetim", rule_code="incident_review"
    )
    yonetim = override(make_user("yonetim"), "hse.incidents", CHANGE)

    assert titles(api(yonetim).get(f"{BASE}/")) == []
    assert not selectors.user_can_act_on_task(yonetim, task)


def test_admin_sees_and_acts_on_every_task(make_user: MakeUser):
    task = prep_task()
    admin = make_user("admin")

    assert titles(api(admin).get(f"{BASE}/")) == ["Malzemeyi hazırla"]
    assert api(admin).post(f"{BASE}/{task.pk}/claim/").status_code == 200


# --- Satın alma onayı görevinin açıklaması (§5.6, §5.7) -----------------------------------------


def test_approval_description_blank_and_unsearchable_without_prices(make_user: MakeUser):
    task = approval_task()
    viewer = override(make_user("depo"), "workflow.all_tasks", VIEW, effect="grant")
    client = api(viewer)

    item = client.get(f"{BASE}/{task.pk}/").json()
    assert item["description"] == ""
    assert titles(client.get(f"{BASE}/", {"search": "Kimya"})) == []
    assert titles(client.get(f"{BASE}/", {"search": "onayla"})) == [task.title]


def test_approval_description_shown_with_prices_grant(make_user: MakeUser):
    task = approval_task()
    viewer = override(make_user("depo"), "workflow.all_tasks", VIEW, effect="grant")
    override(viewer, "sensitive.prices", VIEW, effect="grant")
    client = api(viewer)

    assert client.get(f"{BASE}/{task.pk}/").json()["description"].startswith("Tedarikçi")
    assert titles(client.get(f"{BASE}/", {"search": "Kimya"})) == [task.title]


def test_other_task_descriptions_searchable_without_prices(make_user: MakeUser):
    services.create_task(None, title="Depo işi", description="Kimya rafı", role="depo")

    assert titles(api(make_user("depo")).get(f"{BASE}/", {"search": "Kimya"})) == ["Depo işi"]


def test_management_with_prices_revoked_loses_approval_task(make_user: MakeUser):
    task = approval_task()
    yonetim = override(make_user("yonetim"), "sensitive.prices", VIEW)

    assert yonetim.access.allows("purchasing.over_limit", APPROVE) is False
    assert titles(api(yonetim).get(f"{BASE}/")) == []
    assert not selectors.user_can_act_on_task(yonetim, task)
