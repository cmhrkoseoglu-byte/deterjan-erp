"""İSG ve çevre: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, ek kuralı, kayıt türü, ön yüz) planın §3.13 tablosundaki
yetkiye eşlenir. Kişiye özel ayar yokken eski ve yeni denetim, admin dışındaki 8 rolün bütün
bileşimlerinde aynı kararı verir. `live=` satırları koddaki rol sabitine de bağlıdır.

Rolsüz kullanıcı farkı (plan §8 madde 1): İSG menüsü ve sayfası, "olaylar", "tehlike" ve
"ifadeler" sekmeleri ve "Olay bildir" düğmesi bugün giriş yapan herkese açıktır (`roles: []`);
yeni yetki bunları rolü olan herkese verir. Bu satırlar `ROLELESS_CHANGES`'tadır.

Satır olmayanlar (satır kuralı, rol değil; plan §4): olayı bildiren kendi olayını görür ve
fotoğraf ekler (`incidents_visible_to` ve `can_attach_incident`'teki `created_by` kısmı).
"""

from dataclasses import replace

from apps.core import access
from apps.core.access import CHANGE
from apps.core.roles import ALL_ROLES
from apps.core.tests.access_helpers import (
    ANY_ROLE,
    SIGNED_IN,
    Row,
    all_of,
    any_of,
    assert_rows,
    frontend_roles,
    level,
    read,
    row_errors,
)
from apps.hse import services
from apps.hse.access import (
    HAZARDS,
    INCIDENT_REPORT,
    INCIDENTS,
    SDS,
    SETTINGS,
    STORAGE,
    SUMMARY,
    WASTE,
)

SERVICES = "apps.hse.services"
CONFIG = "frontend:src/modules/hse/config.ts"
MANAGEMENT = ("yonetim",)  # HSE_ROLES, SETTINGS_ROLES
HAZARD_WRITERS = ("yonetim", "laboratuvar")  # HAZARD_ROLES
SDS_READERS = ("yonetim", "depo", "laboratuvar")  # SDS_READ_ROLES
STORAGE_READERS = ("yonetim", "depo")  # STORAGE_READ_ROLES

# Olay kaydı: bütün olaylar Olaylar ve kazalar ile, kişinin kendi olayları Olay bildirimi ile
# okunur (plan §5.1); hangi olayların döneceği ayrıca `incidents_visible_to` satırındadır.
INCIDENT_READ = read(INCIDENTS, INCIDENT_REPORT)
# Modül sayfaları ve menü: Görür'ü olan bölümlerin birleşimi (plan §2, §5.9).
MODULE_VIEW = any_of(*(level(item) for item in access.sections("hse") if item.has_view))

