from typing import Any, ClassVar

import django_filters
from django.db.models import Count, Exists, OuterRef, Prefetch, QuerySet
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.labels import (
    LABEL_PARAMETERS,
    LabelOutputSerializer,
    PrintRequestSerializer,
    PrintResultSerializer,
    label_response,
)
from apps.core.exceptions import BusinessRuleError
from apps.core.labels import Label, render_zpl
from apps.core.models import DocumentModel
from apps.core.permissions import HasRole
from apps.core.roles import ADMIN, DEPO, DOLUM, LABORATUVAR, SEVKIYAT, URETIM
from apps.inventory import importers, labels, selectors, services
from apps.inventory.api import serializers as s
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    Lot,
    PalletLabel,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockMovement,
)
from apps.masterdata import services as masterdata_services
from apps.masterdata.api.serializers import ImportReportSerializer
from apps.masterdata.api.views import get_printer
from apps.masterdata.models import Material, Printer

# Stoka yazan roller (admin her yere erişir); lot bloke laboratuvarındır. Okuma herkese açık.
# Faz 2: lot serbest bırakma ve ret kalite kararıyladır (`quality`); elle serbest bırakma yalnızca
# admin (Karar D-5).
STOCK_WRITE_ROLES = (DEPO,)
LOT_DECISION_ROLES = (LABORATUVAR,)
MANUAL_RELEASE_ROLES = (ADMIN,)
READ_ACTIONS = frozenset(
    {"list", "retrieve", "metadata", "trace", "label", "labels", "case_label", "available"}
)
# Etiketi yazıcıya göndermek giriş yapmış herkese açık (baskı denetim günlüğüne yazılır).
PRINT_ACTIONS = frozenset({"print_label", "print_labels"})
# Palet (SSCC) etiketi açabilen roller.
PALLET_ROLES = (DEPO, DOLUM, SEVKIYAT, URETIM)
PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(request: Request) -> Any:
    return request.user


class RolePermissionMixin:
    """Okuma eylemleri giriş yapmış herkese, diğerleri `write_roles`'a açık."""

    write_roles: ClassVar[tuple[str, ...]] = STOCK_WRITE_ROLES
    action_roles: ClassVar[dict[str, tuple[str, ...]]] = {}

    def get_permissions(self) -> list[BasePermission]:
        name = getattr(self, "action", None)
        if name in READ_ACTIONS or name in PRINT_ACTIONS:
            return [IsAuthenticated()]
        return [HasRole(*self.action_roles.get(name or "", self.write_roles))()]


def _company() -> str:
    return masterdata_services.get_label_settings().company_name


def _output(
    request: Request, serializer: type[LabelOutputSerializer] = LabelOutputSerializer
) -> dict:
    params = serializer(data=request.query_params)
    params.is_valid(raise_exception=True)
    return dict(params.validated_data)


def _case_labels(lot: Lot, copies: int, units_per_case: int | None) -> list[Label]:
    if lot.material.material_type != Material.Type.FINISHED:
        raise BusinessRuleError(
            "not_finished_goods", "Koli etiketi yalnızca mamul lotlarına basılır."
        )
    return [labels.case_label(lot, _company(), units_per_case)] * copies


def _print_request(request: Request) -> tuple[Printer, int]:
    """Yazdırma isteğini doğrular: (yazıcı, kopya sayısı)."""
    body = PrintRequestSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    return get_printer(body.validated_data["printer"]), int(body.validated_data["copies"])


def _print(
    request: Request, printer: Printer, items: list[Label], target: Any, description: str
) -> Response:
    masterdata_services.send_to_printer(
        _user(request),
        printer,
        render_zpl(items, dpi=printer.dpi),
        target=target,
        description=description,
    )
    return Response({"printed": len(items), "printer": printer.code})


# --- lot -------------------------------------------------------------------------------------


class LotFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=Lot.Status.choices)
    source = django_filters.MultipleChoiceFilter(choices=Lot.Source.choices)
    material_type = django_filters.MultipleChoiceFilter(
        field_name="material__material_type", choices=Material.Type.choices
    )
    expiry_before = django_filters.DateFilter(field_name="expiry_date", lookup_expr="lte")
    has_stock = django_filters.BooleanFilter(method="filter_has_stock")

    class Meta:
        model = Lot
        fields = ["material", "supplier"]

    def filter_has_stock(self, queryset: QuerySet[Lot], name: str, value: bool) -> QuerySet[Lot]:
        if value is None:
            return queryset
        if value:
            return queryset.filter(total_quantity__gt=0)  # type: ignore[misc]
        return queryset.filter(total_quantity=0)  # type: ignore[misc]


class LotViewSet(RolePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """Lotlar. Serbest bırakma ve ret kalite kararıyladır (`/quality/samples/{id}/decide/`);
    burada laboratuvarın `block` işlemi ve admin'in gerekçeli elle serbest bırakması (D-5) var."""

    filterset_class = LotFilter
    search_fields = ["lot_no", "supplier_lot_no", "material__code", "material__name"]
    ordering_fields = ["lot_no", "expiry_date", "created_at", "total_quantity"]
    ordering = ["-created_at", "-id"]
    write_roles = LOT_DECISION_ROLES
    action_roles = {"release": MANUAL_RELEASE_ROLES}

    def get_queryset(self) -> QuerySet[Lot]:
        return selectors.lots_with_stock().select_related("released_by")

    def get_serializer_class(self) -> type[s.LotSerializer]:
        return s.LotDetailSerializer if self.action == "retrieve" else s.LotSerializer

    def _detail(self, lot: Lot) -> Response:
        return Response(s.LotDetailSerializer(self.get_queryset().get(pk=lot.pk)).data)

    @extend_schema(request=s.LotReleaseSerializer, responses=s.LotDetailSerializer)
    @action(detail=True, methods=["post"])
    def release(self, request: Request, pk: str | None = None) -> Response:
        """Elle serbest bırakma (yalnızca admin, gerekçe zorunlu; Karar D-5). Karantinadaki stok
        `to_location`'a taşınır."""
        body = s.LotReleaseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        lot = services.release_lot(
            _user(request),
            self.get_object(),
            body.validated_data["note"],
            to_location=body.validated_data["to_location"],
        )
        return self._detail(lot)

    @extend_schema(request=s.LotDecisionSerializer, responses=s.LotDetailSerializer)
    @action(detail=True, methods=["post"])
    def block(self, request: Request, pk: str | None = None) -> Response:
        """Lotu bloke eder (neden zorunlu)."""
        body = s.LotDecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        lot = services.block_lot(_user(request), self.get_object(), body.validated_data["note"])
        return self._detail(lot)

    @extend_schema(
        parameters=[
            OpenApiParameter("direction", str, enum=["backward", "forward"], required=False)
        ],
        responses=s.TraceNodeSerializer,
    )
    @action(detail=True, methods=["get"])
    def trace(self, request: Request, pk: str | None = None) -> Response:
        """Soy ağacı: `backward` (girdi lotlar, varsayılan) ya da `forward` (kullanıldığı
        lotlar)."""
        direction = request.query_params.get("direction", "backward")
        if direction not in ("backward", "forward"):
            raise ValidationError({"direction": ["backward ya da forward olmalıdır."]})
        tree = selectors.lot_trace(self.get_object(), direction)  # type: ignore[arg-type]
        return Response(s.TraceNodeSerializer(tree).data)

    @extend_schema(parameters=LABEL_PARAMETERS, responses={(200, PDF): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def label(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Lot etiketi (Code128 + QR, `LOT:<lot_no>`): PDF, A4 PDF ya da ZPL."""
        params = _output(request)
        lot = self.get_object()
        return label_response(
            labels.lot_labels([lot], _company(), params["copies"]),
            params["output"],
            f"etiket-{lot.lot_no}",
        )

    @extend_schema(
        parameters=[*LABEL_PARAMETERS, OpenApiParameter("units_per_case", OpenApiTypes.INT)],
        responses={(200, PDF): OpenApiTypes.BINARY},
    )
    @action(detail=True, methods=["get"], url_path="case-label")
    def case_label(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Mamul koli etiketi: GTIN varsa GS1-128, yoksa firma içi Code128 (Karar D-6)."""
        params = _output(request, s.CaseLabelOutputSerializer)
        lot = self.get_object()
        items = _case_labels(lot, params["copies"], params.get("units_per_case"))
        return label_response(items, params["output"], f"koli-{lot.lot_no}")

    @extend_schema(request=s.LotPrintSerializer, responses=PrintResultSerializer)
    @action(detail=True, methods=["post"], url_path="print-label")
    def print_label(self, request: Request, pk: str | None = None) -> Response:
        """Lot ya da koli etiketini ağ yazıcısına (ZPL) gönderir."""
        body = s.LotPrintSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        lot = self.get_object()
        copies = body.validated_data["copies"]
        printer = get_printer(body.validated_data["printer"])
        if body.validated_data["kind"] == "case":
            items = _case_labels(lot, copies, body.validated_data.get("units_per_case"))
            return _print(request, printer, items, lot, f"koli etiketi × {copies}")
        items = labels.lot_labels([lot], _company(), copies)
        return _print(request, printer, items, lot, f"lot etiketi × {copies}")


# --- hareket, bakiye, transfer ---------------------------------------------------------------


class MovementFilter(django_filters.FilterSet):
    movement_type = django_filters.MultipleChoiceFilter(choices=StockMovement.Type.choices)
    created_after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = StockMovement
        fields = ["material", "lot", "location", "document_number", "transfer_group"]


class StockMovementViewSet(RolePermissionMixin, viewsets.ReadOnlyModelViewSet):
    """Stok hareket defteri (salt okunur). Düzeltme `reverse` ile ters kayıttır."""

    serializer_class = s.StockMovementSerializer
    filterset_class = MovementFilter
    search_fields = ["lot__lot_no", "material__code", "material__name", "document_number"]
    ordering_fields = ["created_at", "quantity"]
    ordering = ["-created_at", "-id"]

    def get_queryset(self) -> QuerySet[StockMovement]:
        return StockMovement.objects.select_related(
            "material__base_unit", "lot", "location", "created_by", "source_content_type"
        ).annotate(has_reversal=Exists(StockMovement.objects.filter(reversal_of=OuterRef("pk"))))

    @extend_schema(request=s.ReverseSerializer, responses=s.StockMovementSerializer(many=True))
    @action(detail=True, methods=["post"])
    def reverse(self, request: Request, pk: str | None = None) -> Response:
        """Hareketi ters kayıtla geri alır (neden zorunlu); transferde iki bacak birlikte."""
        body = s.ReverseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        reversals = services.reverse_movement(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        rows = self.get_queryset().filter(pk__in=[m.pk for m in reversals]).order_by("id")
        return Response(s.StockMovementSerializer(rows, many=True).data)


class BalanceFilter(django_filters.FilterSet):
    lot_status = django_filters.MultipleChoiceFilter(
        field_name="lot__status", choices=Lot.Status.choices
    )
    material_type = django_filters.MultipleChoiceFilter(
        field_name="material__material_type", choices=Material.Type.choices
    )
    warehouse = django_filters.NumberFilter(field_name="location__warehouse")
    location_type = django_filters.CharFilter(field_name="location__location_type")

    class Meta:
        model = StockBalance
        fields = ["material", "lot", "location"]


class StockBalanceViewSet(RolePermissionMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Stok bakiyeleri (yalnızca sıfırdan büyük). `available`: üretimde kullanılabilir lotlar."""

    serializer_class = s.StockBalanceSerializer
    filterset_class = BalanceFilter
    search_fields = ["material__code", "material__name", "lot__lot_no", "location__code"]
    ordering_fields = [
        "material__code",
        "lot__lot_no",
        "location__code",
        "quantity",
        "lot__expiry_date",
    ]
    ordering = ["material__code", "lot__lot_no", "location__code"]

    def get_queryset(self) -> QuerySet[StockBalance]:
        return selectors.balances()

    @extend_schema(
        parameters=[OpenApiParameter("material", int, required=True)],
        responses=s.StockBalanceSerializer(many=True),
        filters=False,
    )
    @action(detail=False, methods=["get"], filter_backends=[], pagination_class=None)
    def available(self, request: Request) -> Response:
        """Malzemenin üretimde kullanılabilir stoku (serbest, SKT'si geçmemiş), FEFO sırasıyla."""
        material_id = request.query_params.get("material", "")
        material = (
            Material.objects.filter(pk=material_id).first() if material_id.isdigit() else None
        )
        if material is None:
            raise ValidationError({"material": ["Geçerli bir malzeme seçilmelidir."]})
        rows = selectors.available_lots(material)
        return Response(s.StockBalanceSerializer(rows, many=True).data)


class TransferView(APIView):
    """Lotu lokasyonlar arasında taşır (iki hareket, ortak transfer grubu)."""

    permission_classes = [HasRole(*STOCK_WRITE_ROLES)]

    @extend_schema(request=s.TransferSerializer, responses=s.StockMovementSerializer(many=True))
    def post(self, request: Request) -> Response:
        body = s.TransferSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        moves = services.transfer(
            _user(request),
            data["lot"],
            data["from_location"],
            data["to_location"],
            data["quantity"],
            note=data["note"],
        )
        return Response(
            s.StockMovementSerializer(moves, many=True).data, status=status.HTTP_201_CREATED
        )


# --- belgeler --------------------------------------------------------------------------------


class DocumentViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Taslak → kaydet (`post`) | iptal (`cancel`) belgesi. Durum PATCH ile değişmez."""

    detail_serializer: ClassVar[type[s.DocumentSerializer]]

    def get_serializer_class(self) -> type[s.DocumentSerializer]:
        if self.action == "list":
            return self.serializer_class  # type: ignore[return-value]
        return self.detail_serializer

    def _respond(self, document: DocumentModel, code: int = status.HTTP_200_OK) -> Response:
        fresh = self.get_queryset().get(pk=document.pk)
        return Response(self.detail_serializer(fresh).data, status=code)

    def _split(self, serializer: Any) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
        data = dict(serializer.validated_data)
        lines = data.pop("lines", None)
        return data, lines

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, lines = self._split(serializer)
        document = self.create_document(data, lines or [])
        return self._respond(document, status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data, lines = self._split(serializer)
        document = self.update_document(instance, data, lines)
        return self._respond(document)

    def create_document(self, data: dict[str, Any], lines: list[dict[str, Any]]) -> Any:
        raise NotImplementedError

    def update_document(
        self, instance: Any, data: dict[str, Any], lines: list[dict[str, Any]] | None
    ) -> Any:
        raise NotImplementedError


class GoodsReceiptFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=GoodsReceipt.Status.choices)
    date_from = django_filters.DateFilter(field_name="receipt_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="receipt_date", lookup_expr="lte")

    class Meta:
        model = GoodsReceipt
        fields = ["supplier"]


class GoodsReceiptViewSet(DocumentViewSet):
    """Mal kabul. Satırlar iç içe yazılır; `post` lotları açıp stoka alır."""

    serializer_class = s.GoodsReceiptSerializer
    detail_serializer = s.GoodsReceiptDetailSerializer
    filterset_class = GoodsReceiptFilter
    search_fields = ["number", "delivery_note_no", "supplier__name", "supplier__code"]
    ordering_fields = ["receipt_date", "number", "created_at"]
    ordering = ["-receipt_date", "-id"]

    def get_queryset(self) -> QuerySet[GoodsReceipt]:
        queryset = GoodsReceipt.objects.select_related(
            "supplier", "quarantine_location", "storage_location", "posted_by", "created_by"
        ).annotate(line_count=Count("lines"))
        if self.action != "list":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "lines",
                    queryset=GoodsReceiptLine.objects.select_related(
                        "material__base_unit", "unit", "created_lot"
                    ).order_by("line_no"),
                )
            )
        return queryset

    def create_document(self, data: dict[str, Any], lines: list[dict[str, Any]]) -> Any:
        return services.create_goods_receipt(_user(self.request), data, lines)

    def update_document(
        self, instance: Any, data: dict[str, Any], lines: list[dict[str, Any]] | None
    ) -> Any:
        return services.update_goods_receipt(_user(self.request), instance, data, lines)

    @extend_schema(request=None, responses=s.GoodsReceiptDetailSerializer)
    @action(detail=True, methods=["post"], url_path="post", url_name="post")
    def post_document(self, request: Request, pk: str | None = None) -> Response:
        """Mal kabulü kaydeder: lotlar açılır, stok karantina/depo lokasyonuna alınır."""
        return self._respond(services.post_goods_receipt(_user(request), self.get_object()))

    @extend_schema(request=s.CancelSerializer, responses=s.GoodsReceiptDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Taslak mal kabulü iptal eder (neden zorunlu)."""
        body = s.CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        receipt = services.cancel_goods_receipt(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(receipt)

    def _receipt_labels(self, receipt: GoodsReceipt, copies: int) -> list[Label]:
        lots = [
            line.created_lot
            for line in receipt.lines.select_related(
                "created_lot__material", "created_lot__supplier"
            ).order_by("line_no")
            if line.created_lot is not None
        ]
        return labels.lot_labels(lots, _company(), copies)

    @extend_schema(parameters=LABEL_PARAMETERS, responses={(200, PDF): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def labels(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Mal kabulde oluşan lotların etiketleri (lot başına `copies` adet)."""
        params = _output(request)
        receipt = self.get_object()
        return label_response(
            self._receipt_labels(receipt, params["copies"]),
            params["output"],
            f"etiket-{receipt.number}",
        )

    @extend_schema(request=PrintRequestSerializer, responses=PrintResultSerializer)
    @action(detail=True, methods=["post"], url_path="print-labels")
    def print_labels(self, request: Request, pk: str | None = None) -> Response:
        """Mal kabul lotlarının etiketlerini ağ yazıcısına gönderir."""
        printer, copies = _print_request(request)
        receipt = self.get_object()
        items = self._receipt_labels(receipt, copies)
        if not items:
            raise BusinessRuleError("no_lots", "Bu mal kabulde henüz lot yok.")
        return _print(request, printer, items, receipt, f"mal kabul lot etiketleri ({len(items)})")


class StockAdjustmentFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(choices=StockAdjustment.Status.choices)
    date_from = django_filters.DateFilter(field_name="adjustment_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="adjustment_date", lookup_expr="lte")

    class Meta:
        model = StockAdjustment
        fields: list[str] = []


class StockAdjustmentViewSet(DocumentViewSet):
    """Sayım düzeltme. Depo hazırlar ve kaydeder (Karar D-3)."""

    serializer_class = s.StockAdjustmentSerializer
    detail_serializer = s.StockAdjustmentDetailSerializer
    filterset_class = StockAdjustmentFilter
    search_fields = ["number", "note"]
    ordering_fields = ["adjustment_date", "number", "created_at"]
    ordering = ["-adjustment_date", "-id"]

    def get_queryset(self) -> QuerySet[StockAdjustment]:
        queryset = StockAdjustment.objects.select_related("posted_by", "created_by").annotate(
            line_count=Count("lines")
        )
        if self.action != "list":
            queryset = queryset.prefetch_related(
                Prefetch(
                    "lines",
                    queryset=StockAdjustmentLine.objects.select_related(
                        "lot__material__base_unit", "location"
                    ).order_by("line_no"),
                )
            )
        return queryset

    def create_document(self, data: dict[str, Any], lines: list[dict[str, Any]]) -> Any:
        return services.create_stock_adjustment(_user(self.request), data, lines)

    def update_document(
        self, instance: Any, data: dict[str, Any], lines: list[dict[str, Any]] | None
    ) -> Any:
        return services.update_stock_adjustment(_user(self.request), instance, data, lines)

    @extend_schema(request=None, responses=s.StockAdjustmentDetailSerializer)
    @action(detail=True, methods=["post"], url_path="post", url_name="post")
    def post_document(self, request: Request, pk: str | None = None) -> Response:
        """Sayım düzeltmeyi kaydeder: farklar düzeltme hareketi olarak yazılır."""
        return self._respond(services.post_stock_adjustment(_user(request), self.get_object()))

    @extend_schema(request=s.CancelSerializer, responses=s.StockAdjustmentDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str | None = None) -> Response:
        """Taslak sayım düzeltmeyi iptal eder (neden zorunlu)."""
        body = s.CancelSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        adjustment = services.cancel_stock_adjustment(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return self._respond(adjustment)


# --- açılış stoku ----------------------------------------------------------------------------


class OpeningImportView(APIView):
    """Açılış stoku içe aktarma. `confirm=false` önizleme (hiçbir şey yazılmaz), `confirm=true`
    aktarır. Hatalı satır varsa hiçbir kayıt yazılmaz; 400 yanıtında `report` döner."""

    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [HasRole(*STOCK_WRITE_ROLES)]

    @extend_schema(
        request={"multipart/form-data": s.OpeningUploadSerializer},
        responses={
            200: ImportReportSerializer,
            400: OpenApiResponse(description="import_has_errors (gövdede `report`)"),
        },
    )
    def post(self, request: Request) -> Response:
        upload = s.OpeningUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        file = upload.validated_data["file"]
        if upload.validated_data["confirm"]:
            try:
                report = importers.run_opening_import(_user(request), file, file.name)
            except importers.OpeningImportHasErrors as exc:
                body = {
                    "code": exc.code,
                    "detail": exc.message,
                    "report": {**exc.report.as_dict(), "imported": False},
                }
                return Response(body, status=status.HTTP_400_BAD_REQUEST)
            return Response({**report.as_dict(), "imported": True})
        report = importers.preview_opening(_user(request), file, file.name)
        return Response({**report.as_dict(), "imported": False})


class OpeningTemplateView(APIView):
    """Açılış stoku şablonu (.xlsx)."""

    permission_classes = [HasRole(*STOCK_WRITE_ROLES)]

    @extend_schema(responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request) -> HttpResponse:
        response = HttpResponse(importers.build_template(), content_type=XLSX)
        response["Content-Disposition"] = 'attachment; filename="sablon-acilis-stoku.xlsx"'
        return response


# --- palet etiketi ve okutma -----------------------------------------------------------------


class PalletLabelViewSet(
    RolePermissionMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """SSCC'li palet etiketleri (Karar D-6: GS1 firma öneki tanımlıysa). Oluşturma depo, dolum,
    sevkiyat ve üretime açık; etiket indirme ve yazdırma herkese."""

    queryset = PalletLabel.objects.select_related("lot__material", "created_by")
    serializer_class = s.PalletLabelSerializer
    filterset_fields = ["lot"]
    search_fields = ["sscc", "lot__lot_no"]
    ordering = ["-created_at", "-id"]
    write_roles = PALLET_ROLES

    def perform_create(self, serializer: Any) -> None:
        data = serializer.validated_data
        serializer.instance = services.create_pallet_label(
            _user(self.request),
            data["lot"],
            data["case_count"],
            units_per_case=data.get("units_per_case"),
        )

    @extend_schema(parameters=LABEL_PARAMETERS, responses={(200, PDF): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def label(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Palet etiketi (SSCC + içerik barkodu): PDF, A4 PDF ya da ZPL."""
        params = _output(request)
        pallet = self.get_object()
        items = [labels.pallet_label(pallet, _company())] * params["copies"]
        return label_response(items, params["output"], f"palet-{pallet.sscc}")

    @extend_schema(request=PrintRequestSerializer, responses=PrintResultSerializer)
    @action(detail=True, methods=["post"], url_path="print-label")
    def print_label(self, request: Request, pk: str | None = None) -> Response:
        """Palet etiketini ağ yazıcısına gönderir."""
        printer, copies = _print_request(request)
        pallet = self.get_object()
        items = [labels.pallet_label(pallet, _company())] * copies
        return _print(request, printer, items, pallet, f"palet etiketi × {copies}")


class ScanView(APIView):
    """Okutulan barkodu çözer: lot, lokasyon, malzeme ya da palet (`?code=`)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("code", OpenApiTypes.STR, required=True)],
        responses=s.ScanResultSerializer,
    )
    def get(self, request: Request) -> Response:
        code = request.query_params.get("code", "")
        if not code.strip():
            raise ValidationError({"code": ["Okutulan kod boş."]})
        result = selectors.decode_scan(code)
        return Response(s.ScanResultSerializer(result).data)
