"""Raporlama API'si: panolar, raporlar (ekran + Excel/PDF), arka plan rapor işleri.

Yetki (docs/plan/kisi-yetkileri.md §3.15): her pano ve rapor kendi yetki bölümüyle korunur
(`reporting.access`; admin hepsini görür). Uç noktalar giriş yapan herkese açıktır, bölüm görünümün
içinde denetlenir: bilinmeyen pano ya da rapor önce 404, yetkisiz kişi sonra 403 alır; OPTIONS
herkese açık kalır. Tutar sütunları ve stok değeri Maliyetleri görür'e, panodaki onay bekleyen
satın alma siparişlerinin TL toplamı Fiyatları görür'e bağlıdır; bu süzme `reports.py` ve
`dashboards.py` içinde, ekran ve dosya için aynı kuralla yapılır. Rapor dosyası indirilirken
raporun yetkisi yeniden denetlenir (§8 madde 12).
"""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import COSTS, PRICES, VIEW, Section
from apps.core.models import User
from apps.core.permissions import MissingAccess, SignedIn, has_access
from apps.reporting import dashboards, filters, services
from apps.reporting.access import LAB, MANAGEMENT, PRODUCTION, SHIPPING, WAREHOUSE
from apps.reporting.api import serializers as s
from apps.reporting.models import ReportJob
from apps.reporting.reports import (
    ReportDefinition,
    can_view,
    get_report,
    reports_for,
    visible_columns,
)
from apps.reporting.selectors import page_of


def _user(request: Request) -> User:
    user = request.user
    assert isinstance(user, User)
    return user


def jsonable(value: Any) -> Any:
    """Pano ve rapor değerlerini JSON'a çevirir: Decimal metin olarak (kayan nokta yok),
    tarih ve zaman ISO biçiminde."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


# --- panolar ---------------------------------------------------------------------------------

Dashboard = tuple[str, Section, Callable[[Any], dict[str, Any]]]

DASHBOARDS: dict[str, Dashboard] = {
    "management": (
        "Yönetim panosu",
        MANAGEMENT,
        lambda user: dashboards.management_dashboard(
            show_costs=has_access(user, COSTS), show_prices=has_access(user, PRICES)
        ),
    ),
    "warehouse": ("Depo", WAREHOUSE, lambda user: dashboards.warehouse_dashboard()),
    "lab": ("Laboratuvar", LAB, lambda user: dashboards.lab_dashboard()),
    "production": ("Üretim", PRODUCTION, lambda user: dashboards.production_dashboard()),
    "shipping": ("Sevkiyat", SHIPPING, lambda user: dashboards.shipping_dashboard()),
}


def _deny(message: str, section: Section) -> MissingAccess:
    return MissingAccess(message, ((section.key, VIEW),))


class DashboardListView(APIView):
    permission_classes = [SignedIn("pano listesi kişinin görebildiği panolarla daralır")]

    @extend_schema(responses=s.DashboardInfoSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Kullanıcının görebildiği panolar."""
        return Response(
            [
                {"code": code, "title": title}
                for code, (title, section, _) in DASHBOARDS.items()
                if has_access(request.user, section)
            ]
        )


class DashboardView(APIView):
    permission_classes = [
        SignedIn("bilinmeyen pano 404, yetki pano koduna göre görünümde denetlenir (403)")
    ]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, code: str) -> Response:
        """Pano verisi (`management`, `warehouse`, `lab`, `production`, `shipping`)."""
        if code not in DASHBOARDS:
            raise NotFound("Böyle bir pano yok.")
        _, section, build = DASHBOARDS[code]
        if not has_access(request.user, section):
            raise _deny("Bu panoyu görme yetkiniz yok.", section)
        return Response(jsonable(build(request.user)))


# --- raporlar --------------------------------------------------------------------------------


def _definition(request: Request, code: str) -> ReportDefinition:
    definition = get_report(code)
    if definition is None:
        raise NotFound("Böyle bir rapor yok.")
    if not can_view(definition, _user(request)):
        raise _deny("Bu raporu görme yetkiniz yok.", definition.section)
    return definition


def _columns(definition: ReportDefinition, user: Any) -> list[dict[str, str]]:
    return [
        {"key": c.key, "label": c.label, "kind": c.kind} for c in visible_columns(definition, user)
    ]


