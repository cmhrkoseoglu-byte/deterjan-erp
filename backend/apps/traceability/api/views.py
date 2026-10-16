from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasRole
from apps.core.roles import LABORATUVAR, YONETIM
from apps.inventory.models import Lot
from apps.traceability import exports, selectors
from apps.traceability.api import serializers as s

# İzlenebilirlik ve geri çağırma ekranı: laboratuvar ve yönetim (admin her yere).
TRACE_ROLES = (LABORATUVAR, YONETIM)
PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOT_PARAM = OpenApiParameter(
    "lot", int, many=True, required=True, description="Lot kimliği (birden çok verilebilir)"
)


class TraceView(APIView):
    permission_classes = [HasRole(*TRACE_ROLES)]

    def _lot(self, pk: int) -> Lot:
        return get_object_or_404(Lot.objects.select_related("material"), pk=pk)


class BackwardTraceView(TraceView):
    @extend_schema(responses=s.BackwardNodeSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """Geri izleme: lotu oluşturan girdi lotlar; hammaddede tedarikçi ve mal kabul."""
        tree = selectors.backward_trace(self._lot(pk))
        return Response(s.BackwardNodeSerializer(tree).data)


class ForwardTraceView(TraceView):
    @extend_schema(responses=s.ForwardNodeSerializer)
    def get(self, request: Request, pk: int) -> Response:
        """İleri izleme: lotun kullanıldığı lotlar; stokta, sevk ve iade miktarlarıyla."""
        tree = selectors.forward_trace(self._lot(pk))
        return Response(s.ForwardNodeSerializer(tree).data)


def _recall(request: Request) -> dict[str, Any]:
    query = s.RecallQuerySerializer(data={"lot": request.query_params.getlist("lot")})
    query.is_valid(raise_exception=True)
    return selectors.recall_simulation(query.validated_data["lot"])


def _file(content: bytes, content_type: str, extension: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    name = f"geri-cagirma-{timezone.localtime():%Y%m%d-%H%M}.{extension}"
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


class RecallView(TraceView):
    @extend_schema(parameters=[LOT_PARAM], responses=s.RecallSerializer)
    def get(self, request: Request) -> Response:
        """Geri çağırma simülasyonu: seçilen lotlar ve ileri soyları; stokta kalan, sevk edilen
        ve etkilenen müşteriler."""
        return Response(s.RecallSerializer(_recall(request)).data)


class RecallExcelView(TraceView):
    @extend_schema(parameters=[LOT_PARAM], responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request) -> HttpResponse:
        """Geri çağırma simülasyonu Excel dosyası."""
        return _file(exports.recall_xlsx(_recall(request)), XLSX, "xlsx")


class RecallPdfView(TraceView):
    @extend_schema(parameters=[LOT_PARAM], responses={(200, PDF): OpenApiTypes.BINARY})
    def get(self, request: Request) -> HttpResponse:
        """Geri çağırma simülasyonu PDF'i."""
        return _file(exports.recall_pdf(_recall(request)), PDF, "pdf")
