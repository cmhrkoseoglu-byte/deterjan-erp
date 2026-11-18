"""Cari hesaplar API'si (docs/plan/cari-hesaplar.md §2.5).

`/api/v1/ledger/customers/` ve `/api/v1/ledger/suppliers/`: liste (bakiye, yaşlandırma), cari
özeti, ekstre, elle kayıt, iptal ve fiyatı eksik belgeler. Görür liste ve ekstreyi açar; tutarlar
ayrıca Fiyatları görür ister. Yazma işlemleri Değiştirir ve Fiyatları görür ister.
"""

from typing import Any, ClassVar

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.access import CHANGE, PRICES, VIEW, Section
from apps.core.pagination import StandardPagination
from apps.core.permissions import AccessMixin, HasAccess
from apps.ledger import exports, selectors, services
from apps.ledger.access import CUSTOMERS, SUPPLIERS
from apps.ledger.api import serializers as s
from apps.ledger.models import LedgerEntry, Side
from apps.masterdata.models import Customer
from apps.returns.models import CustomerReturn
from apps.sales.models import ShipmentLine


def _user(request: Request) -> Any:
    return request.user


def _read(section: Section) -> Any:
    return HasAccess(section, VIEW)


def _write(section: Section) -> Any:
    return HasAccess(section, CHANGE) & HasAccess(PRICES, VIEW)


DATE_PARAMS = [
    OpenApiParameter("date_from", str, description="Başlangıç tarihi (YYYY-AA-GG)"),
    OpenApiParameter("date_to", str, description="Bitiş tarihi (YYYY-AA-GG)"),
]
LIST_PARAMS = [
    OpenApiParameter("search", str, description="Kod ya da ünvan"),
    OpenApiParameter("with_balance", bool, description="Yalnız bakiyesi olanlar"),
    OpenApiParameter("overdue", bool, description="Yalnız vadesi geçen tutarı olanlar"),
    OpenApiParameter("currency", str, description="Para birimi (TRY, EUR, USD)"),
    OpenApiParameter("include_inactive", bool, description="Hareketsiz pasif cariler de"),
]


