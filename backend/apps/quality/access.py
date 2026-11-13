"""Kalite kontrol: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.5)."""

from apps.core.access import (
    APPROVE,
    CHANGE,
    VIEW,
    ReadScope,
    grant,
    register_module,
    register_open_records,
    register_readers,
    register_section,
)
from apps.core.roles import LABORATUVAR, YONETIM

register_module("quality", "Kalite kontrol", order=50)

SAMPLES = register_section(
    "quality.samples",
    "Numuneler ve kalite kararı",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Numuneler, sonuçlar ve kararlar.",
        CHANGE: "Numune açar, numune alma bilgilerini düzenler, spesifikasyon atar, sonuç girer ve "
        "düzeltir, numuneyi iptal eder (Numune kuyruğu sekmesi).",
        APPROVE: "Karar verir: serbest bırakır, reddeder, yeniden işletir, şartlı kabul önerir.",
    },
    read=ReadScope.OPEN,
)
CONDITIONAL = register_section(
    "quality.conditional",
    "Şartlı kabul onayı",
    levels=(VIEW, APPROVE),
    help={
        VIEW: "Onay bekleyen şartlı kabuller.",
        APPROVE: "Önerilen şartlı kabulü onaylar ya da reddeder; öneren kişi onaylayamaz.",
    },
)
SPECS = register_section(
    "quality.specs",
    "Spesifikasyonlar ve test tanımları",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Spesifikasyon sürümleri ve test tanımları.",
        CHANGE: "Spesifikasyon ve test tanımı açar ve düzenler.",
        APPROVE: "Spesifikasyon sürümünü onaylar.",
    },
    read=ReadScope.OPEN,
)
OPEN_RECORDS = register_open_records("quality")

register_readers("quality.sample", SAMPLES, CONDITIONAL)

grant(LABORATUVAR, SAMPLES, VIEW, CHANGE, APPROVE)
grant(YONETIM, SAMPLES, VIEW)
grant(YONETIM, CONDITIONAL, VIEW, APPROVE)
grant(LABORATUVAR, SPECS, VIEW, CHANGE, APPROVE)
grant(YONETIM, SPECS, VIEW)