ROWS = [
    # --- API: apps/hse/api/views.py -------------------------------------------------------------
    Row(
        "views.HazardStatementViewSet GET (HAZARD_READ_ROLES = ALL_ROLES)",
        ANY_ROLE,
        read(HAZARDS),
    ),
    Row(
        "views.HazardStatementViewSet create, partial_update, activate, deactivate (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{SERVICES}:HAZARD_ROLES",
    ),
    Row(
        "views.MaterialHazardViewSet GET (HAZARD_READ_ROLES = ALL_ROLES)",
        ANY_ROLE,
        read(HAZARDS),
    ),
    Row("views.MaterialHazardView GET (HAZARD_READ_ROLES = ALL_ROLES)", ANY_ROLE, read(HAZARDS)),
    Row(
        "views.MaterialHazardView PUT (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{SERVICES}:HAZARD_ROLES",
    ),
    Row(
        "views.SafetyDataSheetViewSet GET (SDS_READ_ROLES)",
        SDS_READERS,
        read(SDS),
        live=f"{SERVICES}:SDS_READ_ROLES",
    ),
    Row(
        "views.SafetyDataSheetViewSet create, partial_update (HSE_ROLES)",
        MANAGEMENT,
        level(SDS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.SdsGapsView GET (SDS_READ_ROLES)",
        SDS_READERS,
        level(SDS),
        live=f"{SERVICES}:SDS_READ_ROLES",
    ),
    Row(
        "views.SdsGapsExportView GET Excel (SDS_READ_ROLES)",
        SDS_READERS,
        level(SDS),
        live=f"{SERVICES}:SDS_READ_ROLES",
    ),
    Row(
        "views.StorageLimitViewSet GET (STORAGE_READ_ROLES)",
        STORAGE_READERS,
        read(STORAGE),
        live=f"{SERVICES}:STORAGE_READ_ROLES",
    ),
    Row(
        "views.StorageLimitViewSet create, partial_update, activate, deactivate (HSE_ROLES)",
        MANAGEMENT,
        level(STORAGE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.StorageUtilisationView GET (STORAGE_READ_ROLES)",
        STORAGE_READERS,
        level(STORAGE),
        live=f"{SERVICES}:STORAGE_READ_ROLES",
    ),
    Row(
        "views.WasteContractorViewSet GET (HSE_ROLES)",
        MANAGEMENT,
        read(WASTE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.WasteContractorViewSet create, partial_update, activate, deactivate (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.WasteRecordViewSet GET (HSE_ROLES)",
        MANAGEMENT,
        read(WASTE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.WasteRecordViewSet create, cancel (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.IncidentViewSet GET (INCIDENT_REPORT_ROLES = ALL_ROLES)",
        ANY_ROLE,
        INCIDENT_READ,
    ),
    Row(
        "views.IncidentViewSet.create olay bildirimi (INCIDENT_REPORT_ROLES = ALL_ROLES)",
        ANY_ROLE,
        level(INCIDENT_REPORT, CHANGE),
    ),
    Row(
        "views.IncidentViewSet investigate, investigation, close, cancel (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "views.HseSummaryView GET (HSE_ROLES)",
        MANAGEMENT,
        level(SUMMARY),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    # Değerleri ayarlar sekmesini ve GBF arşivini gören okur (plan §2, §3.13).
    Row(
        "views.HseSettingsView GET (SDS_READ_ROLES)",
        SDS_READERS,
        any_of(level(SETTINGS), level(SDS)),
        live=f"{SERVICES}:SDS_READ_ROLES",
    ),
    Row(
        "views.HseSettingsView PATCH (SETTINGS_ROLES)",
        MANAGEMENT,
        level(SETTINGS, CHANGE),
        live=f"{SERVICES}:SETTINGS_ROLES",
    ),
    # --- servis: apps/hse/services.py (_require_role, user_has_role) ----------------------------
    Row(
        "services.incidents_visible_to bütün olaylar (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.update_settings (SETTINGS_ROLES)",
        MANAGEMENT,
        level(SETTINGS, CHANGE),
        live=f"{SERVICES}:SETTINGS_ROLES",
    ),
    Row(
        "services.create_statement (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{SERVICES}:HAZARD_ROLES",
    ),
    Row(
        "services.update_statement (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{SERVICES}:HAZARD_ROLES",
    ),
    Row(
        "services.set_statement_active (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{SERVICES}:HAZARD_ROLES",
    ),
    Row(
        "services.set_material_hazard (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{SERVICES}:HAZARD_ROLES",
    ),
    Row(
        "services.create_sds (HSE_ROLES)",
        MANAGEMENT,
        level(SDS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.update_sds (HSE_ROLES)",
        MANAGEMENT,
        level(SDS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.create_storage_limit (HSE_ROLES)",
        MANAGEMENT,
        level(STORAGE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.update_storage_limit (HSE_ROLES)",
        MANAGEMENT,
        level(STORAGE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.set_storage_limit_active (HSE_ROLES)",
        MANAGEMENT,
        level(STORAGE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.create_contractor (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.update_contractor (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.set_contractor_active (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.record_waste (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.cancel_waste_record (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.report_incident (INCIDENT_REPORT_ROLES = ALL_ROLES)",
        ANY_ROLE,
        level(INCIDENT_REPORT, CHANGE),
    ),
    Row(
        "services.start_investigation (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.update_investigation (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.close_incident (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.cancel_incident (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    # --- ek kuralları: apps/hse/apps.py (register_attachment_target can_add) --------------------
    Row(
        "services.can_attach_sds GBF PDF'i (HSE_ROLES)",
        MANAGEMENT,
        level(SDS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.can_attach_waste atık belgesi (HSE_ROLES)",
        MANAGEMENT,
        level(WASTE, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "services.can_attach_incident başkasının olayına fotoğraf (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    # --- kayıt türleri: apps/hse/apps.py (register_record_type) ---------------------------------
    Row(
        "records hse.safetydatasheet (yorum, geçmiş, ek; SDS_READ_ROLES)",
        SDS_READERS,
        read(SDS),
        live=f"{SERVICES}:SDS_READ_ROLES",
    ),
    Row(
        "records hse.wasterecord (yorum, geçmiş, ek; HSE_ROLES)",
        MANAGEMENT,
        read(WASTE),
        live=f"{SERVICES}:HSE_ROLES",
    ),
    Row(
        "records hse.incident (yorum, geçmiş, ek; INCIDENT_REPORT_ROLES = ALL_ROLES)",
        ANY_ROLE,
        INCIDENT_READ,
    ),
    # --- ön yüz: frontend/src/modules/hse -------------------------------------------------------
    Row(
        "HsePage TABS gbf (SDS_READ_ROLES)",
        SDS_READERS,
        level(SDS),
        live=f"{CONFIG}:SDS_READ_ROLES",
    ),
    Row(
        "HsePage TABS depolama (STORAGE_READ_ROLES)",
        STORAGE_READERS,
        level(STORAGE),
        live=f"{CONFIG}:STORAGE_READ_ROLES",
    ),
    Row("HsePage TABS atik (HSE_ROLES)", MANAGEMENT, level(WASTE), live=f"{CONFIG}:HSE_ROLES"),
    Row("HsePage TABS ozet (HSE_ROLES)", MANAGEMENT, level(SUMMARY), live=f"{CONFIG}:HSE_ROLES"),
    Row(
        "HsePage TABS ayarlar (HSE_ROLES)",
        MANAGEMENT,
        level(SETTINGS),
        live=f"{CONFIG}:HSE_ROLES",
    ),
    Row(
        "HsePage IncidentsTab yalnız kendi bildirdikleri notu (HSE_ROLES değilse)",
        MANAGEMENT,
        level(INCIDENTS),
        live=f"{CONFIG}:HSE_ROLES",
    ),
    Row(
        "HsePage SdsTab yeni GBF düğmesi (HSE_ROLES)",
        MANAGEMENT,
        level(SDS, CHANGE),
        live=f"{CONFIG}:HSE_ROLES",
    ),
    Row(
        "HsePage SdsModal düzenlenebilir form (HSE_ROLES)",
        MANAGEMENT,
        level(SDS, CHANGE),
        live=f"{CONFIG}:HSE_ROLES",
    ),
    Row(
        "HsePage HazardsTab tehlike bilgisi girilecek malzeme seçimi (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{CONFIG}:HAZARD_ROLES",
    ),
    Row(
        "HsePage StatementsTab yeni ifade, düzelt, etkinleştir ve pasife al (HAZARD_ROLES)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{CONFIG}:HAZARD_ROLES",
    ),
    Row(
        "HsePage StorageTab limit ekle, düzelt, etkinleştir ve pasife al (HSE_ROLES)",
        MANAGEMENT,
        level(STORAGE, CHANGE),
        live=f"{CONFIG}:HSE_ROLES",
    ),
    Row(
        "IncidentPage incele, kapat, iptal ve inceleme formu (HSE_ROLES)",
        MANAGEMENT,
        level(INCIDENTS, CHANGE),
        live=f"{CONFIG}:HSE_ROLES",
    ),
    Row(
        "MaterialHazardModal düzenle düğmesi (HAZARD_ROLES; ana veriler malzeme satırı)",
        HAZARD_WRITERS,
        level(HAZARDS, CHANGE),
        live=f"{CONFIG}:HAZARD_ROLES",
    ),
]

# Plan §8 madde 1: rolsüz kullanıcı İSG menüsünü ve sayfalarını görmez. Bunlar bugün giriş yapan
# herkese açıktır (arkalarındaki çağrılar rolsüz kullanıcıya bugün de 403 döner); yeni yetki rolü
# olan herkese verir. Fark yalnız rolsüz kullanıcıdadır.
ROLELESS_CHANGES = [
    Row("layout/menu.ts MENU hse (roles: [])", SIGNED_IN, MODULE_VIEW),
    Row(
        "routes.tsx hsePage: isg/:tab?, isg/olaylar/:incidentId (menuRoles hse: [])",
        SIGNED_IN,
        MODULE_VIEW,
    ),
    Row(
        "HsePage TABS olaylar (INCIDENT_ROLES = [])",
        SIGNED_IN,
        any_of(level(INCIDENT_REPORT), level(INCIDENTS)),
    ),
    Row("HsePage TABS tehlike (roles: [])", SIGNED_IN, level(HAZARDS)),
    Row("HsePage TABS ifadeler (roles: [])", SIGNED_IN, level(HAZARDS)),
    Row(
        "HsePage başlıktaki IncidentReportButton (koşulsuz; sayfa koruması [])",
        SIGNED_IN,
        all_of(MODULE_VIEW, level(INCIDENT_REPORT, CHANGE)),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_roleless_day_one_change() -> None:
    """§8 madde 1 dışında fark yok: her satır yalnız rolsüz kullanıcıda ayrılır."""
    for row in ROLELESS_CHANGES:
        assert row.roles == SIGNED_IN, row.source
        assert row_errors([row]), f"{row.source}: fark kalmadı; satırı ROWS'a taşıyın."
    assert_rows([replace(row, roles=ANY_ROLE) for row in ROLELESS_CHANGES])


def test_open_role_constants() -> None:
    """`ANY_ROLE` ve `SIGNED_IN` satırları `live` taşıyamaz; bugünkü sabitler burada sabitlenir.
    Ön yüzde boş rol listesi giriş yapan herkes demektir (`hasAnyRole`)."""
    assert services.HAZARD_READ_ROLES == ALL_ROLES
    assert services.INCIDENT_REPORT_ROLES == ALL_ROLES
    assert frontend_roles("src/modules/hse/config.ts", "INCIDENT_ROLES") == ()
