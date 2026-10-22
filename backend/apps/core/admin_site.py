"""Projenin yönetim paneli sitesi: Türkçe başlıklar, giriş denemesi sınırı ve 2FA."""

from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.http import HttpRequest, HttpResponse

from apps.core import ratelimit, security
from apps.core.models import User


class OtpAdminAuthenticationForm(AdminAuthenticationForm):
    """Yönetim paneli girişi: doğrulayıcı uygulaması kurulu kullanıcıdan kod ister; rolü 2FA
    gerektirip kurmamış kullanıcıyı önce uygulamadaki Güvenlik sayfasına yönlendirir."""

    otp_code = forms.CharField(
        label="Doğrulama kodu",
        required=False,
        max_length=16,
        help_text="İki aşamalı doğrulama açıksa telefonunuzdaki 6 haneli kod ya da kurtarma kodu.",
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
    )

    def confirm_login_allowed(self, user: Any) -> None:
        super().confirm_login_allowed(user)
        if not isinstance(user, User):
            return
        if security.otp_enabled(user):
            code = self.cleaned_data.get("otp_code") or ""
            if not security.verify_second_factor(user, code):
                security.report_failed_second_factor(self.request, user.get_username())
                raise forms.ValidationError(
                    "Doğrulama kodu eksik ya da hatalı.", code="invalid_otp"
                )
        elif security.otp_required_for(user):
            raise forms.ValidationError(
                "Rolünüz için iki aşamalı doğrulama zorunlu. Önce uygulamaya girip Güvenlik "
                "sayfasından kurun.",
                code="otp_setup_required",
            )


class ERPAdminSite(admin.AdminSite):
    site_header = "Inncos ERP Yönetim"
    site_title = "Inncos ERP"
    index_title = "Yönetim paneli"
    login_form = OtpAdminAuthenticationForm

    def has_permission(self, request: HttpRequest) -> bool:
        user = request.user
        if isinstance(user, User) and security.otp_setup_required(user):
            return False
        return super().has_permission(request)

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
