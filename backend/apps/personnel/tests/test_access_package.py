"""Personel: paket denkliği (docs/plan/kisi-yetkileri.md §3.14 ve §5.5, 3. parça).

Personel uç noktaları ve servisleri bugün `PERSONNEL_ROLES` (yönetim) ister; ön yüzde menü ve sayfa
korumaları satır içi rol dizisidir. Her denetim planın bölüm ve düzeyine eşlenir; kişiye özel ayar
yokken iki taraf 256 rol bileşiminin hepsinde aynı kararı vermelidir. Bölümlerin hepsi yalnız
yönetim rolünde geçerlidir (KVKK).
"""

from apps.core.access import APPROVE, CHANGE, VIEW
from apps.core.tests.access_helpers import Need, Row, any_of, assert_rows, level, read
from apps.personnel.access import ATTENDANCE, CARDS, PAYROLL, SETTINGS, WAGES

YONETIM = ("yonetim",)
ROLES = "apps.personnel.services:PERSONNEL_ROLES"

# Modülün Görür'ü olan bölümlerinden biri: menü (plan §2).
ANY_SECTION = any_of(*(level(item, VIEW) for item in (CARDS, ATTENDANCE, WAGES, PAYROLL, SETTINGS)))


def api(source: str, need: Need) -> Row:
    """api/views.py `permission_classes = [HasRole(*services.PERSONNEL_ROLES)]`."""
    return Row(f"api/views.py {source}", YONETIM, need, live=ROLES)


def service(name: str, need: Need) -> Row:
    """services.py `_require_role(actor)`: `user_has_role(actor, PERSONNEL_ROLES)`."""
    return Row(f"services.{name}", YONETIM, need, live=ROLES)


API_ROWS = [
    # Kartlar ve özlük belgeleri
    api("EmployeeViewSet GET employees/, {pk}/, {pk}/history/", level(CARDS, VIEW)),
    api(
        "EmployeeViewSet POST employees/, PATCH {pk}/, POST {pk}/terminate/, {pk}/reinstate/",
        level(CARDS, CHANGE),
    ),
    api("EmployeeDocumentViewSet GET documents/, {pk}/, {pk}/download/", level(CARDS, VIEW)),
    api("EmployeeDocumentViewSet POST documents/, {pk}/remove/", level(CARDS, CHANGE)),
    # Birimler kart listesinin, kart formunun ve puantajın süzgecidir.
    api("DepartmentListView GET departments/", read(CARDS, ATTENDANCE)),
    # Bağlanabilecek kullanıcılar yalnız kart formunda seçilir (seçim listesi, plan §5.4 örneği).
    api("LinkableUserListView GET linkable-users/", level(CARDS, CHANGE)),
    # Puantaj ve tatil takvimi
    api("AttendanceGridView GET attendance/{year}/{month}/", level(ATTENDANCE, VIEW)),
    api("AttendanceExportView GET attendance/{year}/{month}/export/", level(ATTENDANCE, VIEW)),
    api("AttendanceDayView POST attendance/days/", level(ATTENDANCE, CHANGE)),
    api("AttendanceRangeView POST attendance/ranges/", level(ATTENDANCE, CHANGE)),
    api(
        "AttendanceApproveView POST attendance/{year}/{month}/approve/", level(ATTENDANCE, APPROVE)
    ),
    api("AttendanceReopenView POST attendance/{year}/{month}/reopen/", level(ATTENDANCE, APPROVE)),
    api("PublicHolidayViewSet GET attendance/holidays/, {pk}/", level(ATTENDANCE, VIEW)),
    api(
        "PublicHolidayViewSet POST attendance/holidays/, PATCH {pk}/, POST {pk}/remove/, fixed/",
        level(ATTENDANCE, CHANGE),
    ),
    # Hafta tatili günleri Personel ayarları'ndadır.
    api("AttendanceSettingsView GET attendance/settings/", level(SETTINGS, VIEW)),
    api("AttendanceSettingsView PATCH attendance/settings/", level(SETTINGS, CHANGE)),
    # Ücretler
    api("EmployeeWageViewSet GET wages/, {pk}/, summary/", level(WAGES, VIEW)),
    api("EmployeeWageViewSet POST wages/, {pk}/remove/", level(WAGES, CHANGE)),
    # Bordro
    api("PayrollMonthView GET payroll/{year}/{month}/", level(PAYROLL, VIEW)),
    api("PayrollPayslipsPdfView GET payroll/{year}/{month}/payslips.pdf", level(PAYROLL, VIEW)),
    api(
        "PayrollEmployerCostPdfView GET payroll/{year}/{month}/employer-cost.pdf",
        level(PAYROLL, VIEW),
    ),
    api("PayrollRegisterPdfView GET payroll/{year}/{month}/register.pdf", level(PAYROLL, VIEW)),
    api("PayrollExcelView GET payroll/{year}/{month}/xlsx/", level(PAYROLL, VIEW)),
    api("PayrollApproveView POST payroll/{year}/{month}/approve/", level(PAYROLL, APPROVE)),
    api("PayrollReopenView POST payroll/{year}/{month}/reopen/", level(PAYROLL, APPROVE)),
    api(
        "PayrollPaymentDateView POST payroll/{year}/{month}/payment-date/",
        level(PAYROLL, APPROVE),
    ),
    api("PayrollFollowCardView POST payroll/{year}/{month}/follow-card/", level(PAYROLL, CHANGE)),
    api("ExternalPayrollView POST payroll/{year}/{month}/external/", level(PAYROLL, CHANGE)),
    api("ExternalPayrollRemoveView POST payroll/external/{pk}/remove/", level(PAYROLL, CHANGE)),
    api("PayrollItemViewSet GET payroll/items/, {pk}/", level(PAYROLL, VIEW)),
    api(
        "PayrollItemViewSet POST payroll/items/, PATCH {pk}/, POST {pk}/remove/, batch/",
        level(PAYROLL, CHANGE),
    ),
    api("PayrollOpeningViewSet GET payroll/openings/, {pk}/", level(PAYROLL, VIEW)),
    api(
        "PayrollOpeningViewSet POST payroll/openings/, {pk}/remove/, batch/",
        level(PAYROLL, CHANGE),
    ),
    # Bordro parametreleri Personel ayarları'ndadır.
    api(
        "PayrollParameterSetViewSet GET payroll/parameters/, {pk}/, defaults/",
        level(SETTINGS, VIEW),
    ),
    api(
        "PayrollParameterSetViewSet POST payroll/parameters/, PATCH {pk}/, POST {pk}/remove/",
        level(SETTINGS, CHANGE),
    ),
]

