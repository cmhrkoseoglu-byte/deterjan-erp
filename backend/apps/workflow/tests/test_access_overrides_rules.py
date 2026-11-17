"""Kişiye özel ayarla kural alıcıları (docs/plan/kisi-yetkileri.md §5.7, §8 madde 6 ve 10;
7. adım): görev ve bildirim role gitmeye devam eder, roldeki kişilerden yalnız kuralın
gerektirdiği yetkisi olanlara gider. Yükten gelen kişiler (siparişi açan) de süzülür; rapor
isteyen süzülmez. İptal bildirimi iptal edilen kaydın bölümünde Görür ister. Anlık (WebSocket)
kitle aynı süzgeci kullanır."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core import event_names as ev
from apps.core.access import CHANGE, VIEW
from apps.core.models import AccessOverride, User
from apps.workflow import services
from apps.workflow.models import Notification, Task
from apps.workflow.tests.factories import WidgetFactory, ref

pytestmark = pytest.mark.django_db


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def titles_for(user: User) -> list[str]:
    return sorted(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def order_ref(order, **extra):
    return ref(order, number=f"UE-2026-{order.pk:05d}", **extra)


# --- görev kuralı: kuralın yetkisi ------------------------------------------------------------


def test_task_goes_only_to_role_members_holding_the_rule_requirement(fire, make_user):
    keeper, revoked = make_user("depo"), make_user("depo")
    override(revoked, "production.prep", CHANGE)
    order = WidgetFactory()

    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))

    task = Task.objects.get(rule_code="material_prep")
    title = f"Yeni görev: Malzeme hazırla: UE-2026-{order.pk:05d}"
    assert titles_for(keeper) == [title]
    assert titles_for(revoked) == []
    # Anlık kitle aynı süzgeç: yetkisi kaldırılan üye görev iletisi almaz.
    assert services._task_audience(task) == {keeper.pk}


def test_granting_the_requirement_outside_the_role_does_not_make_a_recipient(fire, make_user):
    """Yetki roldeki kişiyi süzer; rolü olmayana görev ya da bildirim göndermez."""
    member = make_user("depo")
    outsider = override(make_user("sevkiyat"), "production.prep", CHANGE, effect="grant")
    order = WidgetFactory()

    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))

    assert titles_for(member) != []
    assert titles_for(outsider) == []


def test_claimer_who_lost_the_requirement_is_not_pushed(fire, make_user):
    keeper, claimer = make_user("depo"), make_user("depo")
    order = WidgetFactory()
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
    task = Task.objects.get(rule_code="material_prep")
    services.claim_task(claimer, task)
    assert services._task_audience(task) == {keeper.pk, claimer.pk}

    override(claimer, "production.prep", CHANGE)
    task.refresh_from_db()

    assert services._task_audience(task) == {keeper.pk}


def test_person_assigned_task_is_pushed_to_the_assignee(make_user):
    """Kişiye atanmış görev atanan kişiye görünür (işi yapmak yine yetki ister)."""
    assignee = make_user()
    task = services.create_task(None, title="Kontrol et", user=assignee)

    assert titles_for(assignee) == ["Yeni görev: Kontrol et"]
    assert services._task_audience(task) == {assignee.pk}


# --- bildirim kuralı: kuralın bölümünde Görür ---------------------------------------------------


def test_notification_goes_only_to_role_members_with_the_rule_view(fire, make_user):
    keeper, revoked = make_user("planlama"), make_user("planlama")
    override(revoked, "production.orders", VIEW)
    lot = WidgetFactory()

    fire(ev.LOT_RELEASED, ref(lot, lot_no="B-261015-001", material_type="BULK"))

    assert titles_for(keeper) == ["Bulk lot serbest bırakıldı: B-261015-001"]
    assert titles_for(revoked) == []


def test_lot_linked_notifications_are_not_filtered_by_overrides(fire, make_user):
    """§12 kararı: lot sayfasına bağlanan iki bildirim "Lotlar: Görür" ister; kilitli olduğundan
    kaldırılamaz, alıcılar bugünkü gibi kalır."""
    lab = override(make_user("laboratuvar"), "inventory.lots", VIEW)
    batch, lot = WidgetFactory(), WidgetFactory()

    fire(
        ev.PRODUCTION_DEVIATION,
        ref(batch, order_number="UE-2026-00007", output_lot=ref(lot, lot_no="B-261015-001")),
    )

    notification = Notification.objects.get(recipient=lab)
    assert notification.title == "Tartım sapması: UE-2026-00007"
    assert notification.related_object == lot


def test_admin_rules_reach_admin_group_members_only(fire, make_user):
    admin = make_user("admin")
    granted = override(make_user("yonetim"), "golive.problems", VIEW, effect="grant")
    superuser = make_user(is_superuser=True)
    locked = make_user()

    fire(ev.USER_LOCKED, ref(locked, repr=locked.username, username=locked.username))

    assert len(titles_for(admin)) == 1
    assert titles_for(granted) == []
    assert titles_for(superuser) == []


# --- yükten gelen kişiler (§8 madde 10) -----------------------------------------------------------


def dispatch(fire, creator: User) -> None:
    shipment = WidgetFactory()
    fire(
        ev.SHIPMENT_DISPATCHED,
        ref(shipment, number="SV-2026-00001", order_created_by_id=creator.pk, lots=[]),
    )


def test_order_creator_without_shipments_view_is_not_notified(fire, make_user):
    creator = override(make_user("sevkiyat"), "sales.shipments", VIEW)

    dispatch(fire, creator)

    assert titles_for(creator) == []


def test_order_creator_with_granted_shipments_view_is_notified(fire, make_user):
    creator = override(make_user("uretim"), "sales.shipments", VIEW, effect="grant")

    dispatch(fire, creator)

    assert titles_for(creator) == ["Sevk edildi: SV-2026-00001"]


def test_report_requester_is_never_filtered(fire, make_user):
    requester = make_user()
    job = WidgetFactory()

    fire(ev.REPORT_JOB_DONE, ref(job, title="Stok", row_count=3, requested_by_id=requester.pk))

    assert titles_for(requester) == ["Rapor hazır: Stok"]


# --- iptal bildirimi: iptal edilen kaydın bölümünde Görür ---------------------------------------


def test_cancel_notice_requires_view_of_the_cancelled_record(fire, make_user):
    depo, planner = make_user("depo"), make_user("planlama")
    revoked_planner = override(make_user("planlama"), "production.orders", VIEW)
    order = WidgetFactory()
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
    claimer = make_user("uretim")
    Task.objects.filter(rule_code="material_prep").update(claimed_by=claimer)
    Notification.objects.all().delete()

    fire(ev.PRODUCTION_ORDER_CANCELLED, order_ref(order))

    title = f"Üretim emri iptal edildi: UE-2026-{order.pk:05d}"
    assert titles_for(depo) == [title]
    assert titles_for(planner) == [title]
    # Üstlenen kişi görevin yetkisi olmadan da emri gördüğü için haber alır.
    assert titles_for(claimer) == [title]
    assert titles_for(revoked_planner) == []


def test_cancel_notice_skips_claimer_and_role_member_without_record_view(fire, make_user):
    depo = override(make_user("depo"), "production.orders", VIEW)
    claimer = override(make_user("uretim"), "production.orders", VIEW)
    order = WidgetFactory()
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
    Task.objects.filter(rule_code="material_prep").update(claimed_by=claimer)
    Notification.objects.all().delete()

    fire(ev.PRODUCTION_ORDER_CANCELLED, order_ref(order))

    assert titles_for(depo) == []
    assert titles_for(claimer) == []


def test_cancel_notice_reaches_claimer_granted_the_record_view(fire, make_user):
    make_user("depo")
    claimer = override(make_user("satin_alma"), "production.orders", VIEW, effect="grant")
    order = WidgetFactory()
    fire(ev.PRODUCTION_ORDER_APPROVED, order_ref(order))
    Task.objects.filter(rule_code="material_prep").update(claimed_by=claimer)

    fire(ev.PRODUCTION_ORDER_CANCELLED, order_ref(order))

    assert titles_for(claimer) == [f"Üretim emri iptal edildi: UE-2026-{order.pk:05d}"]


# --- sorgu sayısı (§5.3: roller ve ayarlar önceden yüklenir) -----------------------------------


def test_recipient_filter_query_count_does_not_grow_with_members(make_user):
    def count(members: int) -> int:
        for _ in range(members):
            override(make_user("planlama"), "production.batches", VIEW)
        with CaptureQueriesContext(connection) as queries:
            services.role_members(["planlama"], ("production.orders", VIEW))
        return len(queries)

    assert count(1) == count(5)
