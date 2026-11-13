"""Paket denkliği: canlıya geçiş (docs/plan/kisi-yetkileri.md §3.16, §5.5 3. parça).

Bugünkü her rol denetimi bir yetki ifadesine eşlenir; kişiye özel ayar yokken 256 rol bileşiminde
aynı kararı verdiği kanıtlanır. Sorun bildirmek ve kişinin kendi bildirimlerini görmesi herkese
açıktır (plan §4; satır kuralı); bütün bildirimleri görmek yalnız admindir (Sorun bildirimleri
listesi). Menü ve rotalar kabuğun dosyasındadır (`apps/core/tests/test_access_package_shell.py`).
"""

from apps.core.access import CHANGE
from apps.core.tests.access_helpers import ADMIN_ONLY, Row, any_of, assert_rows, level
from apps.golive.access import COMPARISONS, PROBLEMS, READINESS, SETTINGS

ROWS: list[Row] = [
    # API (apps/golive/api/views.py).
    Row(
        "golive.api.views.ReadinessView (READ_ROLES)",
        ("yonetim", "planlama", "depo"),
        level(READINESS),
        live="apps.golive.api.views:READ_ROLES",
    ),
    Row(
        "golive.api.views.GoLiveView GET (READ_ROLES)",
        ("yonetim", "planlama", "depo"),
        level(SETTINGS),
        live="apps.golive.api.views:READ_ROLES",
    ),
    Row(
        "golive.api.views.GoLiveView PUT (GO_LIVE_ROLES)",
        ("yonetim",),
        level(SETTINGS, CHANGE),
        live="apps.golive.api.views:GO_LIVE_ROLES",
    ),
    Row(
        "golive.api.views.StockComparisonViewSet list, retrieve, lines, export, template "
        "(READ_ROLES)",
        ("yonetim", "planlama", "depo"),
        level(COMPARISONS),
        live="apps.golive.api.views:READ_ROLES",
    ),
    Row(
        "golive.api.views.StockComparisonViewSet create (COMPARISON_WRITE_ROLES)",
        ("depo", "yonetim"),
        level(COMPARISONS, CHANGE),
        live="apps.golive.api.views:COMPARISON_WRITE_ROLES",
    ),
    # Bütün sorun bildirimleri: ekran, ekran görüntüsü ve kayıt paneli (apps.py
    # register_record_type visible=) aynı kuralı kullanır.
    Row(
        "golive.selectors.problem_reports_visible_to (admin hepsini görür)",
        ADMIN_ONLY,
        level(PROBLEMS),
    ),
    Row("golive.services.can_view_problem (admin)", ADMIN_ONLY, level(PROBLEMS)),
    # Ön yüz (frontend/src/modules/golive).
    Row(
        "GoLivePage.tsx TABS hazirlik (hazırlık listesi ve canlı başlangıç tarihi kartı)",
        ("yonetim", "planlama", "depo"),
        any_of(level(READINESS), level(SETTINGS)),
    ),
    Row(
        "GoLivePage.tsx TABS karsilastirma",
        ("yonetim", "planlama", "depo"),
        level(COMPARISONS),
    ),
    Row("GoLivePage.tsx TABS sorunlar (['admin'])", ADMIN_ONLY, level(PROBLEMS)),
    Row(
        "ComparisonsTab.tsx canCreate (yeni karşılaştırma)",
        ("depo", "yonetim"),
        level(COMPARISONS, CHANGE),
    ),
    Row(
        "ReadinessTab.tsx GoLiveCard canEdit (tarihi kaydet, kaldır)",
        ("yonetim",),
        level(SETTINGS, CHANGE),
    ),
    Row(
        "ProblemPage.tsx sorun bildirimleri listesine dönüş bağlantısı (['admin'])",
        ADMIN_ONLY,
        level(PROBLEMS),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