SERVICE_ROWS = [
    *(
        service(name, level(CARDS, CHANGE))
        for name in (
            "create_employee",
            "update_employee",
            "terminate_employee",
            "reinstate_employee",
            "add_document",
            "remove_document",
        )
    ),
    service("record_document_access", level(CARDS, VIEW)),
    *(
        service(name, level(ATTENDANCE, CHANGE))
        for name in (
            "add_holiday",
            "update_holiday",
            "remove_holiday",
            "add_fixed_holidays",
            "set_attendance_day",
            "set_attendance_range",
        )
    ),
    service("approve_attendance_month", level(ATTENDANCE, APPROVE)),
    service("reopen_attendance_month", level(ATTENDANCE, APPROVE)),
    service("add_wage", level(WAGES, CHANGE)),
    service("remove_wage", level(WAGES, CHANGE)),
    # Bordro çıktısı açılışı (PDF, Excel); maliyetten çağrılışı costing testindedir.
    service("record_payroll_access", level(PAYROLL, VIEW)),
    *(
        service(name, level(PAYROLL, CHANGE))
        for name in (
            "set_external_payroll",
            "remove_external_payroll",
            "set_opening_balance",
            "set_opening_balances",
            "remove_opening_balance",
            "add_payroll_item",
            "add_payroll_items",
            "update_payroll_item",
            "remove_payroll_item",
            "set_payroll_follow_card",
        )
    ),
    *(
        service(name, level(PAYROLL, APPROVE))
        for name in ("approve_payroll_month", "reopen_payroll_month", "set_payroll_payment_date")
    ),
    *(
        service(name, level(SETTINGS, CHANGE))
        for name in (
            "update_attendance_settings",
            "create_parameter_set",
            "update_parameter_set",
            "remove_parameter_set",
        )
    ),
]

FRONTEND_ROWS = [
    Row("frontend/src/layout/menu.ts MENU personnel roles", YONETIM, ANY_SECTION),
    Row("frontend/src/routes.tsx personnelPage personel (PersonnelPage)", YONETIM, level(CARDS)),
    Row(
        "frontend/src/routes.tsx personnelPage personel/:employeeId (EmployeePage)",
        YONETIM,
        level(CARDS),
    ),
    Row(
        "frontend/src/routes.tsx personnelPage personel/puantaj (AttendancePage)",
        YONETIM,
        level(ATTENDANCE),
    ),
    Row(
        "frontend/src/routes.tsx personnelPage personel/tatiller (HolidaysPage)",
        YONETIM,
        level(ATTENDANCE),
    ),
    Row(
        "frontend/src/routes.tsx personnelPage personel/ucretler (WagesPage)",
        YONETIM,
        level(WAGES),
    ),
    Row(
        "frontend/src/routes.tsx personnelPage personel/bordro (PayrollPage)",
        YONETIM,
        level(PAYROLL),
    ),
]

ROWS = [*API_ROWS, *SERVICE_ROWS, *FRONTEND_ROWS]


def test_package_equivalence() -> None:
    assert_rows(ROWS)
