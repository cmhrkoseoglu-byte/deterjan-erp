"""Paket denkliği: sistem durumu (docs/plan/kisi-yetkileri.md §4, §5.5 3. parça).

Sistem durumu yalnız adminindir; kimseye verilemez, katalogda bölümü yoktur. Arayüz hata kaydı
herkese, dış izleme ucu kimlik doğrulamasız açıktır (rol denetimi yok).
"""

from apps.core.permissions import AdminOnly
from apps.core.tests.access_helpers import ADMIN_ONLY, Row, admin_only, assert_rows
from apps.ops.api.views import SystemStatusView

ROWS: list[Row] = [
    Row("ops.api.views.SystemStatusView (HasRole(ADMIN))", ADMIN_ONLY, admin_only()),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_system_status_is_admin_only() -> None:
    """Satırın karşılığı: uç nokta yalnız sistem yöneticisine açıktır (bölümü yoktur)."""
    assert SystemStatusView.permission_classes == [AdminOnly]
