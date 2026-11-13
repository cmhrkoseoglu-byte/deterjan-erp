"""İSG ve çevre: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.13).

Kaza ve arıza bildirmek rolü olan herkesin hakkıdır; bu yetkiler kişiden kaldırılamaz. İSG
ayarlarının değerlerini GBF arşivini gören herkes okuyabilir.
"""

from apps.core.access import (
    ANY_ROLE,
    CHANGE,
    VIEW,
    grant,
    register_module,
    register_readers,
    register_section,
)
from apps.core.roles import DEPO, LABORATUVAR, YONETIM

register_module("hse", "İSG ve çevre", order=130)

INCIDENT_REPORT = register_section(
    "hse.incident_report",
    "Olay bildirimi",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Kişinin kendi bildirdiği olaylar.",
        CHANGE: "Olay bildirir; kendi olayına yorum ve fotoğraf ekler.",
    },
    locked=(VIEW, CHANGE),
)
INCIDENTS = register_section(
    "hse.incidents",
    "Olaylar ve kazalar",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Bütün olaylar (yaralanan kişi ve yaralanma bilgisi).",
        CHANGE: "Olayı inceler, kapatır, iptal eder.",
    },
    restricted_to_role=YONETIM,
)
SDS = register_section(
    "hse.sds",
    "GBF arşivi",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "GBF'ler, eksik ve süresi geçmiş GBF raporu.",
        CHANGE: "Yeni GBF ekler, PDF yükler.",
    },
)
HAZARDS = register_section(
    "hse.hazards",
    "Tehlike bilgileri ve H/P ifadeleri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Malzemenin tehlike bilgisi ve H/P ifadeleri.",
        CHANGE: "Tehlike bilgisini ve H/P ifadelerini düzenler.",
    },
    locked=(VIEW,),
)
STORAGE = register_section(
    "hse.storage",
    "Depolama limitleri",
    levels=(VIEW, CHANGE),
    help={VIEW: "Tehlikeli madde depolama limitleri.", CHANGE: "Limitleri düzenler."},
)
WASTE = register_section(
    "hse.waste",
    "Atık",
    levels=(VIEW, CHANGE),
    help={VIEW: "Atık kayıtları.", CHANGE: "Atık kaydı açar ve düzenler."},
)
SUMMARY = register_section(
    "hse.summary",
    "İSG özeti",
    levels=(VIEW,),
    help={VIEW: "Sayılar (isim yok)."},
)
SETTINGS = register_section(
    "hse.settings",
    "İSG ayarları",
    levels=(VIEW, CHANGE),
    help={VIEW: "GBF en çok yaşı.", CHANGE: "İSG ayarlarını değiştirir."},
)

register_readers("hse.safetydatasheet", SDS)
register_readers("hse.wasterecord", WASTE)
register_readers("hse.incident", INCIDENTS, INCIDENT_REPORT)

grant(ANY_ROLE, INCIDENT_REPORT, VIEW, CHANGE)
grant(YONETIM, INCIDENTS, VIEW, CHANGE)
for role in (YONETIM, DEPO, LABORATUVAR):
    grant(role, SDS, VIEW)
grant(YONETIM, SDS, CHANGE)
grant(ANY_ROLE, HAZARDS, VIEW)
for role in (YONETIM, LABORATUVAR):
    grant(role, HAZARDS, CHANGE)
for role in (YONETIM, DEPO):
    grant(role, STORAGE, VIEW)
grant(YONETIM, STORAGE, CHANGE)
grant(YONETIM, WASTE, VIEW, CHANGE)
grant(YONETIM, SUMMARY, VIEW)
grant(YONETIM, SETTINGS, VIEW, CHANGE)
