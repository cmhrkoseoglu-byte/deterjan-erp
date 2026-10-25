"""Yönetim paneli: personel kartları yalnızca görüntülenir; değişiklik servislerle yapılır."""

from django.contrib import admin

from apps.core.admin import ReadOnlyAdmin
from apps.personnel.models import Employee


@admin.register(Employee)
class EmployeeAdmin(ReadOnlyAdmin):
    list_display = ("full_name", "employee_no", "department", "title", "hire_date", "is_active")
    list_filter = ("is_active", "department")
    search_fields = ("full_name", "employee_no", "department", "title")
    list_select_related = ("user",)