class PartnerLedgerViewSet(AccessMixin, viewsets.GenericViewSet):
    """Bir tarafın (müşteri ya da tedarikçi) cari hesapları."""

    side: ClassVar[str]
    section: ClassVar[Section]
    pagination_class = StandardPagination
    lookup_value_regex = r"\d+"
    # Şema üretimi için; kayıtlar seçicilerden okunur.
    queryset = LedgerEntry.objects.none()
    serializer_class = s.PartnerRowSerializer

    def get_partner(self) -> selectors.Partner:
        return self._partner(int(self.kwargs["pk"]))

    def _partner(self, pk: int) -> selectors.Partner:
        partner = selectors.find_partner(self.side, pk)
        if partner is None:
            raise NotFound("Cari bulunamadı.")
        return partner

    def _context(self) -> dict[str, Any]:
        return dict(self.get_serializer_context())

    def _list_rows(self, request: Request) -> list[dict[str, Any]]:
        query = s.ListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return selectors.partner_rows(self.side, **dict(query.validated_data))

    @extend_schema(parameters=LIST_PARAMS, responses=s.PartnerListSerializer)
    def list(self, request: Request) -> Response:
        rows = self._list_rows(request)
        page = self.paginate_queryset(rows)  # type: ignore[arg-type]
        data = s.PartnerRowSerializer(page, many=True, context=self._context()).data
        response = self.get_paginated_response(data)
        if s.can_see_prices(self._context()):
            response.data["totals"] = s.TotalSerializer(
                selectors.totals(rows, self.side), many=True
            ).data
        return response

    @extend_schema(responses=s.SummarySerializer)
    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        partner = self.get_partner()
        summary = {
            "partner": partner,
            "balances": selectors.balances_of(partner),
            "missing": selectors.missing_price_counts(self.side)[partner.pk],
        }
        return Response(s.SummarySerializer(summary, context=self._context()).data)

    def _statement_args(self, request: Request) -> dict[str, Any]:
        query = s.StatementQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return dict(query.validated_data)

    @extend_schema(parameters=DATE_PARAMS, responses=s.StatementSerializer)
    @action(detail=True)
    def statement(self, request: Request, pk: str | None = None) -> Response:
        """Ekstre: para birimi başına devreden bakiye, satırlar ve toplamlar; müşteride
        teslim alınmış iadeler bilgi satırıdır."""
        partner = self.get_partner()
        dates = self._statement_args(request)
        data = {
            "partner": partner,
            **dates,
            "currencies": selectors.statement(partner, dates["date_from"], dates["date_to"]),
            "returns": selectors.returns_of(partner, dates["date_from"], dates["date_to"])
            if isinstance(partner, Customer)
            else [],
        }
        return Response(s.StatementSerializer(data, context=self._context()).data)

    @extend_schema(parameters=DATE_PARAMS, responses={(200, exports.XLSX): bytes})
    @action(detail=True, url_path="statement-xlsx")
    def statement_xlsx(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Ekstrenin Excel çıktısı (tutarlar yalnız Fiyatları görür ile)."""
        partner = self.get_partner()
        dates = self._statement_args(request)
        return exports.statement_xlsx(_user(request), partner, dates["date_from"], dates["date_to"])

    @extend_schema(parameters=DATE_PARAMS, responses={(200, "application/pdf"): bytes})
    @action(detail=True, url_path="statement-pdf")
    def statement_pdf(self, request: Request, pk: str | None = None) -> HttpResponse:
        """Mutabakat için A4 ekstre (Fiyatları görür ister)."""
        partner = self.get_partner()
        dates = self._statement_args(request)
        return exports.statement_pdf(_user(request), partner, dates["date_from"], dates["date_to"])

    @extend_schema(parameters=LIST_PARAMS, responses={(200, exports.XLSX): bytes})
    @action(detail=False, url_path="export-xlsx")
    def export_xlsx(self, request: Request) -> HttpResponse:
        """Cari listesinin Excel çıktısı (süzgeçlerle)."""
        return exports.partners_xlsx(_user(request), self.side, self._list_rows(request))

    @extend_schema(request=s.ManualEntrySerializer, responses={201: s.EntrySerializer})
    @action(detail=True, methods=["post"])
    def entries(self, request: Request, pk: str | None = None) -> Response:
        """Elle kayıt: tahsilat / ödeme, iade dekontu, borç / alacak dekontu, açılış bakiyesi."""
        partner = self.get_partner()
        body = s.ManualEntrySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        values = dict(body.validated_data)
        return_id = values.pop("customer_return")
        customer_return = None
        if return_id is not None:
            customer_return = CustomerReturn.objects.filter(pk=return_id).first()
            if customer_return is None:
                raise ValidationError({"customer_return": "İade bulunamadı."})
        entry = services.post_manual_entry(
            _user(request), partner=partner, customer_return=customer_return, **values
        )
        return Response(
            s.EntrySerializer(entry, context=self._context()).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=s.EntryReverseSerializer, responses={201: s.EntrySerializer})
    @action(detail=True, methods=["post"])
    def reverse(self, request: Request, pk: str | None = None) -> Response:
        """Elle girilmiş kaydı ters kayıtla iptal eder (gerekçe zorunlu)."""
        partner = self.get_partner()
        body = s.EntryReverseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        entry = get_object_or_404(
            LedgerEntry, pk=body.validated_data["entry"], **{self.side: partner}
        )
        reversal = services.reverse_entry(_user(request), entry, body.validated_data["reason"])
        return Response(
            s.EntrySerializer(reversal, context=self._context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        parameters=[OpenApiParameter("partner", int, description="Yalnız bu cari")],
        responses=s.MissingPriceSerializer(many=True),
    )
    @action(detail=False, url_path="missing-prices")
    def missing_prices(self, request: Request) -> Response:
        """Fiyatı olmadığı için cariye yazılmamış belge satırları."""
        partner: selectors.Partner | None = None
        partner_id = request.query_params.get("partner")
        if partner_id:
            if not partner_id.isdigit():
                raise ValidationError({"partner": "Geçersiz cari."})
            partner = self._partner(int(partner_id))
        rows = selectors.missing_prices(self.side, partner)
        return Response(s.MissingPriceSerializer(rows, many=True).data)


class CustomerLedgerViewSet(PartnerLedgerViewSet):
    """Müşteri carileri; ayrıca fiyatı eksik sevkiyat satırına cari fiyatı ve iade dekontu
    önerisi."""

    side = Side.CUSTOMER
    section = CUSTOMERS
    read_access = _read(CUSTOMERS)
    action_access = {
        "entries": _write(CUSTOMERS),
        "reverse": _write(CUSTOMERS),
        "shipment_line_price": _write(CUSTOMERS),
        "return_suggestion": _write(CUSTOMERS),
        "statement_pdf": _read(CUSTOMERS) & HasAccess(PRICES, VIEW),
    }

    @extend_schema(request=s.ShipmentLinePriceSerializer, responses=s.EntrySerializer(many=True))
    @action(detail=False, methods=["post"], url_path="shipment-line-prices")
    def shipment_line_price(self, request: Request) -> Response:
        """Siparişinde fiyatı olmayan sevk edilmiş satıra cari fiyatı girer (sipariş değişmez);
        yazılan cari kayıtlarını döner."""
        body = s.ShipmentLinePriceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        values = body.validated_data
        line = get_object_or_404(ShipmentLine, pk=values["line"])
        created = services.set_shipment_line_price(
            _user(request), line, values["unit_price"], values["currency"], values["note"]
        )
        return Response(s.EntrySerializer(created, many=True, context=self._context()).data)

    @extend_schema(
        parameters=[OpenApiParameter("customer_return", int, required=True)],
        responses=s.ReturnSuggestionSerializer,
    )
    @action(detail=True, url_path="return-suggestion")
    def return_suggestion(self, request: Request, pk: str | None = None) -> Response:
        """İade dekontu için önerilen tutar (sevkiyatın sipariş fiyatından, KDV dahil)."""
        partner = self.get_partner()
        return_id = request.query_params.get("customer_return", "")
        if not return_id.isdigit():
            raise ValidationError({"customer_return": "İade seçin."})
        document = get_object_or_404(CustomerReturn, pk=int(return_id), customer=partner)
        data = {
            "customer_return": document.pk,
            "suggestion": selectors.return_credit_suggestion(document),
        }
        return Response(s.ReturnSuggestionSerializer(data, context=self._context()).data)


class SupplierLedgerViewSet(PartnerLedgerViewSet):
    """Tedarikçi carileri."""

    side = Side.SUPPLIER
    section = SUPPLIERS
    read_access = _read(SUPPLIERS)
    action_access = {
        "entries": _write(SUPPLIERS),
        "reverse": _write(SUPPLIERS),
        "statement_pdf": _read(SUPPLIERS) & HasAccess(PRICES, VIEW),
    }
