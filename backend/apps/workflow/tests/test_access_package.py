"""Paket denkliği: görevler (docs/plan/kisi-yetkileri.md §3.17, §5.7, §5.5 3. parça).

Yönetimin başka rollerin görevlerini de görmesi "Tüm birimlerin görevleri" bölümüne eşlenir.
Görevin ve bildirimin role gitmesi (kuralların rolleri, rol üyeleri, görevin rolündeki kişinin
üstlenmesi) rol yönlendirmesidir; yetki satırı değildir (7. adımda kurala `requires=` eklenir).
"""

from apps.core.tests.access_helpers import Row, assert_rows, level
from apps.workflow.access import ALL_TASKS

ROWS: list[Row] = [
    Row(
        "workflow.selectors.tasks_visible_to: yonetim bütün görevleri görür (TaskViewSet)",
        ("yonetim",),
        level(ALL_TASKS),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
