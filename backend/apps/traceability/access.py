"""İzlenebilirlik: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.9)."""

from apps.core.access import VIEW, grant, register_module, register_section
from apps.core.roles import LABORATUVAR, YONETIM

register_module("traceability", "İzlenebilirlik", order=90)

TRACE = register_section(
    "traceability.trace",
    "Geri ve ileri izleme, geri çağırma",
    levels=(VIEW,),
    help={VIEW: "Geri ve ileri izleme ile geri çağırma raporları, Excel ve PDF."},
)

for role in (LABORATUVAR, YONETIM):
    grant(role, TRACE, VIEW)
