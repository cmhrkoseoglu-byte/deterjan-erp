"""İzlenebilirlik: paket denkliği (docs/plan/kisi-yetkileri.md §3.9 ve §5.5, 3. parça).

Bugünkü rol denetimi (API ve ön yüz girişleri) bir yetki ifadesine eşlenir. Kişiye özel ayar
yokken eski denetim ile yeni yetki, admin dışındaki 8 rolün bütün bileşimlerinde aynı kararı
verir. Modülün servis katmanı yoktur; seçiciler ve dışa aktarımlar rol denetimi yapmaz. Ön yüzde
(`modules/traceability`) rol denetimi yoktur; lot ve mal kabul bağlantıları koşulsuzdur.
"""

from apps.core.tests.access_helpers import Row, assert_rows, level
from apps.traceability.access import TRACE

TRACE_PAGE = ("laboratuvar", "yonetim")

ROWS = [
    Row(
        "API TraceView (lots/<pk>/backward, lots/<pk>/forward, recall, recall/xlsx, recall/pdf; "
        "TRACE_ROLES)",
        TRACE_PAGE,
        level(TRACE),
    ),
    # Bugün sınıf düzeyindeki HasRole her metodu (yazma metotları dahil) denetler.
    Row("API TraceView karşılanmayan metot (TRACE_ROLES)", TRACE_PAGE, level(TRACE)),
    # --- kabuk: modülün menü ve rota girişleri ---
    Row(
        "Ön yüz layout/menu.ts MENU traceability.roles",
        TRACE_PAGE,
        level(TRACE),
    ),
    Row(
        "Ön yüz routes.tsx izlenebilirlik/:tab? (menuRoles('traceability'))",
        TRACE_PAGE,
        level(TRACE),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
