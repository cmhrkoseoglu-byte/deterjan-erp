"""Personel API'si: yalnızca admin ve yönetim (kişisel veri, docs/KVKK.md). Silme yoktur; ayrılış
`terminate`, yeniden işe başlama `reinstate` ile kaydedilir."""

from typing import Any

import django_filters
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import User
from apps.core.permissions import HasRole
from apps.personnel import selectors, services
from apps.personnel.api import serializers as s
from apps.personnel.models import Employee


def _user(request: Request) -> Any:
    return request.user


class EmployeeFilter(django_filters.FilterSet):
    department = django_filters.CharFilter(field_name="department", label="Birim")
    is_active = django_filters.BooleanFilter(label="Çalışıyor (ayrılanlar için false)")

    class Meta:
        model = Employee
        fields = ["department", "is_active"]


class EmployeeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Personel kartları: liste, kart, yeni kart, düzenleme, ayrılış, yeniden başlama, geçmiş."""

    serializer_class = s.EmployeeSerializer
    filterset_class = EmployeeFilter
    search_fields = ["full_name", "employee_no", "department", "title", "phone"]
    ordering_fields = ["full_name", "employee_no", "department", "hire_date"]
    ordering = ["full_name", "id"]
    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]
    queryset = Employee.objects.select_related("user")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Personel kartı açar."""
        body = s.EmployeeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        employee = services.create_employee(_user(request), body.validated_data)
        return Response(s.EmployeeSerializer(employee).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Kartı günceller (yalnızca gönderilen alanlar)."""
        instance = self.get_object()
        body = s.EmployeeSerializer(instance, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        employee = services.update_employee(_user(request), instance, body.validated_data)
        return Response(s.EmployeeSerializer(employee).data)

    @extend_schema(request=s.TerminateSerializer, responses=s.EmployeeSerializer)
    @action(detail=True, methods=["post"])
    def terminate(self, request: Request, pk: str | None = None) -> Response:
        """İşten ayrılışı kaydeder: kart pasife alınır, çıkış tarihi yazılır."""
        body = s.TerminateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        employee = services.terminate_employee(
            _user(request),
            self.get_object(),
            body.validated_data["termination_date"],
            note=body.validated_data["note"],
        )
        return Response(s.EmployeeSerializer(employee).data)

    @extend_schema(request=None, responses=s.EmployeeSerializer)
    @action(detail=True, methods=["post"])
    def reinstate(self, request: Request, pk: str | None = None) -> Response:
        """Ayrılan personeli yeniden çalışır yapar."""
        employee = services.reinstate_employee(_user(request), self.get_object())
        return Response(s.EmployeeSerializer(employee).data)

    @extend_schema(responses=s.EmployeeHistorySerializer(many=True))
    @action(detail=True, methods=["get"])
    def history(self, request: Request, pk: str | None = None) -> Response:
        """Kartın değişiklik geçmişi (en yenisi önce)."""
        entries = selectors.employee_history(self.get_object())[:200]
        return Response(s.EmployeeHistorySerializer(entries, many=True).data)


class DepartmentListView(APIView):
    """Kayıtlı birimler (birim süzgeci ve yeni kartta öneri için)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(responses=serializers.ListSerializer(child=serializers.CharField()))
    def get(self, request: Request) -> Response:
        return Response(selectors.departments())


class LinkableUserListView(APIView):
    """Karta bağlanabilecek sistem kullanıcıları (`?employee=` düzenlenen kart)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(
        parameters=[OpenApiParameter("employee", int, required=False)],
        responses=s.LinkedUserSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        employee = None
        employee_id = request.query_params.get("employee", "")
        if employee_id.isdigit():
            employee = Employee.objects.filter(pk=int(employee_id)).first()
        users: QuerySet[User] = selectors.linkable_users(employee)
        return Response(s.LinkedUserSerializer(users, many=True).data)
