"""Görevler: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.17 ve §5.7).

"Tüm birimlerin görevleri" başka rollerin görevlerini bugünkü gibi gösterir; kişinin kendi
rollerinin görevlerinde karar 5 geçerlidir. Görev ve bildirim kurallarının gerektirdiği yetkiler
`rules.py`'de kuralın alanıdır (7. adım).
"""

from apps.core.access import VIEW, grant, register_module, register_section
from apps.core.roles import YONETIM

# Görevlerim herkese açıktır; "Tüm birimlerin görevleri" menüde modül açmaz.
register_module("workflow", "Görevler", order=170, menu=False)

ALL_TASKS = register_section(
    "workflow.all_tasks",
    "Tüm birimlerin görevleri",
    levels=(VIEW,),
    help={VIEW: "Başka rollerin görevlerini de görür."},
)

grant(YONETIM, ALL_TASKS, VIEW)
