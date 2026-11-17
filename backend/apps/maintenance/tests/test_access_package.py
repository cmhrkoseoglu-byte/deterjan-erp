"""Bakım: paket denkliği (docs/plan/kisi-yetkileri.md §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, kayıt türü, ön yüz) planın §3.12 tablosundaki yetkiye
eşlenir. Kişiye özel ayar yokken eski ve yeni denetim, admin dışındaki 8 rolün bütün
bileşimlerinde aynı kararı verir.

Sorumlu birim kuralı (`services._can_work`, ön yüzde `canWork`): iş emrini sorumlu rol ya da
yönetim yürütür. Sorumlu rol iş verisidir ve rol denetimi olarak kalır (plan §4 satır kuralları);
yalnız yönetim istisnası "Tüm birimlerin iş emirlerini yürütme"ye eşlenir.

Satır olmayanlar (rolle kalır, iş verisi):
- `services.default_role` ve `record_cleaning`'in `responsible_role=URETIM`'i: iş emrinin sorumlu
  birimi (görev yönlendirme).
- `models.ROLE_CHOICES` ve `MaintenancePage`'deki `ROLE_OPTIONS`: sorumlu birim seçenekleri.
- Tank temizliği kaydında açılan iş emrinin tamamlanması (`record_cleaning` içinden
  `complete_work_order`): ardıl adım, plan §5.4 giriş noktası kuralıyla denetlenmez.

5. adımda modül bölüm denetimine geçti: API, servis ve kayıt türü satırlarının `live` bağlantısı
kaldırıldı (`services`'teki rol sabitleri yok); satırlar bugünkü rollerin kataloğa denkliğini kayıt
olarak tutar.
8. adımda ön yüz de bölüm denetimine geçti: ön yüz satırlarının `live` bağlantısı kaldırıldı;
satırlar 8. adım öncesi rol listelerini dondurulmuş olarak tutar.
"""

from dataclasses import replace

from apps.core import access
from apps.core.access import CHANGE
from apps.core.tests.access_helpers import (
    ANY_ROLE,
    SIGNED_IN,
    Row,
    all_of,
    any_of,
    assert_rows,
    level,
    read,
    row_errors,
)
from apps.maintenance.access import (
    ANY_UNIT,
    BREAKDOWNS,
    CALIBRATION,
    CLEANINGS,
    DOWNTIMES,
    PLANS,
    SETTINGS,
    UNCLEANED,
    WORK_ORDERS,
)
from apps.production.access import BATCHES

# READ_ROLES ve DOWNTIME_ROLES; layout/menu.ts MENU "maintenance" de aynı birimlerdir.
UNITS = ("uretim", "dolum", "laboratuvar", "planlama", "yonetim")
PLANNERS = ("uretim", "dolum", "laboratuvar", "yonetim")  # PLAN_ROLES
LAB = ("laboratuvar",)  # CHANGEOVER_ROLES
MANAGEMENT = ("yonetim",)  # SETTINGS_ROLES

# Modül sayfaları ve menü: Görür'ü olan bölümlerin birleşimi (plan §2, §5.9). Bakım ayarlarının
# değerlerini de Bakım'ı gören herkes okur (plan §3.12).
MODULE_VIEW = any_of(*(level(item) for item in access.sections("maintenance") if item.has_view))
# Şarj başlatma ve tartım, kalibrasyon ve tank temizliği durumunu "Kalibrasyon: Görür" ya da
# "Şarj ve tartım: Değiştirir" ile okur (plan §5.4).
EQUIPMENT_STATUS = any_of(level(CALIBRATION), level(BATCHES, CHANGE))

