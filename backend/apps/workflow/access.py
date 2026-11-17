"""Görevler: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.17 ve §5.7).

"Tüm birimlerin görevleri" başka rollerin görevlerini bugünkü gibi gösterir; kişinin kendi
rollerinin görevlerinde karar 5 geçerlidir. Görev ve bildirim kurallarının gerektirdiği yetkiler
`rules.py`'de kuralın alanıdır (7. adım).
"""

from django.db.models import Q

from apps.core.access import (
    PRICES,
    VIEW,
    grant,
    register_audit_model,
    register_audit_parent,
    register_module,
    register_section,
)
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

# Denetim günlüğü (plan §5.6): yorum bağlı olduğu kaydı izler; satın alma onayı görevinin
# açıklaması (tutarlar) Fiyatları görür ister.
register_audit_parent("workflow.comment")
PURCHASE_ORDER_APPROVAL = "purchase_order_approval"


def _purchase_order_approval_tasks() -> Q:
    from apps.workflow.models import Task

    tasks = Task.objects.filter(rule_code=PURCHASE_ORDER_APPROVAL).values("pk")
    return Q(object_id__in=tasks) | Q(changes__rule_code__1=PURCHASE_ORDER_APPROVAL)


register_audit_model(
    "workflow.task",
    requires=[PRICES],
    rows=_purchase_order_approval_tasks,
    fields=("description",),
)
