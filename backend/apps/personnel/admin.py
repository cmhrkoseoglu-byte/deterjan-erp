"""Yönetim paneli: personel kartları yalnızca görüntülenir; değişiklik servislerle yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.personnel.models import (
    AttendanceEntry,
    AttendanceMonth,
    Employee,
    EmployeeDocument,
    PublicHoliday,
)


@admin.register(Employee)
class EmployeeAdmin(ReadOnlyAdmin):
    list_display = ("full_name", "employee_no", "department", "title", "hire_date", "is_active")
    list_filter = ("is_active", "department")
    search_fields = ("full_name", "employee_no", "department", "title")
    list_select_related = ("user",)


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(ReadOnlyAdmin):
    list_display = ("employee", "kind", "original_name", "period", "valid_from", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("employee__full_name", "original_name")
    list_select_related = ("employee",)


@admin.register(AttendanceMonth)
class AttendanceMonthAdmin(ReadOnlyAdmin):
    list_display = ("number", "year", "month", "status", "approved_at")
    list_filter = ("status", "year")


@admin.register(AttendanceEntry)
class AttendanceEntryAdmin(ReadOnlyAdmin):
    list_display = ("date", "employee", "status", "overtime_hours")
    list_filter = ("status",)
    search_fields = ("employee__full_name",)
    list_select_related = ("employee",)


@admin.register(PublicHoliday)
class PublicHolidayAdmin(ReadOnlyAdmin):
    list_display = ("date", "name", "half_day", "is_active")
    list_filter = ("is_active",)