ROWS = [
    # --- API: apps/maintenance/api/views.py ---------------------------------------------------
    Row(
        "views.MaintenancePlanViewSet GET (READ_ROLES)",
        UNITS,
        read(PLANS),
    ),
    Row(
        "views.MaintenancePlanViewSet create, update, activate, deactivate (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "views.WorkOrderViewSet GET (READ_ROLES)",
        UNITS,
        read(WORK_ORDERS),
    ),
    Row(
        "views.WorkOrderViewSet.create elle iş emri (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "views.WorkOrderViewSet start, complete, cancel, parts (READ_ROLES)",
        UNITS,
        level(WORK_ORDERS, CHANGE),
    ),
    Row("views.BreakdownView POST (HasRole(*ALL_ROLES))", ANY_ROLE, level(BREAKDOWNS, CHANGE)),
    Row(
        "views.CleaningView POST (READ_ROLES)",
        UNITS,
        level(CLEANINGS),
    ),
    Row(
        "views.CleaningCheckView GET (READ_ROLES)",
        UNITS,
        EQUIPMENT_STATUS,
    ),
    Row("views.DowntimeViewSet GET (HasRole(*ALL_ROLES))", ANY_ROLE, read(DOWNTIMES)),
    Row(
        "views.DowntimeViewSet create, end (DOWNTIME_ROLES)",
        UNITS,
        level(DOWNTIMES, CHANGE),
    ),
    Row(
        "views.DowntimeSummaryView GET (READ_ROLES)",
        UNITS,
        level(DOWNTIMES),
    ),
    Row(
        "views.CalibrationStatusView GET (READ_ROLES)",
        UNITS,
        EQUIPMENT_STATUS,
    ),
    Row(
        "views.ChangeoverRuleViewSet GET (READ_ROLES)",
        UNITS,
        read(UNCLEANED),
    ),
    Row(
        "views.ChangeoverRuleViewSet create, activate, deactivate (CHANGEOVER_ROLES)",
        LAB,
        level(UNCLEANED, CHANGE),
    ),
    Row(
        "views.MaintenanceSettingsView GET (READ_ROLES)",
        UNITS,
        MODULE_VIEW,
    ),
    Row(
        "views.MaintenanceSettingsView PATCH (SETTINGS_ROLES)",
        MANAGEMENT,
        level(SETTINGS, CHANGE),
    ),
    # Bugün `get_permissions` yalnız GET'i okuma sayar: HEAD, OPTIONS ve karşılanmayan metotlar (ör.
    # planda silme, ayarlarda POST) yazma rolüyle denetlenir, sonra DRF 405 döner. Karşılanmayan
    # yoldaki GET (ör. `plans/{pk}/activate/`) okuma rolüyle. İş emirlerinde yalnız `create` yazma
    # rolündedir; HEAD, OPTIONS ve öteki metotlar okuma rollerindedir (READ_ROLES). Tek kurallı
    # APIView'larda (arıza, temizlik, temizlik kontrolü, kalibrasyon, duruş özeti) her metot aynı
    # kuraldadır.
    Row(
        "views.MaintenancePlanViewSet HEAD, OPTIONS, karşılanmayan metot (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "views.MaintenancePlanViewSet karşılanmayan yoldaki GET (READ_ROLES)",
        UNITS,
        read(PLANS),
    ),
    Row(
        "views.WorkOrderViewSet HEAD, OPTIONS, karşılanmayan yoldaki GET (READ_ROLES)",
        UNITS,
        read(WORK_ORDERS),
    ),
    Row(
        "views.WorkOrderViewSet karşılanmayan metot (READ_ROLES)",
        UNITS,
        level(WORK_ORDERS, CHANGE),
    ),
    Row(
        "views.DowntimeViewSet HEAD, OPTIONS, karşılanmayan metot (DOWNTIME_ROLES)",
        UNITS,
        level(DOWNTIMES, CHANGE),
    ),
    Row(
        "views.DowntimeViewSet karşılanmayan yoldaki GET (HasRole(*ALL_ROLES))",
        ANY_ROLE,
        read(DOWNTIMES),
    ),
    Row(
        "views.ChangeoverRuleViewSet HEAD, OPTIONS, karşılanmayan metot (CHANGEOVER_ROLES)",
        LAB,
        level(UNCLEANED, CHANGE),
    ),
    Row(
        "views.ChangeoverRuleViewSet karşılanmayan yoldaki GET (READ_ROLES)",
        UNITS,
        read(UNCLEANED),
    ),
    Row(
        "views.MaintenanceSettingsView HEAD, OPTIONS, karşılanmayan metot (SETTINGS_ROLES)",
        MANAGEMENT,
        level(SETTINGS, CHANGE),
    ),
    # --- servis: apps/maintenance/services.py (_require_role) -----------------------------------
    Row(
        "services.update_settings (SETTINGS_ROLES)",
        MANAGEMENT,
        level(SETTINGS, CHANGE),
    ),
    Row(
        "services.create_plan (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "services.update_plan (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "services.set_plan_active (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "services.create_work_order (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "services.report_breakdown (BREAKDOWN_ROLES = ALL_ROLES)",
        ANY_ROLE,
        level(BREAKDOWNS, CHANGE),
    ),
    Row(
        "services._can_work yönetim istisnası (start_work_order, complete_work_order, "
        "cancel_work_order, add_part)",
        MANAGEMENT,
        level(ANY_UNIT, CHANGE),
    ),
    Row(
        "services.record_cleaning (URETIM, YONETIM)",
        ("uretim", "yonetim"),
        level(CLEANINGS, CHANGE),
    ),
    Row(
        "services.start_downtime (DOWNTIME_ROLES)",
        UNITS,
        level(DOWNTIMES, CHANGE),
    ),
    Row(
        "services.end_downtime (DOWNTIME_ROLES)",
        UNITS,
        level(DOWNTIMES, CHANGE),
    ),
    Row(
        "services.create_changeover_rule (CHANGEOVER_ROLES)",
        LAB,
        level(UNCLEANED, CHANGE),
    ),
    Row(
        "services.set_changeover_active (CHANGEOVER_ROLES)",
        LAB,
        level(UNCLEANED, CHANGE),
    ),
    # --- kayıt türü: apps/maintenance/apps.py (register_record_type) ---------------------------
    Row(
        "records maintenance.maintenanceworkorder (yorum, geçmiş, ek; READ_ROLES)",
        UNITS,
        read(WORK_ORDERS),
    ),
    # --- ön yüz: menü ve rotalar ----------------------------------------------------------------
    Row("layout/menu.ts MENU maintenance", UNITS, MODULE_VIEW),
    Row(
        "routes.tsx maintenancePage: bakim/:tab?, bakim/is-emirleri/:workOrderId",
        UNITS,
        MODULE_VIEW,
    ),
    # --- ön yüz: frontend/src/modules/maintenance -----------------------------------------------
    Row(
        "MaintenancePage TABS is-emirleri (READ_ROLES)",
        UNITS,
        level(WORK_ORDERS),
    ),
    Row(
        "MaintenancePage TABS duruslar (READ_ROLES)",
        UNITS,
        level(DOWNTIMES),
    ),
    Row(
        "MaintenancePage TABS planlar (READ_ROLES)",
        UNITS,
        level(PLANS),
    ),
    Row(
        "MaintenancePage TABS kalibrasyon (READ_ROLES)",
        UNITS,
        level(CALIBRATION),
    ),
    Row(
        "MaintenancePage TABS temizliksiz-gecisler (READ_ROLES)",
        UNITS,
        level(UNCLEANED),
    ),
    Row(
        "MaintenancePage TABS ayarlar (SETTINGS_ROLES)",
        MANAGEMENT,
        level(SETTINGS),
    ),
    Row(
        "MaintenancePage başlıktaki BreakdownButton (koşulsuz; sayfa koruması)",
        UNITS,
        all_of(MODULE_VIEW, level(BREAKDOWNS, CHANGE)),
    ),
    Row(
        "MaintenancePage WorkOrdersTab yeni iş emri düğmesi (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "MaintenancePage PlansTab yeni plan, düzenle, etkinleştir ve pasife al (PLAN_ROLES)",
        PLANNERS,
        level(PLANS, CHANGE),
    ),
    Row(
        "MaintenancePage DowntimesTab duruş başlat düğmesi (DOWNTIME_ROLES)",
        UNITS,
        level(DOWNTIMES, CHANGE),
    ),
    Row(
        "MaintenancePage OpenDowntimes duruşu bitir düğmesi (DOWNTIME_ROLES)",
        UNITS,
        level(DOWNTIMES, CHANGE),
    ),
    Row(
        "MaintenancePage ChangeoversTab yeni kural, etkinleştir ve pasife al (CHANGEOVER_ROLES)",
        LAB,
        level(UNCLEANED, CHANGE),
    ),
    Row(
        "config.ts canWork yönetim istisnası (WorkOrderPage işe başla, parça, tamamla, iptal)",
        MANAGEMENT,
        level(ANY_UNIT, CHANGE),
    ),
]

# Plan §8 madde 1: rolsüz kullanıcı Görevlerim'deki "Arıza bildir" düğmesini görmez. Düğme bugün
# koşulsuzdur; yeni yetki rolü olan herkese verir. Fark yalnız rolsüz kullanıcıdadır.
ROLELESS_CHANGES = [
    Row("pages/HomePage.tsx BreakdownButton (koşulsuz)", SIGNED_IN, level(BREAKDOWNS, CHANGE)),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def test_roleless_day_one_change() -> None:
    """§8 madde 1 dışında fark yok: her satır yalnız rolsüz kullanıcıda ayrılır."""
    for row in ROLELESS_CHANGES:
        assert row.roles == SIGNED_IN, row.source
        assert row_errors([row]), f"{row.source}: fark kalmadı; satırı ROWS'a taşıyın."
    assert_rows([replace(row, roles=ANY_ROLE) for row in ROLELESS_CHANGES])