class ReportListView(APIView):
    permission_classes = [SignedIn("rapor listesi kişinin görebildiği raporlarla daralır")]

    @extend_schema(responses=s.ReportInfoSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Kullanıcının görebildiği raporlar, filtreleri ve sütunlarıyla."""
        return Response(
            [
                {
                    "code": d.code,
                    "title": d.title,
                    "description": d.description,
                    "filters": list(d.filters),
                    "default_days": d.default_days,
                    "columns": _columns(d, request.user),
                }
                for d in reports_for(_user(request))
            ]
        )


PAGE_PARAMS = [
    OpenApiParameter("page", int, description="Sayfa (1'den başlar)"),
    OpenApiParameter("page_size", int, description="Sayfa boyu (varsayılan 50, en fazla 500)"),
]


class ReportView(APIView):
    permission_classes = [
        SignedIn("bilinmeyen rapor 404, yetki rapor koduna göre görünümde denetlenir (403)")
    ]

    @extend_schema(
        parameters=[filters.ReportFilterSerializer, *PAGE_PARAMS],
        responses=s.ReportPageSerializer,
    )
    def get(self, request: Request, code: str) -> Response:
        """Raporun bir sayfası: görünür sütunlar, özet ve satırlar. Tarih filtresi boşsa son 30
        gün (stok durumu tarihsizdir)."""
        definition = _definition(request, code)
        values = filters.parse_filters(definition, request.query_params)
        data = services.report_data(definition, _user(request), values)
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            size = min(max(int(request.query_params.get("page_size", 50)), 1), 500)
        except ValueError:
            page, size = 1, 50
        keys = [c.key for c in data.columns]
        rows = page_of(data.rows, (page - 1) * size, size)
        return Response(
            {
                "code": definition.code,
                "title": definition.title,
                "columns": _columns(definition, request.user),
                "summary": jsonable(data.summary),
                "filters": jsonable(filters.to_params(values)),
                "count": len(data.rows),
                "sync_limit": services.SYNC_ROW_LIMIT,
                "results": [jsonable({k: row.get(k) for k in keys}) for row in rows],
            }
        )


class ReportExportView(APIView):
    permission_classes = [
        SignedIn("yetki rapor koduna göre görünümde ve serviste, gövdeden önce denetlenir")
    ]

    @extend_schema(
        parameters=[filters.ReportFilterSerializer],
        request=s.ExportRequestSerializer,
        responses={
            (200, "application/octet-stream"): OpenApiTypes.BINARY,
            202: s.ReportJobSerializer,
        },
    )
    def post(self, request: Request, code: str) -> HttpResponse | Response:
        """Excel ya da PDF. 5.000 satıra kadar dosya hemen döner (200); daha büyük rapor arka
        planda hazırlanır (202 + iş kaydı) ve hazır olunca bildirim gelir. Filtreler sorgu
        parametresi ya da gövdede verilebilir."""
        definition = _definition(request, code)
        body = s.ExportRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        source = {**request.query_params.dict(), **dict(request.data)}
        values = filters.parse_filters(definition, source)
        result = services.export_report(
            _user(request),
            definition,
            values,
            body.validated_data["file_format"],
        )
        if isinstance(result, ReportJob):
            return Response(s.ReportJobSerializer(result).data, status=status.HTTP_202_ACCEPTED)
        response = HttpResponse(result.content, content_type=result.content_type)
        response["Content-Disposition"] = f'attachment; filename="{result.file_name}"'
        return response


# --- arka plan işleri ------------------------------------------------------------------------


def _own_jobs(request: Request) -> QuerySet[ReportJob]:
    """Kullanıcı yalnızca kendi istediği dosyaları görür (admin dahil)."""
    if not isinstance(request.user, User):  # şema üretimi (anonim)
        return ReportJob.objects.none()
    return ReportJob.objects.filter(created_by=_user(request))


class ReportJobListView(generics.ListAPIView):
    permission_classes = [SignedIn("kişinin kendi rapor dosyaları (indirmeler herkese açık)")]
    serializer_class = s.ReportJobSerializer
    filterset_fields = ["status", "report_code", "file_format"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self) -> QuerySet[ReportJob]:
        return _own_jobs(self.request)


class ReportJobDetailView(generics.RetrieveAPIView):
    permission_classes = [SignedIn("kişinin kendi rapor dosyası; başkasınınki 404")]
    serializer_class = s.ReportJobSerializer

    def get_queryset(self) -> QuerySet[ReportJob]:
        return _own_jobs(self.request)


class ReportJobDownloadView(APIView):
    permission_classes = [
        SignedIn("kişinin kendi rapor dosyası; raporun yetkisi indirmede yeniden denetlenir")
    ]

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request: Request, pk: int) -> FileResponse:
        """Hazır dosyayı indirir (yalnızca isteyen kişi, raporun yetkisi hâlâ varsa)."""
        job = get_object_or_404(_own_jobs(request), pk=pk)
        if job.status != ReportJob.Status.DONE or not job.file:
            raise NotFound("Dosya hazır değil ya da saklama süresi doldu.")
        missing = services.missing_download_access(_user(request), job)
        if missing:
            raise MissingAccess("Bu dosyayı indirme yetkiniz artık yok.", missing)
        return FileResponse(
            job.file.open("rb"),
            as_attachment=True,
            filename=job.file_name,
            content_type=services.CONTENT_TYPES[job.file_format],
        )
