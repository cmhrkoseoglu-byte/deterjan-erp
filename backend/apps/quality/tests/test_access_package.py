"""Kalite kontrol: paket denkliği (docs/plan/kisi-yetkileri.md §3.5 ve §5.5, 3. parça).

Bugünkü her rol denetimi (API, servis, kayıt türü, kod önerisi ve ön yüz) bir yetki ifadesine
eşlenir. Kişiye özel ayar yokken eski denetim ile yeni yetki, admin dışındaki 8 rolün bütün
bileşimlerinde aynı kararı verir. `live` satırları koddaki rol sabitini de denetler.

Satır olmayanlar: `open_sample` denetim yapmaz (yetkiyi çağıran denetler; numune açılması ardıl
adımdır, plan §5.4). Kalite sayfasının varsayılan sekme seçimi (`QualityPage.tsx`: laboratuvar
olmayan yönetim onay sekmesine düşer) rol görünümüdür ve rol bazlı kalır (plan §5.9).
"""

from apps.core.access import APPROVE, CHANGE
from apps.core.tests.access_helpers import SIGNED_IN, Row, any_of, assert_rows, level, read
from apps.inventory.access import LOTS
from apps.production.access import ORDERS as PRODUCTION_ORDERS
from apps.quality.access import CONDITIONAL, SAMPLES, SPECS

CONFIG = "frontend:src/modules/quality/config.ts"

LAB = ("laboratuvar",)
MANAGEMENT = ("yonetim",)
# Kalite sayfasının bugünkü koruması: menuRoles("quality").
QUALITY_PAGE = ("laboratuvar", "yonetim")

# Modülün menüsü ve birden çok bölümün kayıtlarını gösteren sayfaları: Görür'ü olan
# bölümlerinden birinde Görür (plan §2 ve §5.9).
MODULE_VIEW = any_of(level(SAMPLES), level(CONDITIONAL), level(SPECS))
# Numune kaydının okuması (plan §5.1 kayıt türleri tablosu).
SAMPLE_READ = read(SAMPLES, CONDITIONAL)

