"""Ana veriler: paket denkliği (docs/plan/kisi-yetkileri.md §3.1 ve §5.5, 3. parça).

Bugünkü her rol denetimi planın bölüm ve düzeyine eşlenir; admin dışındaki 8 rolün bütün
bileşimlerinde eski ve yeni karar aynıdır. Kartlar, birimler, yazıcılar, etiket ayarları ve firma
bilgileri bugün giriş yapan herkese açıktır (ortak okuma, kişiden kapatılamaz). Müşteri ve
tedarikçinin vergi, adres ve iletişim alanları açık okumadır (sade kart, §5.6). Lokasyon etiketi ve
yazıcı deneme baskısı kaydın okumasını izler (§4). GS1 ayarları kodlama sistematiğindedir: yalnız
admin (§4).
"""

import re

from apps.core import access
from apps.core.access import CHANGE, READ
from apps.core.coding.registry import code_type
from apps.core.tests.access_helpers import (
    ADMIN_ONLY,
    REPO_ROOT,
    SIGNED_IN,
    Need,
    Row,
    admin_only,
    any_of,
    assert_rows,
    level,
    read,
)
from apps.masterdata.access import CARDS, COMPANY, OPEN_RECORDS, REFERENCE

WRITE_ROLES = "apps.masterdata.api.views:MASTERDATA_WRITE_ROLES"
COMPANY_WRITE_ROLES = "apps.masterdata.services:COMPANY_WRITE_ROLES"
PLANLAMA = ("planlama",)
YONETIM = ("yonetim",)
# Sekmeler bugün sayfanın korumasını izler (routes.tsx: menuRoles('masterdata')).
PAGE = ("planlama", "yonetim")

# Kod önerisi (core CodeSuggestView) türün yazma rollerine açıktır; yazma rolü olmayan tür yalnız
# admine öneri verir (`write_roles or (ADMIN,)`).
CARD_CODE_TYPES = (
    "masterdata.material",
    "masterdata.materialcategory",
    "masterdata.warehouse",
    "masterdata.location",
    "masterdata.equipment",
    "masterdata.supplier",
    "masterdata.customer",
)
REFERENCE_CODE_TYPES = ("masterdata.printer", "masterdata.unitofmeasure")

# live= yalnız `export const` okur; bu sabitler dışa aktarılmaz, ayrı testte denetlenir.
ENTITIES = "src/modules/masterdata/entities.tsx"


def contact(name: str) -> Need:
    """İletişim alanlarını tam gören: Ana veriler'in açık kayıtları ya da alanları okuyan
    bölümlerden birinde Görür (müşteride sales, Satış siparişleri'ni ekler; §3.1)."""
    return any_of(level(OPEN_RECORDS, READ), *(level(item) for item in access.field_openers(name)))


