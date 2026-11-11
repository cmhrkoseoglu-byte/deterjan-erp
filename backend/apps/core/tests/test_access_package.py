"""Çekirdek: paket denkliği (docs/plan/kisi-yetkileri.md §3.17, §4 ve §5.5, 3. parça).

Kullanıcılar, kodlama sistematiği (biçimler, kod göçü, çıktı doküman kodları, kayıt kodunu
değiştirme), saha tableti ve kaldırılmış eki açma yalnız admindir (§4): bugünkü `HasRole(ADMIN)` ve
`is_admin` denetimleri hiçbir role verilemeyen yetkiye eşlenir. Denetim günlüğü yönetimdedir
(KVKK). Sistem menüsü ve rotası ön yüz kabuğunun satırlarındadır (`test_access_package_shell.py`).

Satır değildir: giriş yapan herkese açık hesap uçları (me, güvenlik, şifre, iki aşamalı
doğrulama), ortak listeler (`standards`), katalog ve ek uçlarının sınıf izni (kayıt kuralı
modüllerin kaydındadır). İki aşamalı doğrulama ve son admin kuralları rol bazlı kalır.
"""

from apps.core.access import AUDIT_LOG
from apps.core.tests.access_helpers import ADMIN_ONLY, Row, admin_only, assert_rows, level

# Kodlama sistematiği uç noktaları: hepsi `HasRole(ADMIN)` (api/coding.py).
CODING_VIEWS = (
    "CodeTypeListView GET",
    "CodeTypeDetailView GET, PUT",
    "CodeTypePreviewView POST",
    "CodeSchemeRevisionListView GET",
    "AllRevisionsListView GET",
    "RecodePreviewView GET",
    "RecodeApplyView POST",
    "CodeMigrationRunListView GET",
    "RevertPreviewView GET",
    "RevertView POST",
    "OutputDocumentListView GET",
    "OutputDocumentDetailView GET, PATCH",
    "OutputRevisionCreateView POST",
)
# Servis denetimi `coding.services.require_admin`.
CODING_SERVICES = (
    "coding.services.update_scheme",
    "coding.migration.apply_recode",
    "coding.migration.revert_recode",
    "coding.outputs.update_output",
    "coding.outputs.add_revision",
)

ROWS: list[Row] = [
    Row(
        "api.views.AuditLogViewSet list, retrieve (HasRole(ADMIN, YONETIM))",
        ("yonetim",),
        level(AUDIT_LOG),
    ),
    Row("api.views.UserViewSet bütün eylemler (HasRole(ADMIN))", ADMIN_ONLY, admin_only()),
    Row("api.views.FieldDeviceView POST (HasRole(ADMIN))", ADMIN_ONLY, admin_only()),
    # Ekler: kaldırılmış eki yalnız admin açar; eki yükleyen ya da admin kaldırır (satır kuralı
    # sürer, §4); türün `can_add` kuralını admin atlar.
    Row(
        "api.views.AttachmentViewSet.download (kaldırılmış ek: user.is_admin)",
        ADMIN_ONLY,
        admin_only(),
    ),
    Row(
        "services.remove_attachment (actor.is_admin ya da yükleyen)",
        ADMIN_ONLY,
        admin_only(),
    ),
    Row(
        "api.serializers.AttachmentSerializer.get_can_remove (user.is_admin ya da yükleyen)",
        ADMIN_ONLY,
        admin_only(),
    ),
    Row(
        "attachments.can_add_attachment (user.is_admin türün can_add kuralını atlar)",
        ADMIN_ONLY,
        admin_only(),
    ),
    *(
        Row(f"api.coding.{name} (HasRole(ADMIN))", ADMIN_ONLY, admin_only())
        for name in CODING_VIEWS
    ),
    Row(
        "api.coding.CodeSuggestView: yazma rolü olmayan tür (write_roles or (ADMIN,))",
        ADMIN_ONLY,
        admin_only(),
    ),
    *(Row(f"{name} (require_admin)", ADMIN_ONLY, admin_only()) for name in CODING_SERVICES),
    Row(
        "coding.services.can_change_code, ensure_can_change_code (kayıt kodunu değiştirme; "
        "masterdata.services.update_record)",
        ADMIN_ONLY,
        admin_only(),
    ),
    # --- ön yüz (kayıt formu: kod alanı kilidi, core kodlama kuralının eşi) ---
    Row(
        "frontend modules/common/RecordFormModal.tsx codeLocked (isAdmin)",
        ADMIN_ONLY,
        admin_only(),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
