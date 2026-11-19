"""Portal uç noktaları (docs/plan/musteri-siparis-takibi.md §4).

- `accounts/`: portal hesaplarının yönetimi, yalnız sistem yöneticisi (CUMHUR, 2026-11-19).
- `me/`: portal kullanıcısının kendi hesabı. Çalışan açamaz.
"""

from typing import Any

import django_filters
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import User
from apps.core.permissions import AccessPermission, AdminOnly
from apps.portal import selectors, services
from apps.portal.api import serializers as s
from apps.portal.models import PortalAccount


def _actor(request: Request) -> User:
    return request.user  # type: ignore[return-value]


class PortalUserOnly(AccessPermission):
    """Yalnız portal kullanıcısı (müşteri ya da tedarikçi yetkilisi); çalışan açamaz."""

    message = "Bu sayfa yalnız portal hesabına açık."

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "is_portal", False))


class PortalAccountFilter(django_filters.FilterSet):
    kind = django_filters.ChoiceFilter(
        choices=[("customer", "Müşteri"), ("supplier", "Tedarikçi")],
        method="filter_kind",
    )
    is_active = django_filters.BooleanFilter(field_name="user__is_active")

    class Meta:
        model = PortalAccount
        fields = ["customer", "supplier"]

    def filter_kind(
        self, queryset: QuerySet[PortalAccount], name: str, value: str
    ) -> QuerySet[PortalAccount]:
        if value == "customer":
            return queryset.filter(customer__isnull=False)
        if value == "supplier":
            return queryset.filter(supplier__isnull=False)
        return queryset


class PortalAccountViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Portal hesapları (yalnız admin): liste, yeni hesap (geçici şifreyle), şifre sıfırlama,
    kilit açma, pasife alma ve etkinleştirme. Hesap silinmez, bağlı firma değişmez."""

    serializer_class = s.PortalAccountSerializer
    permission_classes = [AdminOnly]
    filterset_class = PortalAccountFilter
    search_fields = [
        "user__username",
        "user__full_name",
        "user__email",
        "customer__code",
        "customer__name",
        "supplier__code",
        "supplier__name",
    ]
    ordering_fields = ["user__username", "created_at", "user__last_login"]

    def get_queryset(self) -> QuerySet[PortalAccount]:
        return selectors.accounts()

    def _fresh(self, account: PortalAccount) -> Any:
        return s.PortalAccountSerializer(self.get_queryset().get(pk=account.pk)).data

    def _issued(self, account: PortalAccount, password: str, status_code: int) -> Response:
        response = Response(
            {"account": self._fresh(account), "temporary_password": password},
            status=status_code,
        )
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(
        request=s.PortalAccountCreateSerializer,
        responses={201: s.IssuedAccountPasswordSerializer},
    )
    def create(self, request: Request) -> Response:
        body = s.PortalAccountCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        account, password = services.create_account(_actor(request), **body.validated_data)
        return self._issued(account, password, status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.IssuedAccountPasswordSerializer)
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request: Request, pk: str | None = None) -> Response:
        account = self.get_object()
        password = services.reset_password(_actor(request), account)
        return self._issued(account, password, status.HTTP_200_OK)

    @extend_schema(request=None, responses=s.PortalAccountSerializer)
    @action(detail=True, methods=["post"])
    def unlock(self, request: Request, pk: str | None = None) -> Response:
        account = self.get_object()
        services.unlock(_actor(request), account)
        return Response(self._fresh(account))

    @extend_schema(request=None, responses=s.PortalAccountSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        account = self.get_object()
        services.set_active(_actor(request), account, False)
        return Response(self._fresh(account))

    @extend_schema(request=None, responses=s.PortalAccountSerializer)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        account = self.get_object()
        services.set_active(_actor(request), account, True)
        return Response(self._fresh(account))


class PortalMeView(APIView):
    """Portal kullanıcısının hesabı: tür ve bağlı firma."""

    permission_classes = [PortalUserOnly]

    @extend_schema(responses=s.PortalMeSerializer)
    def get(self, request: Request) -> Response:
        account = selectors.account_of(_actor(request))
        if account is None:
            return Response(
                {
                    "code": "portal_account_missing",
                    "detail": "Portal hesabı bulunamadı.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        firm = account.firm
        data = {"kind": account.kind, "firm_code": firm.code, "firm_name": firm.name}
        return Response(s.PortalMeSerializer(data).data)
