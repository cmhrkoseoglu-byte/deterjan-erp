"""Görevler: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.17 ve §5.7).

"Tüm birimlerin görevleri" başka rollerin görevlerini bugünkü gibi gösterir; kişinin kendi
rollerinin görevlerinde karar 5 geçerlidir. Görev ve bildirim kurallarının gerektirdiği yetkiler
`rules.py`'de kuralın alanıdır (`requires=`); workflow onları `apps.py`'de core'un kayıt defterine
yazar.
"""

from django.db.models import Q

from apps.core.access import (
    APPROVE,
    CHANGE,
    PRICES,
    VIEW,
    grant,
    register_audit_model,
    register_audit_parent,
    register_module,
    register_risky_pair,
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

# Denetim günlüğü (plan §5.6): yorum ve kayda bağlı görev bağlı olduğu kaydı izler (görev: sahip
# kararı 2026-11-17; ör. olay inceleme görevi "Olaylar ve kazalar: Görür" ister); satın alma onayı
# görevinin açıklaması (tutarlar) Fiyatları görür ister.
register_audit_parent("workflow.comment")
register_audit_parent(
    "workflow.task",
    content_type_field="related_content_type",
    object_id_field="related_object_id",
)
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


# Görev ayrılığı (plan §5.11): riskli yetki çiftleri tek yerde. workflow her modülü dinlediği için
# bağımlılık denetiminden muaftır; çiftler birbirine bağlı olmayan modülleri (üretim ve kalite)
# birleştirdiği için burada kaydedilir. İki yetki aynı rol paketinden geliyorsa uyarı çıkmaz.
SAMPLE_DECISION = ("quality.samples", APPROVE)
register_risky_pair(("production.batches", CHANGE), SAMPLE_DECISION)
register_risky_pair(("filling.runs", CHANGE), SAMPLE_DECISION)
register_risky_pair(("inventory.receipts", CHANGE), SAMPLE_DECISION)
register_risky_pair(
    ("purchasing.settings", CHANGE),
    ("purchasing.orders", APPROVE),
    ("purchasing.over_limit", APPROVE),
)
register_risky_pair(SAMPLE_DECISION, ("quality.conditional", APPROVE))
