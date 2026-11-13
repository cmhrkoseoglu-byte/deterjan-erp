"""Kişiye özel ayarla satın alma (docs/plan/kisi-yetkileri.md §10, 5. adım): D-13 bölümlerle
çevrilir (Limit üstü sipariş onayı her tutarı, Satın alma siparişleri: Onaylar limit içini onaylar),
fiyatlar Fiyatları görür'e bağlıdır (geçmişteki tutarlar dahil), servisler bölüm ve düzeyi söyler.
Mal kabul kaydının siparişi ilerletmesi ve sabah kontrolünün otomatik talebi denetimsiz sistem
adımlarıdır."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.access import APPROVE, CHANGE, PRICES, VIEW
from apps.core.audit import log_change
from apps.core.models import AccessOverride, AuditLog, User
from apps.core.permissions import MissingAccess
from apps.inventory import services as inventory
from apps.purchasing import services
from apps.purchasing.access import DELIVERIES, ORDERS, OVER_LIMIT, REQUESTS, SETTINGS
from apps.purchasing.models import PurchaseOrder, PurchaseRequest
from apps.purchasing.tests.factories import (
    ORDER_DATE,
    approved_order,
    draft_order,
    line,
    raw_material,
    receipt_locations,
)

pytestmark = pytest.mark.usefixtures("invariants")
D = Decimal
Status = PurchaseOrder.Status


def url(name: str, *args: Any) -> str:
    return reverse(f"purchasing:{name}", args=args)


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def api(user: User | None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def required(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"key": key, "level": level} for key, level in pairs]


def set_limit(manager: User, value: str | None) -> None:
    services.update_settings(manager, {"approval_limit_try": None if value is None else D(value)})


def test_order_approver_without_over_limit_follows_d13(buyer: User, manager: User) -> None:
    """Plan §5.4: Satın alma siparişleri: Onaylar yalnız limit içini onaylar; kaldırılınca onay
    uç noktası ve servisin ilk denetimi 403 olur, onaya gönderme açık kalır."""
    set_limit(manager, "1000")
    order = draft_order(buyer, [line(raw_material(), "10", "10")])  # 100 TL
    client = api(override(buyer, ORDERS.key, APPROVE))

    detail = client.get(url("order-detail", order.pk))
    assert detail.status_code == 200 and detail.json()["can_approve"] is False
    refused = client.post(url("order-approve", order.pk))
    assert refused.status_code == 403
    assert refused.json()["required"] == required((ORDERS.key, APPROVE), (OVER_LIMIT.key, APPROVE))
    with pytest.raises(MissingAccess) as exc:
        services.approve_order(buyer, order)
    assert exc.value.required == ((ORDERS.key, APPROVE), (OVER_LIMIT.key, APPROVE))
    assert client.post(url("order-submit", order.pk)).status_code == 200


def test_granted_over_limit_approves_any_amount_and_returns_to_draft(
    buyer: User, manager: User
) -> None:
    """Limit üstü sipariş onayı satın almaya verilince limit girilmemişken de onaylar ve taslağa
    geri gönderir (bugün yalnız yönetim)."""
    pending = services.submit_for_approval(buyer, draft_order(buyer, [line(raw_material())]))
    other = services.submit_for_approval(buyer, draft_order(buyer, [line(raw_material())]))
    assert not services.can_approve(buyer, pending)
    with pytest.raises(MissingAccess) as exc:
        services.return_to_draft(buyer, other, "Yeniden teklif")
    assert exc.value.required == ((OVER_LIMIT.key, APPROVE),)

    client = api(override(buyer, OVER_LIMIT.key, APPROVE, effect="grant"))
    assert client.get(url("order-detail", pending.pk)).json()["can_approve"] is True
    approved = client.post(url("order-approve", pending.pk))
    assert approved.status_code == 200, approved.json()
    assert approved.json()["status"] == Status.APPROVED
    returned = client.post(url("order-return-to-draft", other.pk), {"note": "Yeniden teklif"})
    assert returned.status_code == 200, returned.json()


@pytest.mark.parametrize("limit", [None, "1"])
def test_over_limit_refusal_names_the_permission_not_the_role(
    buyer: User, manager: User, limit: str | None
) -> None:
    """D-13 reddi (plan §5.4, §10 "mesajlar rol adı içermez"): Limit üstü sipariş onayı
    kaldırılan yönetim üyesine "yönetim onaylar" denmez, gereken yetki söylenir."""
    set_limit(manager, limit)
    order = draft_order(buyer, [line(raw_material(), "100", "100")])  # 10.000 TL
    client = api(override(manager, OVER_LIMIT.key, APPROVE))

    refused = client.post(url("order-approve", order.pk))
    assert refused.status_code == 400
    assert refused.json()["code"] == "approval_limit_exceeded"
    detail = refused.json()["detail"]
    assert "Limit üstü sipariş onayı yetkisi olan onaylar" in detail
    assert "yönetim onaylar" not in detail


def test_cancel_level_follows_status(buyer: User, manager: User) -> None:
    """Taslak ya da onay bekleyeni iptal Değiştirir, onaylıyı iptal Onaylar ister (plan §3.10)."""
    draft = draft_order(buyer, [line(raw_material())])
    approved = approved_order(manager, [line(raw_material())])
    client = api(override(buyer, ORDERS.key, APPROVE))

    refused = client.post(url("order-cancel", approved.pk), {"reason": "Gerek kalmadı"})
    assert refused.status_code == 403
    assert refused.json()["required"] == required((ORDERS.key, APPROVE))
    cancelled = client.post(url("order-cancel", draft.pk), {"reason": "Gerek kalmadı"})
    assert cancelled.status_code == 200, cancelled.json()


def test_prices_follow_prices_right_in_screen_pdf_and_history(
    buyer: User, manager: User, depo: User
) -> None:
    """Fiyatları görür (plan §3.18, §5.6, §8 madde 7): ekrandaki tutarlar, PDF ve geçmişteki
    tutarlar (alan satırları, silinen satırın içi, eski tutarlı notlar)."""
    material = raw_material()
    order = draft_order(buyer, [line(material, "100", "50"), line(material, "10", "5")])
    kept = order.lines.order_by("line_no")[0]
    values = {
        "id": kept.pk,
        "material": material,
        "quantity": kept.quantity,
        "unit": kept.unit,
        "unit_price": kept.unit_price,
        "expected_date": kept.expected_date,
    }
    services.update_order(buyer, order, {}, [values])
    order = services.submit_for_approval(buyer, order)
    services.approve_order(manager, order)
    # 5. adımdan önceki kayıtların notu tutar taşır.
    log_change(manager, order, AuditLog.Action.STATUS_CHANGE, {}, "Tutar 5.000,00 TL")
    history_params = {"content_type": "purchasing.purchaseorder", "object_id": str(order.pk)}
    history_url = "/api/v1/workflow/record-history/"

    def history(user: User) -> list[dict[str, Any]]:
        response = api(user).get(history_url, history_params)
        assert response.status_code == 200, response.json()
        data = response.json()
        return data["results"] if isinstance(data, dict) else data

    def shown(entries: list[dict[str, Any]]) -> str:
        return repr(entries)

    hidden = shown(history(depo))
    assert "approval_total_try" not in hidden and "unit_price" not in hidden
    assert "5.000,00" not in hidden
    seen = shown(history(buyer))
    assert "approval_total_try" in seen and "unit_price" in seen and "5.000,00" in seen

    priced = api(override(depo, PRICES.key, VIEW, effect="grant"))
    detail = priced.get(url("order-detail", order.pk)).json()
    assert detail["total_try"] == "5000.00"
    assert priced.get(url("order-pdf", order.pk)).status_code == 200
    granted = shown(history(depo))
    assert "approval_total_try" in granted and "5.000,00" in granted

    blind = api(override(buyer, PRICES.key, VIEW))
    assert "total_try" not in blind.get(url("order-detail", order.pk)).json()
    refused = blind.get(url("order-pdf", order.pk))
    assert refused.status_code == 403


def test_settings_values_follow_settings_view_or_order_change(
    make_user: Callable[..., User], manager: User
) -> None:
    """Plan §3.10: ayar değerlerini Satın alma ayarları: Görür ve sipariş yazan okur; HEAD ve
    OPTIONS bugünkü gibi değiştirme yetkisini ister."""
    planner = api(override(make_user("planlama"), SETTINGS.key, VIEW, effect="grant"))
    assert planner.get(url("settings")).status_code == 200
    assert planner.head(url("settings")).status_code == 403
    refused = planner.patch(url("settings"), {"approval_limit_try": "5"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == required((SETTINGS.key, CHANGE))

    revoked = api(override(make_user("yonetim"), SETTINGS.key, CHANGE))
    assert revoked.get(url("settings")).status_code == 200
    assert revoked.patch(url("settings"), {}, format="json").status_code == 403


def test_request_row_rule_follows_order_change(
    buyer: User, planner: User, make_user: Callable[..., User]
) -> None:
    """Kişi kendi talebini düzenler; başkasınınkini "Satın alma siparişleri: Değiştirir"
    düzenler (plan §4)."""
    material = raw_material()
    data = {"material": material, "quantity": D("5"), "need_date": ORDER_DATE}
    request = services.create_request(planner, data)
    client = api(override(buyer, ORDERS.key, CHANGE))
    refused = client.patch(url("request-detail", request.pk), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    assert refused.json()["required"] == required((ORDERS.key, CHANGE))
    own = services.create_request(buyer, data)
    edited = client.patch(url("request-detail", own.pk), {"reason": "x"}, format="json")
    assert edited.status_code == 200, edited.json()
    assert services.update_request(buyer, own, {"reason": "y"}).reason == "y"

    no_requests = api(override(make_user("depo"), REQUESTS.key, CHANGE))
    assert no_requests.get(url("request-list")).status_code == 200
    body = {"material": material.pk, "quantity": "5", "need_date": "2026-10-16"}
    created = no_requests.post(url("request-list"), body, format="json")
    assert created.status_code == 403
    assert created.json()["required"] == required((REQUESTS.key, CHANGE))


def test_receipt_from_order_follows_deliveries_change(manager: User, depo: User) -> None:
    order = approved_order(manager, [line(raw_material(), "100", "10")])
    client = api(override(depo, DELIVERIES.key, CHANGE))
    assert client.get(url("expected-deliveries")).status_code == 200
    refused = client.post(
        url("order-receive", order.pk),
        {"receipt_date": "2026-10-18", "lines": []},
        format="json",
    )
    assert refused.status_code == 403
    assert refused.json()["required"] == required((DELIVERIES.key, CHANGE))


def test_receipt_posting_moves_the_order_without_purchasing_access(
    manager: User, depo: User, make_user: Callable[..., User]
) -> None:
    """Giriş noktası kuralı (plan §5.4): mal kabulü kaydeden kişinin satın alma yetkisi olmasa da
    sipariş durumu kancayla ilerler; otomatik talep (sabah kontrolü) denetimsizdir."""
    order = approved_order(manager, [line(raw_material(), "100", "10")])
    receipt = services.create_receipt_from_order(
        depo,
        order,
        {"receipt_date": date(2026, 10, 18), **receipt_locations()},
        [{"order_line": order.lines.get().pk, "quantity": D("100")}],
    )
    for key in (DELIVERIES.key, ORDERS.key):
        override(depo, key, VIEW)
    inventory.post_goods_receipt(depo, receipt)
    order.refresh_from_db()
    assert order.status == Status.RECEIVED

    data = {"material": raw_material(), "quantity": D("5"), "need_date": ORDER_DATE}
    auto = services.create_request(None, data, source=PurchaseRequest.Source.AUTO)
    assert auto.pk is not None
    with pytest.raises(MissingAccess):
        services.create_request(make_user(), data)


def test_unrouted_methods_keep_todays_rule(
    buyer: User, manager: User, depo: User, planner: User
) -> None:
    """Siparişte bugün yalnız GET okumadır: HEAD, OPTIONS ve karşılanmayan metotlar sipariş
    yazma yetkisini, karşılanmayan yoldaki GET okuma kuralını ister; sonra 405 döner."""
    order = draft_order(buyer, [line(raw_material())])
    request = services.create_request(
        planner, {"material": raw_material(), "quantity": D("5"), "need_date": ORDER_DATE}
    )
    reader, writer, outsider = api(depo), api(buyer), api(planner)

    assert reader.get(url("order-list")).status_code == 200
    assert reader.head(url("order-list")).status_code == 403
    assert writer.head(url("order-list")).status_code == 200
    assert reader.options(url("order-receive", order.pk)).status_code == 403
    assert writer.options(url("order-receive", order.pk)).status_code == 200
    assert reader.head(url("order-pdf", order.pk)).status_code == 403
    assert reader.get(url("order-approve", order.pk)).status_code == 405
    assert outsider.get(url("order-approve", order.pk)).status_code == 403
    assert reader.head(url("order-approve", order.pk)).status_code == 403
    assert writer.head(url("order-approve", order.pk)).status_code == 405
    assert reader.delete(url("order-detail", order.pk)).status_code == 403
    assert writer.delete(url("order-detail", order.pk)).status_code == 405
    assert writer.post(url("order-pdf", order.pk)).status_code == 405
    assert api(None).delete(url("order-detail", order.pk)).status_code == 401

    assert outsider.delete(url("request-detail", request.pk)).status_code == 405
    assert (
        api(override(planner, REQUESTS.key, CHANGE))
        .delete(url("request-detail", request.pk))
        .status_code
        == 403
    )

    assert writer.get(url("settings")).status_code == 200
    assert writer.head(url("settings")).status_code == 403
    assert writer.put(url("settings"), {}, format="json").status_code == 403
    assert api(manager).put(url("settings"), {}, format="json").status_code == 405
    assert api(manager).head(url("settings")).status_code == 200

    for name in ("expected-deliveries", "receipt-links"):
        assert reader.post(url(name)).status_code == 405
        assert outsider.post(url(name)).status_code == 403
    assert outsider.post(url("suggestions")).status_code == 405
    assert reader.post(url("suggestions")).status_code == 403
    assert writer.post(url("supplier-performance")).status_code == 405
    assert reader.post(url("supplier-performance")).status_code == 403


def test_each_service_names_its_section_and_level(
    buyer: User, manager: User, depo: User, make_user: Callable[..., User]
) -> None:
    """Her servis denetimi plan §3.10'daki bölüme ve düzeye bağlıdır (rolü olmayan kişi)."""
    material = raw_material()
    draft = draft_order(buyer, [line(material)])
    pending = services.submit_for_approval(buyer, draft_order(buyer, [line(material)]))
    approved = approved_order(manager, [line(material)])
    partial = approved_order(manager, [line(material, "100", "10")])
    receipt = services.create_receipt_from_order(
        depo,
        partial,
        {"receipt_date": date(2026, 10, 18), **receipt_locations()},
        [{"order_line": partial.lines.get().pk, "quantity": D("40")}],
    )
    inventory.post_goods_receipt(depo, receipt)
    partial.refresh_from_db()
    assert partial.status == Status.PARTIALLY_RECEIVED
    request = services.create_request(
        buyer, {"material": material, "quantity": D("5"), "need_date": ORDER_DATE}
    )
    nobody = make_user()
    approvers = ((ORDERS.key, APPROVE), (OVER_LIMIT.key, APPROVE))
    calls: list[tuple[str, Callable[[], object], tuple[tuple[str, str], ...]]] = [
        (
            "update_settings",
            lambda: services.update_settings(nobody, {}),
            ((SETTINGS.key, CHANGE),),
        ),
        (
            "create_request",
            lambda: services.create_request(nobody, {}),
            ((REQUESTS.key, CHANGE),),
        ),
        (
            "update_request",
            lambda: services.update_request(nobody, request, {}),
            ((ORDERS.key, CHANGE),),
        ),
        (
            "cancel_request",
            lambda: services.cancel_request(nobody, request, "x"),
            ((ORDERS.key, CHANGE),),
        ),
        ("create_order", lambda: services.create_order(nobody, {}), ((ORDERS.key, CHANGE),)),
        (
            "update_order",
            lambda: services.update_order(nobody, draft, {}),
            ((ORDERS.key, CHANGE),),
        ),
        (
            "submit_for_approval",
            lambda: services.submit_for_approval(nobody, draft),
            ((ORDERS.key, CHANGE),),
        ),
        ("approve_order", lambda: services.approve_order(nobody, draft), approvers),
        (
            "return_to_draft",
            lambda: services.return_to_draft(nobody, pending, "x"),
            ((OVER_LIMIT.key, APPROVE),),
        ),
        ("mark_sent", lambda: services.mark_sent(nobody, approved), ((ORDERS.key, CHANGE),)),
        (
            "cancel_order taslak",
            lambda: services.cancel_order(nobody, draft, "x"),
            ((ORDERS.key, CHANGE),),
        ),
        (
            "cancel_order onay bekleyen",
            lambda: services.cancel_order(nobody, pending, "x"),
            ((ORDERS.key, CHANGE),),
        ),
        (
            "cancel_order onaylı",
            lambda: services.cancel_order(nobody, approved, "x"),
            ((ORDERS.key, APPROVE),),
        ),
        (
            "cancel_order iptal edilemeyen",
            lambda: services.cancel_order(nobody, partial, "x"),
            ((ORDERS.key, CHANGE), (ORDERS.key, APPROVE)),
        ),
        (
            "close_order",
            lambda: services.close_order(nobody, partial, "x"),
            ((ORDERS.key, CHANGE),),
        ),
        (
            "create_receipt_from_order",
            lambda: services.create_receipt_from_order(nobody, approved, {}, []),
            ((DELIVERIES.key, CHANGE),),
        ),
    ]
    wrong: list[str] = []
    for name, call, expected in calls:
        try:
            call()
        except MissingAccess as error:
            if error.required != expected:
                wrong.append(f"{name}: {error.required} != {expected}")
        else:
            wrong.append(f"{name}: reddedilmedi")
    assert not wrong, "\n".join(wrong)
    assert services.can_approve(nobody, draft) is False
