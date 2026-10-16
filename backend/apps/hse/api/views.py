from datetime import date, timedelta
from typing import Any

import django_filters
from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole, user_has_role
from apps.hse import exports, selectors, services
from apps.hse.api import serializers as s
from apps.hse.models import (
    HazardClass,
    HazardStatement,
    Incident,
    MaterialHazard,
    SafetyDataSheet,
    StorageLimit,
    WasteContractor,
    WasteRecord,
)
from apps.inventory.api.serializers import CancelSerializer
from apps.masterdata.models import Location, Material

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(request: Request) -> Any:
    return request.user


def _date_param(request: Request, name: str) -> date | None:
    value = request.query_params.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: ["Geçerli bir tarih girin (YYYY-AA-GG)."]}) from exc


def _object_param(request: Request, name: str, model: Any) -> Any:
    value = request.query_params.get(name)
    if not value:
        return None
    if not value.isdigit():
        raise ValidationError({name: ["Geçerli bir kimlik girin."]})
    obj = model.objects.filter(pk=value).first()
    if obj is None:
        raise ValidationError({name: ["Kayıt bulunamadı."]})
    return obj


def _period(request: Request) -> tuple[date, date]:
    date_to = _date_param(request, "date_to") or timezone.localdate()
    date_from = _date_param(request, "date_from") or date_to - timedelta(days=30)
    if date_from > date_to:
        raise ValidationError({"date_from": ["Başlangıç bitişten sonra olamaz."]})
    return date_from, date_to


def _read_write(read: tuple[str, ...], write: tuple[str, ...], request: Request) -> Any:
    return [HasRole(*(read if request.method == "GET" else write))()]


# --- tehlike ifadeleri ve malzeme tehlike bilgisi ------------------------------------------------


class HazardStatementViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """H / P / EUH ifadeleri. Okuma herkese; ekleme ve düzeltme yönetim ve laboratuvara."""

    serializer_class = s.HazardStatementSerializer
    filterset_fields = ["kind", "is_active"]
    search_fields = ["code", "text"]
    ordering_fields = ["code", "kind"]
    ordering = ["kind", "code"]
    queryset = HazardStatement.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self) -> list[BasePermission]:
        return _read_write(services.HAZARD_READ_ROLES, services.HAZARD_ROLES, self.request)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """İfade ekler."""
        body = s.HazardStatementSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        statement = services.create_statement(_user(request), body.validated_data)
        return Response(s.HazardStatementSerializer(statement).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.HazardStatementUpdateSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """İfade metnini düzeltir."""
        body = s.HazardStatementUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        statement = services.update_statement(
            _user(request), self.get_object(), body.validated_data
        )
        return Response(s.HazardStatementSerializer(statement).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """İfadeyi aktif yapar."""
        statement = services.set_statement_active(_user(request), self.get_object(), True)
        return Response(s.HazardStatementSerializer(statement).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """İfadeyi pasife alır."""
        statement = services.set_statement_active(_user(request), self.get_object(), False)
        return Response(s.HazardStatementSerializer(statement).data)


class MaterialHazardFilter(django_filters.FilterSet):
    pictogram = django_filters.ChoiceFilter(
        choices=HazardClass.choices, field_name="pictograms", method="filter_pictogram"
    )

    class Meta:
        model = MaterialHazard
        fields = ["material"]

    def filter_pictogram(self, queryset: QuerySet[MaterialHazard], name: str, value: str) -> Any:
        return queryset.filter(pictograms__contains=[value])


def _hazard_queryset() -> QuerySet[MaterialHazard]:
    return MaterialHazard.objects.select_related("material").prefetch_related("statements")


class MaterialHazardViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Malzemelerin tehlike bilgileri (lot listeleri, tartım, toplama ve sevkiyat uyarısı için).
    Okuma herkese açıktır; yazma `materials/<id>/hazard/` ile."""

    serializer_class = s.MaterialHazardSerializer
    filterset_class = MaterialHazardFilter
    search_fields = ["material__code", "material__name"]
    ordering = ["material__code"]
    permission_classes = [HasRole(*services.HAZARD_READ_ROLES)]

    def get_queryset(self) -> QuerySet[MaterialHazard]:
        return _hazard_queryset()


class MaterialHazardView(APIView):
    """Malzeme kartının "Tehlike" sekmesi. Okuma herkese; yazma yönetim ve laboratuvara."""

    def get_permissions(self) -> list[BasePermission]:
        return _read_write(services.HAZARD_READ_ROLES, services.HAZARD_ROLES, self.request)

    def _data(self, material: Material) -> dict[str, Any]:
        hazard = _hazard_queryset().filter(material=material).first()
        if hazard is not None:
            return dict(s.MaterialHazardSerializer(hazard).data)
        # Tehlike bilgisi girilmemiş malzeme: boş profil.
        return {
            "id": None,
            "material": material.pk,
            "material_code": material.code,
            "material_name": material.name,
            "is_hazardous": material.is_hazardous,
            "pictograms": [],
            "pictogram_labels": [],
            "signal_word": "",
            "signal_word_display": "",
            "statements": [],
            "statement_rows": [],
            "note": "",
        }

    @extend_schema(responses=s.MaterialHazardSerializer)
    def get(self, request: Request, material_id: int) -> Response:
        material = get_object_or_404(Material, pk=material_id)
        return Response(self._data(material))

    @extend_schema(request=s.MaterialHazardSerializer, responses=s.MaterialHazardSerializer)
    def put(self, request: Request, material_id: int) -> Response:
        material = get_object_or_404(Material, pk=material_id)
        body = s.MaterialHazardSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.set_material_hazard(_user(request), material, body.validated_data)
        return Response(self._data(material))


# --- GBF ---------------------------------------------------------------------------------------


class SafetyDataSheetFilter(django_filters.FilterSet):
    current = django_filters.BooleanFilter(field_name="superseded_at", method="filter_current")

    class Meta:
        model = SafetyDataSheet
        fields = ["material", "supplier"]

    def filter_current(self, queryset: QuerySet[SafetyDataSheet], name: str, value: bool) -> Any:
        return queryset.filter(superseded_at__isnull=value)


class SafetyDataSheetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """GBF arşivi. Okuma yönetim, depo ve laboratuvara; kayıt yönetime. PDF, çekirdek ek API'si
    ile (`hse.safetydatasheet`) yüklenir."""

    serializer_class = s.SafetyDataSheetSerializer
    filterset_class = SafetyDataSheetFilter
    search_fields = ["material__code", "material__name", "revision_no"]
    ordering_fields = ["revision_date", "material__code", "created_at"]
    ordering = ["material__code", "-revision_date", "-id"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self) -> list[BasePermission]:
        return _read_write(services.SDS_READ_ROLES, services.HSE_ROLES, self.request)

    def get_queryset(self) -> QuerySet[SafetyDataSheet]:
        return SafetyDataSheet.objects.select_related("material", "supplier", "created_by")

    def _respond(self, sheet: SafetyDataSheet, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=sheet.pk)
        return Response(s.SafetyDataSheetSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Yeni GBF revizyonu girer; önceki geçerli GBF arşive geçer."""
        body = s.SafetyDataSheetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        sheet = services.create_sds(_user(request), body.validated_data)
        return self._respond(sheet, status.HTTP_201_CREATED)

    @extend_schema(request=s.SafetyDataSheetUpdateSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """GBF bilgilerini düzeltir."""
        body = s.SafetyDataSheetUpdateSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        sheet = services.update_sds(_user(request), self.get_object(), body.validated_data)
        return self._respond(sheet)


class SdsGapsView(APIView):
    """Eksik / eskimiş GBF raporu: aktif hammaddeler ve tehlikeli işaretli malzemeler."""

    permission_classes = [HasRole(*services.SDS_READ_ROLES)]

    @extend_schema(responses=s.SdsStatusSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.SdsStatusSerializer(selectors.sds_gaps(), many=True).data)


class SdsGapsExportView(APIView):
    """Eksik / eskimiş GBF raporunun Excel çıktısı."""

    permission_classes = [HasRole(*services.SDS_READ_ROLES)]

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request) -> HttpResponse:
        response = HttpResponse(exports.sds_gaps_xlsx(selectors.sds_gaps()), content_type=XLSX)
        filename = f"eksik-gbf-{timezone.localtime():%Y%m%d-%H%M}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# --- depolama limitleri ------------------------------------------------------------------------


class StorageLimitViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Lokasyon × tehlike sınıfı depolama limitleri. Okuma yönetim ve depoya; yazma yönetime."""

    serializer_class = s.StorageLimitSerializer
    filterset_fields = ["location", "hazard_class", "is_active"]
    search_fields = ["location__code", "location__name", "note"]
    ordering = ["location__code", "hazard_class"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self) -> list[BasePermission]:
        return _read_write(services.STORAGE_READ_ROLES, services.HSE_ROLES, self.request)

    def get_queryset(self) -> QuerySet[StorageLimit]:
        return StorageLimit.objects.select_related("location")

    def _respond(self, limit: StorageLimit, code: int = status.HTTP_200_OK) -> Response:
        return Response(
            s.StorageLimitSerializer(self.get_queryset().get(pk=limit.pk)).data, status=code
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Limit tanımlar."""
        body = s.StorageLimitSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        limit = services.create_storage_limit(_user(request), body.validated_data)
        return self._respond(limit, status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Limiti günceller."""
        instance = self.get_object()
        body = s.StorageLimitSerializer(instance, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        limit = services.update_storage_limit(_user(request), instance, body.validated_data)
        return self._respond(limit)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """Limiti aktif yapar."""
        return self._respond(
            services.set_storage_limit_active(_user(request), self.get_object(), True)
        )

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """Limiti pasife alır."""
        return self._respond(
            services.set_storage_limit_active(_user(request), self.get_object(), False)
        )


class StorageUtilisationView(APIView):
    """Depolama limitlerinin doluluğu (kg ve %)."""

    permission_classes = [HasRole(*services.STORAGE_READ_ROLES)]

    @extend_schema(
        parameters=[OpenApiParameter("location", int)],
        responses=s.StorageUtilisationSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        location = _object_param(request, "location", Location)
        rows = selectors.storage_utilisation(location)
        return Response(s.StorageUtilisationSerializer(rows, many=True).data)


# --- atık ----------------------------------------------------------------------------------------


class WasteContractorViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Lisanslı atık firmaları (yönetim)."""

    serializer_class = s.WasteContractorSerializer
    filterset_fields = ["is_active"]
    search_fields = ["name", "license_no"]
    ordering_fields = ["name", "license_valid_until"]
    ordering = ["name", "id"]
    permission_classes = [HasRole(*services.HSE_ROLES)]
    queryset = WasteContractor.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Firma tanımlar."""
        body = s.WasteContractorSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        contractor = services.create_contractor(_user(request), body.validated_data)
        return Response(
            s.WasteContractorSerializer(contractor).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Firmayı günceller (ör. lisans yenileme)."""
        instance = self.get_object()
        body = s.WasteContractorSerializer(instance, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        contractor = services.update_contractor(_user(request), instance, body.validated_data)
        return Response(s.WasteContractorSerializer(contractor).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, pk: str | None = None) -> Response:
        """Firmayı aktif yapar."""
        contractor = services.set_contractor_active(_user(request), self.get_object(), True)
        return Response(s.WasteContractorSerializer(contractor).data)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"])
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        """Firmayı pasife alır."""
        contractor = services.set_contractor_active(_user(request), self.get_object(), False)
        return Response(s.WasteContractorSerializer(contractor).data)


class WasteRecordFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=WasteRecord.Status.choices)
    date_from = django_filters.DateFilter(field_name="delivered_on", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="delivered_on", lookup_expr="lte")

    class Meta:
        model = WasteRecord
        fields = ["contractor", "is_hazardous", "waste_code"]


class WasteRecordViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Atık teslim kayıtları (`AT-`, yönetim). Taşıma formu ek olarak (`hse.wasterecord`)."""

    serializer_class = s.WasteRecordSerializer
    filterset_class = WasteRecordFilter
    search_fields = ["number", "waste_code", "description", "document_no", "contractor__name"]
    ordering_fields = ["delivered_on", "number", "quantity_kg"]
    ordering = ["-delivered_on", "-id"]
    permission_classes = [HasRole(*services.HSE_ROLES)]

    def get_queryset(self) -> QuerySet[WasteRecord]:
        return WasteRecord.objects.select_related("contractor", "created_by")

    def _respond(self, record: WasteRecord, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=record.pk)
        return Response(s.WasteRecordSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Atık teslimini kaydeder."""
        body = s.WasteRecordSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = services.record_waste(_user(request), body.validated_data)
        return self._respond(record, status.HTTP_201_CREATED)

    @extend_schema(request=CancelSerializer, responses=s.WasteRecordSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Atık kaydını iptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = services.cancel_waste_record(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(record)


# --- olay / kaza ---------------------------------------------------------------------------------


class IncidentFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=Incident.Status.choices)
    incident_type = django_filters.MultipleChoiceFilter(choices=Incident.Type.choices)
    severity = django_filters.MultipleChoiceFilter(choices=Incident.Severity.choices)
    date_from = django_filters.DateFilter(field_name="occurred_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="occurred_at", lookup_expr="date__lte")

    class Meta:
        model = Incident
        fields = ["injury", "location", "equipment"]


class IncidentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Olay / kaza kayıtları (`OL-`). Herkes bildirir ve kendi bildirdiklerini görür; yönetim
    tümünü görür, inceler, kapatır."""

    serializer_class = s.IncidentSerializer
    filterset_class = IncidentFilter
    search_fields = ["number", "place", "description", "injured_person"]
    ordering_fields = ["occurred_at", "number", "severity"]
    ordering = ["-occurred_at", "-id"]

    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "GET" or self.action == "create":
            return [HasRole(*services.INCIDENT_REPORT_ROLES)()]
        return [HasRole(*services.HSE_ROLES)()]

    def get_queryset(self) -> QuerySet[Incident]:
        queryset = Incident.objects.select_related("location", "equipment", "created_by")
        if not user_has_role(self.request.user, services.HSE_ROLES):
            queryset = queryset.filter(created_by=self.request.user.pk)
        return queryset

    def _respond(self, incident: Incident, code: int = status.HTTP_200_OK) -> Response:
        fresh = Incident.objects.select_related("location", "equipment", "created_by").get(
            pk=incident.pk
        )
        return Response(s.IncidentSerializer(fresh).data, status=code)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Olay bildirir; yönetime inceleme görevi düşer."""
        body = s.IncidentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = {k: v for k, v in body.validated_data.items() if k in services.INCIDENT_FIELDS}
        incident = services.report_incident(_user(request), data)
        return self._respond(incident, status.HTTP_201_CREATED)

    @extend_schema(request=s.InvestigationSerializer, responses=s.IncidentSerializer)
    @action(detail=True, methods=["post"])
    def investigate(self, request: Request, pk: str | None = None) -> Response:
        """İncelemeye alır (kök neden vb. isteğe bağlı)."""
        body = s.InvestigationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = services.start_investigation(
            _user(request), self.get_object(), body.validated_data
        )
        return self._respond(incident)

    @extend_schema(request=s.InvestigationSerializer, responses=s.IncidentSerializer)
    @action(detail=True, methods=["post"])
    def investigation(self, request: Request, pk: str | None = None) -> Response:
        """İnceleme bilgilerini (kök neden, faaliyet, sorumlu, termin) günceller."""
        body = s.InvestigationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = services.update_investigation(
            _user(request), self.get_object(), body.validated_data
        )
        return self._respond(incident)

    @extend_schema(request=s.CloseIncidentSerializer, responses=s.IncidentSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str | None = None) -> Response:
        """Kapatır (kök neden ve düzeltici faaliyet zorunlu)."""
        body = s.CloseIncidentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = services.close_incident(_user(request), self.get_object(), body.validated_data)
        return self._respond(incident)

    @extend_schema(request=CancelSerializer, responses=s.IncidentSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """İptal eder (neden zorunlu)."""
        body = CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = services.cancel_incident(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(incident)


# --- özet ve ayarlar -----------------------------------------------------------------------------


class HseSummaryView(APIView):
    """Olay ve atık özeti (varsayılan son 30 gün; yönetim)."""

    permission_classes = [HasRole(*services.HSE_ROLES)]

    @extend_schema(
        parameters=[OpenApiParameter("date_from", date), OpenApiParameter("date_to", date)],
        responses=s.HseSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        date_from, date_to = _period(request)
        data = {
            "date_from": date_from,
            "date_to": date_to,
            "incidents": selectors.incident_summary(date_from, date_to),
            "waste": selectors.waste_summary(date_from, date_to),
        }
        return Response(s.HseSummarySerializer(data).data)


class HseSettingsView(APIView):
    """GBF en çok yaşı. Okuma GBF'yi görenlere, değiştirme yönetime."""

    def get_permissions(self) -> list[BasePermission]:
        return _read_write(services.SDS_READ_ROLES, services.SETTINGS_ROLES, self.request)

    @extend_schema(responses=s.HseSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.HseSettingsSerializer(selectors.get_settings()).data)

    @extend_schema(request=s.HseSettingsSerializer, responses=s.HseSettingsSerializer)
    def patch(self, request: Request) -> Response:
        body = s.HseSettingsSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        instance = services.update_settings(_user(request), body.validated_data)
        return Response(s.HseSettingsSerializer(instance).data)
