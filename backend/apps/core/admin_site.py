"""Projenin yönetim paneli sitesi: Türkçe başlıklar ve giriş denemesi sınırı."""

from typing import Any

from django.contrib import admin
from django.contrib.admin.apps import AdminConfig
from django.http import HttpRequest, HttpResponse

from apps.core import ratelimit


class ERPAdminSite(admin.AdminSite):
    site_header = "Deterjan ERP Yönetim"
    site_title = "Deterjan ERP"
    index_title = "Yönetim paneli"

    def login(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> Any:
        """Yönetim paneli girişi de API girişiyle aynı IP başına sınırı paylaşır."""
        if request.method == "POST" and ratelimit.login_rate_exceeded(request):
            response = HttpResponse(
                "Çok fazla giriş denemesi. Lütfen biraz bekleyip tekrar deneyin.",
                status=429,
                content_type="text/plain; charset=utf-8",
            )
            response["Retry-After"] = str(ratelimit.login_rate_period())
            return response
        return super().login(request, extra_context)


class ERPAdminConfig(AdminConfig):
    """`django.contrib.admin` yerine kullanılır: varsayılan yönetim sitesi `ERPAdminSite`."""

    default_site = "apps.core.admin_site.ERPAdminSite"
