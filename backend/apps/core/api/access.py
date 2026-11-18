"""Yetki API'si (docs/plan/kisi-yetkileri.md §5.1, §5.10, §6.2, §6.4): yetki kataloğu, Yetkilerim
ve "Kim neyi görür" raporu (kimde var, Excel). Kişinin yetki matrisi ve geçmişi
`UserViewSet`'tedir (`users/{pk}/access/`)."""

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import access, access_report
from apps.core.access_report_xlsx import access_report_xlsx
from apps.core.api.serializers import (
    AccessHoldersQuerySerializer,
    AccessHoldersSerializer,
    AccessReportQuerySerializer,
    AccessReportSerializer,
    MyAccessSerializer,
)
from apps.core.models import User
from apps.core.permissions import AccessAdminOnly, SignedIn
from apps.core.roles import ROLE_LABELS

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def holder_labels() -> dict[str, str]:
    """Paket sahiplerinin Türkçe adları: herkes, rolü olan herkes ve roller."""
    return {**access.HOLDER_LABELS, **{role: ROLE_LABELS[role] for role in access.ROLES}}


class AccessCatalogView(APIView):
    """Modüller, bölümler, düzeyler ve rollerin varsayılan paketleri. Yetki ekranları ve
    "Yetkiniz yok" sayfası bölüm adlarını buradan alır."""

    permission_classes = [SignedIn("katalog bölüm adlarını ve rol paketlerini gösterir")]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        return Response(
            {
                "hash": access.catalog_hash(),
                "levels": access.LEVEL_LABELS,
                "holders": holder_labels(),
                **access.catalog(),
            }
        )


class MyAccessView(APIView):
    """Yetkilerim: kişinin kendi yetkileri ve kaynakları (rolünden, herkese açık, size özel
    verildi) ile kişiden kaldırılanlar. Gerekçe, değiştiren ve tarih gösterilmez (plan §5.10)."""

    permission_classes = [SignedIn("kişinin kendi yetkileri (Yetkilerim)")]

    @extend_schema(responses=MyAccessSerializer)
    def get(self, request: Request) -> Response:
        user: User = request.user  # type: ignore[assignment]
        return Response(MyAccessSerializer(access_report.my_access(user)).data)


class AccessReportView(APIView):
    """Kim neyi görür: etkin kullanıcıların geçerli yetkileri, kişiye özel ayarları ve görev
    ayrılığı işaretleri (yalnız admin). `?user=` tek kişi."""

    permission_classes = [AccessAdminOnly]

    @extend_schema(parameters=[AccessReportQuerySerializer], responses=AccessReportSerializer)
    def get(self, request: Request) -> Response:
        query = AccessReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = access_report.report(query.validated_data.get("user"))
        return Response(AccessReportSerializer(access_report.report_body(rows)).data)


class AccessHoldersView(APIView):
    """Kimde var: bir bölüm düzeyini etkin olarak taşıyan kişiler ve kaynakları; rol paketinde
    olup kişiden kaldırılanlar en sonda (yalnız admin)."""

    permission_classes = [AccessAdminOnly]

    @extend_schema(
        parameters=[AccessHoldersQuerySerializer],
        responses={
            200: AccessHoldersSerializer,
            400: OpenApiResponse(description="unknown_access"),
        },
    )
    def get(self, request: Request) -> Response:
        query = AccessHoldersQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        body = access_report.holders(query.validated_data["key"], query.validated_data["level"])
        return Response(AccessHoldersSerializer(body).data)


class AccessReportExportView(APIView):
    """Kim neyi görür raporunun Excel çıktısı (doküman kontrollü; gerekçe içerir, yalnız admin).
    Tarayıcı ve ara sunucu önbelleğine yazılmaz."""

    permission_classes = [AccessAdminOnly]

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request) -> HttpResponse:
        content = access_report_xlsx(access_report.report(), holder_labels())
        response = HttpResponse(content, content_type=XLSX)
        filename = f"yetki-raporu-{timezone.localtime():%Y%m%d-%H%M}.xlsx"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response
