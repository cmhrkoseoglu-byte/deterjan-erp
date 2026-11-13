"""Kişiye özel ayarla canlıya geçiş (docs/plan/kisi-yetkileri.md §3.16, §10 5. adım): hazırlık
listesi, canlı başlangıç tarihi ve stok karşılaştırması kendi bölümleriyle denetlenir; tarih ve
karşılaştırma servisleri bugünkü gibi yalnız uç noktada denetlenir (plan §5.4); sorun bildirmek
giriş yapan herkese açıktır, bütün bildirimler yalnız admine."""

import io
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.core import records
from apps.core.access import CHANGE, VIEW
from apps.core.models import AccessOverride, User
from apps.golive import services
from apps.golive.access import COMPARISONS, PROBLEMS, READINESS, SETTINGS
from apps.golive.models import StockComparison
from apps.inventory import services as inventory
from apps.inventory.tests.factories import stocked_lot

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("invariants")]

READINESS_URL = reverse("golive:readiness")
GO_LIVE_URL = reverse("golive:go-live")
COMPARISONS_URL = reverse("golive:comparison-list")
PROBLEMS_URL = reverse("golive:problem-list")


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


def stock_file(code: str) -> SimpleUploadedFile:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Malzeme kodu", "Miktar"])
    sheet.append([code, 10])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile("stok.xlsx", buffer.getvalue())


def test_readiness_and_go_live_follow_their_sections(make_user: Callable[..., User]) -> None:
    planner = override(make_user("planlama"), READINESS.key, VIEW)
    client = api(planner)
    refused = client.get(READINESS_URL)
    assert refused.status_code == 403
    assert required(refused) == [{"key": READINESS.key, "level": VIEW}]
    assert client.get(GO_LIVE_URL).status_code == 200

    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    setter = override(make_user("depo"), SETTINGS.key, CHANGE, effect="grant")
    saved = api(setter).put(GO_LIVE_URL, {"go_live_date": tomorrow}, format="json")
    assert saved.status_code == 200, saved.json()
    assert api(setter).head(GO_LIVE_URL).status_code == 200

    manager = override(make_user("yonetim"), SETTINGS.key, CHANGE)
    refused = api(manager).put(GO_LIVE_URL, {"go_live_date": tomorrow}, format="json")
    assert refused.status_code == 403
    assert required(refused) == [{"key": SETTINGS.key, "level": CHANGE}]
    assert api(manager).get(GO_LIVE_URL).status_code == 200
    # HEAD ve OPTIONS bugünkü gibi Değiştirir ister.
    assert api(manager).head(GO_LIVE_URL).status_code == 403
    assert api(manager).options(GO_LIVE_URL).status_code == 403


def test_comparisons_follow_their_section(make_user: Callable[..., User]) -> None:
    lot = stocked_lot("10")
    planner = override(make_user("planlama"), COMPARISONS.key, CHANGE, effect="grant")
    created = api(planner).post(
        COMPARISONS_URL, {"file": stock_file(lot.material.code)}, format="multipart"
    )
    assert created.status_code == 201, created.json()

    warehouse = override(make_user("depo"), COMPARISONS.key, CHANGE)
    client = api(warehouse)
    assert client.get(COMPARISONS_URL).status_code == 200
    refused = client.post(
        COMPARISONS_URL, {"file": stock_file(lot.material.code)}, format="multipart"
    )
    assert refused.status_code == 403
    assert required(refused) == [{"key": COMPARISONS.key, "level": CHANGE}]
    blind = api(override(make_user("depo"), COMPARISONS.key, VIEW))
    assert blind.get(COMPARISONS_URL).status_code == 403
    assert blind.get(reverse("golive:comparison-template")).status_code == 403
    assert StockComparison.objects.count() == 1


def test_unrouted_methods_keep_todays_rule(make_user: Callable[..., User]) -> None:
    """Karşılanmayan metot bugünkü kuralı ister, sonra 405: karşılaştırmalarda okuma, canlı
    başlangıç tarihinde değiştirme, sorun bildiriminde oturum."""
    planner, manager = api(make_user("planlama")), api(make_user("yonetim"))
    filler, nobody = api(make_user("dolum")), api(make_user())
    assert planner.delete(COMPARISONS_URL).status_code == 405
    assert filler.delete(COMPARISONS_URL).status_code == 403
    assert planner.options(COMPARISONS_URL).status_code == 200
    assert planner.post(READINESS_URL, {}).status_code == 405
    assert filler.post(READINESS_URL, {}).status_code == 403
    assert planner.post(GO_LIVE_URL, {}).status_code == 403
    assert planner.head(GO_LIVE_URL).status_code == 403
    assert manager.post(GO_LIVE_URL, {}).status_code == 405
    assert nobody.delete(PROBLEMS_URL).status_code == 405
    assert nobody.get(PROBLEMS_URL).status_code == 200
    assert api(None).delete(PROBLEMS_URL).status_code == 401
    assert api(None).post(GO_LIVE_URL, {}).status_code == 401


def test_problem_reports_stay_open_and_admin_sees_all(make_user: Callable[..., User]) -> None:
    reporter = make_user()
    report = services.report_problem(reporter, description="Ekran donuyor")
    assert api(reporter).get(PROBLEMS_URL).json()["count"] == 1
    assert records.can_view(reporter, report)
    other = make_user("yonetim")
    assert api(other).get(PROBLEMS_URL).json()["count"] == 0
    assert not services.can_view_problem(other, report)
    # Sorun bildirimleri listesi yalnız admindir: kişiye verilen ayar yok sayılır.
    granted = override(make_user("yonetim"), PROBLEMS.key, VIEW, effect="grant")
    assert api(granted).get(PROBLEMS_URL).json()["count"] == 0
    admin = make_user("admin")
    assert api(admin).get(PROBLEMS_URL).json()["count"] == 1
    assert services.can_view_problem(admin, report)


def test_go_live_and_comparison_services_stay_unchecked(make_user: Callable[..., User]) -> None:
    """Bugün yalnız uç noktada olan denetim yalnız uç noktada kalır (plan §5.4)."""
    nobody = make_user()
    services.set_go_live_date(nobody, timezone.localdate() + timedelta(days=2))
    assert inventory.get_inventory_settings().go_live_date is not None
    lot = stocked_lot("5")
    comparison = services.create_stock_comparison(
        nobody, upload=stock_file(lot.material.code), filename="stok.xlsx"
    )
    assert comparison.pk is not None