ROWS: list[Row] = [
    # --- API okumaları (bugün IsAuthenticated) ---
    Row(
        "api.views.MasterDataViewSet okuma (list, retrieve, metadata): kategori, malzeme, birim "
        "dönüşümü, depo, lokasyon, ekipman, tedarikçi, müşteri",
        SIGNED_IN,
        read(CARDS),
    ),
    Row(
        "api.views.LocationViewSet.label ve print_label (lokasyon etiketi)",
        SIGNED_IN,
        read(CARDS),
    ),
    Row(
        "api.views.UnitOfMeasureViewSet ve PrinterViewSet okuma (list, retrieve, metadata)",
        SIGNED_IN,
        read(REFERENCE),
    ),
    Row("api.views.PrinterViewSet.test (deneme etiketi)", SIGNED_IN, read(REFERENCE)),
    Row("api.views.LabelSettingsView GET", SIGNED_IN, read(REFERENCE)),
    Row("api.views.CompanyProfileView GET", SIGNED_IN, read(COMPANY)),
    Row(
        "api.serializers.SupplierSerializer iletişim alanları ve SupplierViewSet aramasında "
        "vergi no ve yetkili kişi",
        SIGNED_IN,
        contact("masterdata.supplier.contact"),
    ),
    Row(
        "api.serializers.CustomerSerializer iletişim alanları ve CustomerViewSet aramasında "
        "vergi no ve yetkili kişi",
        SIGNED_IN,
        contact("masterdata.customer.contact"),
    ),
    # --- API ve servis yazmaları ---
    Row(
        "api.views.MASTERDATA_WRITE_ROLES (MasterDataViewSet yazma: create, update, "
        "partial_update, activate, deactivate)",
        PLANLAMA,
        level(CARDS, CHANGE),
        live=WRITE_ROLES,
    ),
    Row(
        "api.views.MASTERDATA_WRITE_ROLES (MaterialViewSet.case_gtin_suggestion)",
        PLANLAMA,
        level(CARDS, CHANGE),
        live=WRITE_ROLES,
    ),
    Row(
        "api.views.MASTERDATA_WRITE_ROLES (GtinSuggestionView)",
        PLANLAMA,
        level(CARDS, CHANGE),
        live=WRITE_ROLES,
    ),
    Row(
        "api.views.MASTERDATA_WRITE_ROLES (ImportView: Excel'den içe aktarma)",
        PLANLAMA,
        level(CARDS, CHANGE),
        live=WRITE_ROLES,
    ),
    Row(
        "api.views.MASTERDATA_WRITE_ROLES (ImportTemplateView: içe aktarma şablonu)",
        PLANLAMA,
        level(CARDS, CHANGE),
        live=WRITE_ROLES,
    ),
    Row(
        "api.views.UnitOfMeasureViewSet yazma (write_roles = (ADMIN,))",
        ADMIN_ONLY,
        level(REFERENCE, CHANGE),
    ),
    Row(
        "api.views.PrinterViewSet yazma (write_roles = (ADMIN,))",
        ADMIN_ONLY,
        level(REFERENCE, CHANGE),
    ),
    Row("api.views.LabelSettingsView PUT (HasRole(ADMIN))", ADMIN_ONLY, level(REFERENCE, CHANGE)),
    Row(
        "services.COMPANY_WRITE_ROLES (CompanyProfileView PUT)",
        YONETIM,
        level(COMPANY, CHANGE),
        live=COMPANY_WRITE_ROLES,
    ),
    Row(
        "services.COMPANY_WRITE_ROLES (update_company_profile)",
        YONETIM,
        level(COMPANY, CHANGE),
        live=COMPANY_WRITE_ROLES,
    ),
    Row("api.views.Gs1SettingsView GET, PATCH (HasRole(ADMIN))", ADMIN_ONLY, admin_only()),
    Row(
        "services.update_gs1_settings (user_has_role(actor, (ADMIN,)))",
        ADMIN_ONLY,
        admin_only(),
    ),
    # --- kod önerisi: apps.py register_master_code(write_roles=...) ---
    *(
        Row(f"apps.py {key} write_roles (kod önerisi)", PLANLAMA, level(CARDS, CHANGE))
        for key in CARD_CODE_TYPES
    ),
    *(
        Row(f"apps.py {key} yazma rolü yok (kod önerisi)", ADMIN_ONLY, level(REFERENCE, CHANGE))
        for key in REFERENCE_CODE_TYPES
    ),
    # --- ön yüz (menü ve sayfa koruması test_access_package_shell.py'dedir) ---
    Row(
        "frontend MasterDataPage.tsx TABS kart sekmeleri (malzemeler … birim-donusumleri)",
        PAGE,
        level(CARDS),
    ),
    Row(
        "frontend MasterDataPage.tsx TABS birimler, yazicilar, etiket-ayarlari",
        PAGE,
        level(REFERENCE),
    ),
    Row("frontend MasterDataPage.tsx TABS firma-bilgileri", PAGE, level(COMPANY)),
    Row(
        "frontend entities.tsx WRITE (writeRoles; CrudPage canWrite: yeni, düzenle, pasife al, "
        "içe aktar)",
        PLANLAMA,
        level(CARDS, CHANGE),
    ),
    Row(
        "frontend entities.tsx ADMIN_ONLY (writeRoles: birimler, yazıcılar)",
        ADMIN_ONLY,
        level(REFERENCE, CHANGE),
    ),
    Row(
        "frontend CompanyProfilePanel.tsx canEdit (hasAnyRole(user, ['yonetim']))",
        YONETIM,
        level(COMPANY, CHANGE),
    ),
    Row(
        "frontend LabelTools.tsx LabelSettingsPanel canEdit (hasAnyRole(user, ['admin']); GS1 "
        "bağlantısı dahil)",
        ADMIN_ONLY,
        level(REFERENCE, CHANGE),
    ),
]


def test_package_equivalence() -> None:
    assert_rows(ROWS)


def _private_frontend_roles(path: str, name: str) -> tuple[str, ...]:
    """Ön yüz dosyasındaki dışa aktarılmamış `const NAME ... = [...]` rol dizisi."""
    text = (REPO_ROOT / "frontend" / path).read_text(encoding="utf-8")
    match = re.search(rf"\bconst\s+{re.escape(name)}\b[^=]*=\s*\[(?P<body>[^\]]*)\]", text)
    assert match is not None, f"{path}: {name} dizisi bulunamadı."
    return tuple(re.findall(r"[\"']([a-z_]+)[\"']", match.group("body")))


def test_unexported_roles_match_today() -> None:
    """live= okuyamayan rol listeleri: kod türlerinin yazma rolleri (kayıttan) ve entities.tsx
    sabitleri satırlardaki rollerle aynıdır."""
    for key in CARD_CODE_TYPES:
        item = code_type(key)
        assert item is not None, key
        assert item.write_roles == PLANLAMA, key
    for key in REFERENCE_CODE_TYPES:
        item = code_type(key)
        assert item is not None, key
        assert item.write_roles == (), key
    assert _private_frontend_roles(ENTITIES, "WRITE") == PLANLAMA
    assert _private_frontend_roles(ENTITIES, "ADMIN_ONLY") == ("admin",)
