from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.db.models import Model
from django.forms import ModelForm
from django.http import HttpRequest

from apps.core.audit import log_change
from apps.core.models import AuditLog, DocumentSequence, User
from apps.core.roles import ROLE_LABELS
from apps.core.services import save_with_audit

# Roller (Group) seed_roles ile oluşturulur ve sabittir; panelden eklenemez, yeniden
# adlandırılamaz, silinemez (adı yetkinin kendisidir). Rol ataması kullanıcı ekranından yapılır.
admin.site.unregister(Group)


class AuditedAdminMixin:
    """Yönetim panelinden yapılan kayıtları da denetim günlüğüne yazar; silmeyi kapatır."""

    def save_model(self, request: HttpRequest, obj: Model, form: ModelForm, change: bool) -> None:
        save_with_audit(obj, request.user, note="Yönetim paneli")  # type: ignore[arg-type]

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False


@admin.register(User)
class UserAdmin(AuditedAdminMixin, DjangoUserAdmin):
    list_display = ("username", "full_name", "email", "role_list", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "is_superuser", "groups")
    search_fields = ("username", "full_name", "email")
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Kişisel bilgiler", {"fields": ("full_name", "email", "phone")}),
        (
            "Roller ve yetkiler",
            {
                "fields": (
                    "is_active",
                    "must_change_password",
                    "is_staff",
                    "is_superuser",
                    "groups",
                )
            },
        ),
        ("Önemli tarihler", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "full_name", "email", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("last_login", "date_joined")

    @admin.display(description="Roller")
    def role_list(self, obj: User) -> str:
        return ", ".join(obj.roles)

    def save_related(self, request: HttpRequest, form: Any, formsets: Any, change: bool) -> None:
        user: User = form.instance
        before = sorted(user.groups.values_list("name", flat=True)) if change else []
        super().save_related(request, form, formsets, change)
        after = sorted(user.groups.values_list("name", flat=True))
        user.refresh_roles()
        if before != after:
            log_change(
                request.user,  # type: ignore[arg-type]
                user,
                AuditLog.Action.UPDATE,
                {"roles": [before, after]},
                "Yönetim paneli",
            )


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False


@admin.register(Group)
class RoleAdmin(ReadOnlyAdmin):
    list_display = ("name", "label", "member_count")
    fields = ("name",)

    @admin.display(description="Rol adı")
    def label(self, obj: Group) -> str:
        return ROLE_LABELS.get(obj.name, "")

    @admin.display(description="Kullanıcı sayısı")
    def member_count(self, obj: Group) -> int:
        return obj.user_set.count()


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("timestamp", "actor", "action", "content_type", "object_repr", "ip_address")
    list_filter = ("action", "content_type")
    search_fields = ("object_repr", "note", "actor__username")
    date_hierarchy = "timestamp"
    list_select_related = ("actor", "content_type")


@admin.register(DocumentSequence)
class DocumentSequenceAdmin(ReadOnlyAdmin):
    list_display = ("prefix", "year", "last_number")
    list_filter = ("year",)
