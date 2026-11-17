"""Personel: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.14).

Bütün bölümler yalnız yönetim rolündekilere verilebilir (KVKK).
"""

from django.db.models import Q

from apps.core.access import (
    ALL,
    APPROVE,
    CHANGE,
    VIEW,
    grant,
    register_audit_model,
    register_audit_rows,
    register_module,
    register_section,
)
from apps.core.roles import YONETIM

register_module("personnel", "Personel", order=140)

CARDS = register_section(
    "personnel.cards",
    "Personel kartları ve özlük belgeleri",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Personel kartları, özlük bilgileri ve belgeleri.",
        CHANGE: "Kart açar ve düzenler, belge ekler.",
    },
    restricted_to_role=YONETIM,
)
ATTENDANCE = register_section(
    "personnel.attendance",
    "Puantaj ve tatil takvimi",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Puantaj ve tatil takvimi.",
        CHANGE: "Gün ve aralık girişi, tatiller.",
        APPROVE: "Ayı onaylar ve yeniden açar.",
    },
    restricted_to_role=YONETIM,
)
WAGES = register_section(
    "personnel.wages",
    "Ücretler",
    levels=(VIEW, CHANGE),
    help={VIEW: "Ücret geçmişi.", CHANGE: "Ücret girer ve düzeltir."},
    restricted_to_role=YONETIM,
)
PAYROLL = register_section(
    "personnel.payroll",
    "Bordro",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Ön bordro, pusulalar, PDF ve Excel.",
        CHANGE: "Kalemler, devirler, dış bordro tutarları; yeniden açılan ayda karta geçirme.",
        APPROVE: "Onaylar, yeniden açar, onaylı bordronun ödeme tarihini düzeltir.",
    },
    requires={ALL: [(WAGES, VIEW)]},
    restricted_to_role=YONETIM,
)
SETTINGS = register_section(
    "personnel.settings",
    "Personel ayarları",
    levels=(VIEW, CHANGE),
    help={
        VIEW: "Bordro parametreleri (asgari ücret, SGK oranları, vergi dilimleri) ve hafta tatili "
        "günleri.",
        CHANGE: "Bordro parametrelerini ve hafta tatili günlerini değiştirir.",
    },
    restricted_to_role=YONETIM,
)

grant(YONETIM, CARDS, VIEW, CHANGE)
grant(YONETIM, ATTENDANCE, VIEW, CHANGE, APPROVE)
grant(YONETIM, WAGES, VIEW, CHANGE)
grant(YONETIM, PAYROLL, VIEW, CHANGE, APPROVE)
grant(YONETIM, SETTINGS, VIEW, CHANGE)

# Denetim günlüğü (plan §5.6, KVKK): personel kayıtları ilgili personel bölümünü ister. Kartın
# geçmişindeki bordro özetleri (ek ödeme, kesinti, devir, pusula; kart ekranında da gizli) ve
# bordrosu açılmamış ayın bordro erişim kayıtları (içerik türü yok) Bordro: Görür ister.
_SECTIONS_OF_MODELS = {
    CARDS: ("employee", "employeedocument"),
    ATTENDANCE: ("attendanceentry", "attendancemonth", "publicholiday"),
    WAGES: ("employeewage",),
    PAYROLL: (
        "externalpayrollfigure",
        "payrollapproval",
        "payrollitem",
        "payrollopeningbalance",
        "payrollrun",
        "payrollslip",
    ),
    SETTINGS: ("attendancesettings", "payrollparameterset"),
}
for _section, _models in _SECTIONS_OF_MODELS.items():
    for _model in _models:
        register_audit_model(f"personnel.{_model}", requires=[_section])


def _payroll_card_notes() -> Q:
    from apps.personnel.selectors import payroll_card_notes

    return payroll_card_notes()


register_audit_model("personnel.employee", requires=[PAYROLL], rows=_payroll_card_notes)
# `services.log_payroll_access`, ayın bordrosu yokken (notun başı aynıdır).
PAYROLL_ACCESS_NOTE = "Bordro çıktısı açıldı:"
register_audit_rows(
    "personnel.payroll_access",
    Q(action="custom", note__startswith=PAYROLL_ACCESS_NOTE),
    requires=[PAYROLL],
)