ROWS = [
    # Karşılanmayan metot (ör. numunede silme, onay yolunda GET): bugünkü `write_roles` (LAB_ROLES)
    # yedeği; kalitede yalnız list, retrieve, queue ve coa okumadır. 4. adımda unhandled_access.
    Row(
        "API RolePermissionMixin karşılanmayan metot (write_roles = LAB_ROLES; spesifikasyon ve "
        "test tanımı görünümleri)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "API RolePermissionMixin karşılanmayan metot (write_roles = LAB_ROLES; numune ve karar "
        "görünümleri)",
        LAB,
        level(SAMPLES, CHANGE),
    ),
    # --- API: yazma eylemleri (views.py, RolePermissionMixin ve write_roles) ---
    Row(
        "API TestDefinitionViewSet create, update, partial_update, activate, deactivate "
        "(write_roles = LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "API SpecificationViewSet create, update, partial_update, copy, lines (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "API SpecificationViewSet approve (LAB_ROLES)",
        LAB,
        level(SPECS, APPROVE),
    ),
    Row(
        "API SpecificationLineViewSet update, partial_update, destroy (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "API SampleViewSet create, update, partial_update, assign_specification, results, "
        "cancel (LAB_ROLES)",
        LAB,
        level(SAMPLES, CHANGE),
    ),
    Row(
        "API SampleViewSet decide (LAB_ROLES)",
        LAB,
        level(SAMPLES, APPROVE),
    ),
    Row(
        "API QualityDecisionViewSet review (action_roles = APPROVAL_ROLES)",
        MANAGEMENT,
        level(CONDITIONAL, APPROVE),
    ),
    # --- API: okumalar (READ_ACTIONS → IsAuthenticated) ---
    Row(
        "API TestDefinitionViewSet list, retrieve, metadata (IsAuthenticated)",
        SIGNED_IN,
        read(SPECS),
    ),
    Row(
        "API SpecificationViewSet list, retrieve, metadata (IsAuthenticated)",
        SIGNED_IN,
        read(SPECS),
    ),
    Row(
        "API SpecificationLineViewSet retrieve, metadata (IsAuthenticated)",
        SIGNED_IN,
        read(SPECS),
    ),
    Row(
        "API SampleViewSet list, retrieve, queue, metadata (IsAuthenticated)",
        SIGNED_IN,
        SAMPLE_READ,
    ),
    Row(
        "API SampleViewSet list ?lot= — lot sayfasının kalite bölümü (plan §5.3)",
        SIGNED_IN,
        read(LOTS),
    ),
    Row(
        "API SampleViewSet coa (coa.pdf) — Lotlar okumasını izler (plan §5.3)",
        SIGNED_IN,
        read(LOTS),
    ),
    Row(
        "API QualityDecisionViewSet list, retrieve, metadata (IsAuthenticated)",
        SIGNED_IN,
        SAMPLE_READ,
    ),
    # --- servis (services.py, _require_role) ---
    Row(
        "Servis create_test_definition, update_test_definition, set_test_active (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "Servis create_specification (copy_specification dahil), update_specification, "
        "add_spec_line, update_spec_line, remove_spec_line (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "Servis approve_specification (LAB_ROLES)",
        LAB,
        level(SPECS, APPROVE),
    ),
    Row(
        "Servis create_sample, update_sample, assign_specification, cancel_sample, "
        "record_result (LAB_ROLES)",
        LAB,
        level(SAMPLES, CHANGE),
    ),
    Row(
        "Servis decide (LAB_ROLES)",
        LAB,
        level(SAMPLES, APPROVE),
    ),
    Row(
        "Servis review_conditional_release (APPROVAL_ROLES)",
        MANAGEMENT,
        level(CONDITIONAL, APPROVE),
    ),
    # --- apps.py: kod önerisi, kayıt paneli ve ekler ---
    Row(
        "apps.py register_master_code quality.testdefinition write_roles = LAB_ROLES "
        "(core CodeSuggestView kod önerisi)",
        LAB,
        level(SPECS, CHANGE),
    ),
    Row(
        "apps.py register_record_type quality.sample, roles yok (yorum, geçmiş, ek okuması)",
        SIGNED_IN,
        SAMPLE_READ,
    ),
    Row(
        "apps.py register_attachment_target quality.sample, can_add yok (ek ekleme)",
        SIGNED_IN,
        SAMPLE_READ,
    ),
    # --- ön yüz: frontend/src/modules/quality ---
    Row(
        "Ön yüz QualityPage.tsx TABS kuyruk — Numune kuyruğu sekmesi (LAB_ROLES)",
        LAB,
        level(SAMPLES, CHANGE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz QualityPage.tsx TABS numuneler (roles [], sayfa koruması menuRoles('quality'))",
        QUALITY_PAGE,
        level(SAMPLES),
    ),
    Row(
        "Ön yüz QualityPage.tsx TABS onay (APPROVAL_ROLES)",
        MANAGEMENT,
        level(CONDITIONAL),
        live=f"{CONFIG}:APPROVAL_ROLES",
    ),
    Row(
        "Ön yüz QualityPage.tsx ApprovalsTab onayla ve reddet düğmeleri (onay sekmesi, "
        "APPROVAL_ROLES)",
        MANAGEMENT,
        level(CONDITIONAL, APPROVE),
        live=f"{CONFIG}:APPROVAL_ROLES",
    ),
    Row(
        "Ön yüz QualityPage.tsx TABS spesifikasyonlar (roles [], sayfa koruması "
        "menuRoles('quality'))",
        QUALITY_PAGE,
        level(SPECS),
    ),
    Row(
        "Ön yüz QualityPage.tsx TABS testler (roles [], sayfa koruması menuRoles('quality'))",
        QUALITY_PAGE,
        level(SPECS),
    ),
    Row(
        "Ön yüz QualityPage.tsx SpecsTab yeni spesifikasyon düğmesi (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz QualityPage.tsx testConfig.writeRoles — test tanımı ekle, düzenle, pasife al, "
        "kod önerisi (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz SamplePage.tsx isLab → canEnter: karar ver düğmesi (LAB_ROLES)",
        LAB,
        level(SAMPLES, APPROVE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz SamplePage.tsx isLab: sonuç girme ve düzeltme, spesifikasyon atama, numune "
        "iptali (LAB_ROLES)",
        LAB,
        level(SAMPLES, CHANGE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz SamplePage.tsx şartlı kabulü onayla ve reddet düğmeleri (APPROVAL_ROLES)",
        MANAGEMENT,
        level(CONDITIONAL, APPROVE),
        live=f"{CONFIG}:APPROVAL_ROLES",
    ),
    Row(
        "Ön yüz SpecificationPage.tsx isLab → canEdit: sürümü onayla düğmesi (LAB_ROLES)",
        LAB,
        level(SPECS, APPROVE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz SpecificationPage.tsx isLab: yeni sürüm (kopya), değişiklik notu, satır ekle, "
        "düzenle, kaldır (LAB_ROLES)",
        LAB,
        level(SPECS, CHANGE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz LotQualitySection.tsx canOpen: numune aç düğmesi (LAB_ROLES)",
        LAB,
        level(SAMPLES, CHANGE),
        live=f"{CONFIG}:LAB_ROLES",
    ),
    Row(
        "Ön yüz LotQualitySection.tsx canRework: yeniden işleme emri düğmesi "
        "(production ORDER_ROLES)",
        ("planlama",),
        level(PRODUCTION_ORDERS, CHANGE),
        live="frontend:src/modules/production/config.ts:ORDER_ROLES",
    ),
    # --- kabuk: modülün menü, rota ve arama girişleri ---
    Row(
        "Ön yüz layout/menu.ts MENU quality.roles",
        QUALITY_PAGE,
        MODULE_VIEW,
    ),
    Row(
        "Ön yüz routes.tsx qualityPage: kalite/:tab? ve kalite/numuneler/:sampleId",
        QUALITY_PAGE,
        MODULE_VIEW,
    ),
    Row(
        "Ön yüz routes.tsx qualityPage: kalite/spesifikasyonlar/:specId (plan §5.9: "
        "Spesifikasyonlar: Görür)",
        QUALITY_PAGE,
        level(SPECS),
    ),
    Row(
        "Ön yüz pages/SearchPage.tsx samples kaynağı (menuRoles('quality'); hedef numune sayfası)",
        QUALITY_PAGE,
        MODULE_VIEW,
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
