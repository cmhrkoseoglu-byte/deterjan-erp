"""Personel API'si: yalnızca admin ve yönetim (kişisel veri, docs/KVKK.md). Silme yoktur; ayrılış
`terminate`, yeniden işe başlama `reinstate` ile kaydedilir, belge ve ücret `remove` ile
kaldırılır."""

from typing import Any

import django_filters
from django.db.models import QuerySet
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import User
from apps.core.permissions import HasRole
from apps.personnel import exports, pdf, selectors, services
from apps.personnel.api import serializers as s
from apps.personnel.models import (
    Employee,
    EmployeeDocument,
    EmployeeWage,
    PayrollParameterSet,
    PublicHoliday,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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

    @extend_schema(
        request=s.TerminateSerializer,
        responses={
            200: s.EmployeeSerializer,
            400: OpenApiResponse(
                description="attendance_after_exit; approved_attendance_after_exit "
                '(gövdede `months`, ör. "2026-09")'
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def terminate(self, request: Request, pk: str | None = None) -> Response:
        """İşten ayrılışı kaydeder: kart pasife alınır, çıkış tarihi yazılır. Çıkıştan sonra
        kayıtlı puantaj günleri `remove_attendance` ile kaldırılır (yoksa `attendance_after_exit`;
        onaylı aydaysa `approved_attendance_after_exit`)."""
        body = s.TerminateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            employee = services.terminate_employee(
                _user(request),
                self.get_object(),
                body.validated_data["termination_date"],
                note=body.validated_data["note"],
                remove_attendance=body.validated_data["remove_attendance"],
            )
        except services.ApprovedAttendanceAfterExit as exc:
            # Onaylı aylar ("2026-09") yanıta eklenir; pencere ilk aya bağlantı verir.
            return Response(
                {"code": exc.code, "detail": exc.message, "months": exc.months},
                status=status.HTTP_400_BAD_REQUEST,
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


class EmployeeDocumentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Özlük belgeleri: kimlik fotokopisi, bordro, sözleşme, diploma.

    Liste `?employee=<kart>` ister. Yükleme `multipart/form-data`. Dosya açık `/media` yolundan
    değil `download` ucundan verilir ve her açılış kartın geçmişine yazılır. Belge silinmez;
    `remove` ile kaldırılır, kaldırılan belge artık verilmez.
    """

    serializer_class = s.EmployeeDocumentSerializer
    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None
    queryset = EmployeeDocument.objects.filter(is_active=True).select_related(
        "employee", "created_by"
    )

    @extend_schema(parameters=[s.DocumentQuerySerializer])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Kartın belgeleri (kaldırılanlar hariç)."""
        query = s.DocumentQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        documents = selectors.employee_documents(query.validated_data["employee"])
        return Response(self.get_serializer(documents, many=True).data)

    @extend_schema(
        request={"multipart/form-data": s.DocumentUploadSerializer},
        responses={201: s.EmployeeDocumentSerializer},
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Karta belge ekler."""
        body = s.DocumentUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        document = services.add_document(_user(request), data.pop("employee"), **data)
        return Response(self.get_serializer(document).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.DocumentRemoveSerializer, responses=s.EmployeeDocumentSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, pk: str | None = None) -> Response:
        """Belgeyi kaldırır (neden zorunlu)."""
        body = s.DocumentRemoveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        document = services.remove_document(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return Response(self.get_serializer(document).data)

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def download(self, request: Request, pk: str | None = None) -> FileResponse:
        """Dosyayı tarayıcıda açar (`?download=1` indirir); açılış kartın geçmişine yazılır."""
        document = self.get_object()
        try:
            handle = document.file.open("rb")
        except FileNotFoundError:
            raise NotFound("Dosya bulunamadı.") from None
        services.record_document_access(_user(request), document)
        response = FileResponse(
            handle,
            as_attachment=request.query_params.get("download") == "1",
            filename=document.original_name,
            content_type=document.mime_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
        )
        # Ortak bilgisayarda tarayıcı önbelleğinde kalmasın.
        response["Cache-Control"] = "no-store"
        return response


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


# --- puantaj ------------------------------------------------------------------------------------


def _check_month(year: int, month: int) -> None:
    if not (1 <= month <= 12 and services.MIN_YEAR <= year <= services.MAX_YEAR):
        raise NotFound("Geçersiz ay.")


def _department(request: Request) -> str:
    return request.query_params.get("department", "").strip()


DEPARTMENT_PARAM = OpenApiParameter("department", str, required=False, description="Birim")


class AttendanceGridView(APIView):
    """Aylık puantaj tablosu: günler, kişiler, hücreler ve kişi başına toplamlar."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(parameters=[DEPARTMENT_PARAM], responses=s.AttendanceGridSerializer)
    def get(self, request: Request, year: int, month: int) -> Response:
        _check_month(year, month)
        grid = selectors.attendance_grid(year, month, department=_department(request))
        return Response(s.AttendanceGridSerializer(grid).data)


class AttendanceApproveView(APIView):
    """Ayı onaylar ve kilitler (ay bitmeden onaylanamaz)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(request=None, responses=s.AttendanceMonthSerializer)
    def post(self, request: Request, year: int, month: int) -> Response:
        _check_month(year, month)
        record = services.approve_attendance_month(_user(request), year, month)
        return Response(s.AttendanceMonthSerializer(record).data)


class AttendanceReopenView(APIView):
    """Onaylı ayı gerekçeyle yeniden açar."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(request=s.AttendanceReopenSerializer, responses=s.AttendanceMonthSerializer)
    def post(self, request: Request, year: int, month: int) -> Response:
        _check_month(year, month)
        record = selectors.month_record(year, month)
        if record is None:
            raise NotFound("Bu ayın puantajı yok.")
        body = s.AttendanceReopenSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        record = services.reopen_attendance_month(
            _user(request), record, body.validated_data["reason"]
        )
        return Response(s.AttendanceMonthSerializer(record).data)


class AttendanceExportView(APIView):
    """Aylık puantajın Excel çıktısı (tablo, fazla mesai, kodlar)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(parameters=[DEPARTMENT_PARAM], responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request, year: int, month: int) -> HttpResponse:
        _check_month(year, month)
        grid = selectors.attendance_grid(year, month, department=_department(request))
        response = HttpResponse(exports.attendance_xlsx(grid), content_type=XLSX)
        response["Content-Disposition"] = f'attachment; filename="puantaj-{year}-{month:02d}.xlsx"'
        return response


class AttendanceDayView(APIView):
    """Kişinin bir gününü yazar (durum, fazla mesai, not)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(request=s.AttendanceDayInputSerializer, responses=s.AttendanceEntrySerializer)
    def post(self, request: Request) -> Response:
        body = s.AttendanceDayInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        entry = services.set_attendance_day(
            _user(request),
            data["employee"],
            data["date"],
            status=data["status"],
            overtime_hours=data["overtime_hours"],
            note=data["note"],
            holiday_half_worked=data["holiday_half_worked"],
        )
        return Response(s.AttendanceEntrySerializer(entry).data)


class AttendanceRangeView(APIView):
    """Bir aralığa aynı durumu yazar (kişi, birim ya da herkes)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(request=s.AttendanceRangeSerializer, responses=s.AttendanceRangeResultSerializer)
    def post(self, request: Request) -> Response:
        body = s.AttendanceRangeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        updated = services.set_attendance_range(_user(request), **body.validated_data)
        return Response({"updated": updated})


class PublicHolidayViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Resmi tatil takvimi. Liste `?year=` (varsayılan bu yıl). Tatil silinmez; `remove` ile
    takvimden kaldırılır. `fixed` yılın sabit tatillerini ekler."""

    serializer_class = s.PublicHolidaySerializer
    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]
    pagination_class = None
    queryset = PublicHoliday.objects.filter(is_active=True)
    http_method_names = ["get", "post", "patch", "head", "options"]

    @extend_schema(parameters=[OpenApiParameter("year", int, required=False)])
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Yılın tatilleri (tarih sırasıyla)."""
        year_text = request.query_params.get("year", "")
        year = int(year_text) if year_text.isdigit() else timezone.localdate().year
        return Response(self.get_serializer(selectors.holidays_of_year(year), many=True).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Takvime tatil ekler."""
        body = s.PublicHolidaySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        holiday = services.add_holiday(_user(request), body.validated_data)
        return Response(self.get_serializer(holiday).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Tatilin adını, tarihini ya da yarım gün bilgisini değiştirir."""
        instance = self.get_object()
        body = s.PublicHolidaySerializer(instance, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        holiday = services.update_holiday(_user(request), instance, body.validated_data)
        return Response(self.get_serializer(holiday).data)

    @extend_schema(request=None, responses=s.PublicHolidaySerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, pk: str | None = None) -> Response:
        """Tatili takvimden kaldırır."""
        holiday = services.remove_holiday(_user(request), self.get_object())
        return Response(self.get_serializer(holiday).data)

    @extend_schema(
        request=s.FixedHolidaysSerializer, responses={201: s.PublicHolidaySerializer(many=True)}
    )
    @action(detail=False, methods=["post"])
    def fixed(self, request: Request) -> Response:
        """Yılın sabit resmi tatillerini ekler (zaten olanlar atlanır)."""
        body = s.FixedHolidaysSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        created = services.add_fixed_holidays(_user(request), body.validated_data["year"])
        return Response(
            self.get_serializer(created, many=True).data, status=status.HTTP_201_CREATED
        )


class AttendanceSettingsView(APIView):
    """Puantaj ayarları: varsayılan hafta tatili günleri."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(responses=s.AttendanceSettingsSerializer)
    def get(self, request: Request) -> Response:
        return Response(s.AttendanceSettingsSerializer(services.get_attendance_settings()).data)

    @extend_schema(request=s.AttendanceSettingsSerializer, responses=s.AttendanceSettingsSerializer)
    def patch(self, request: Request) -> Response:
        body = s.AttendanceSettingsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        instance = services.update_attendance_settings(
            _user(request), body.validated_data["rest_weekdays"]
        )
        return Response(s.AttendanceSettingsSerializer(instance).data)


# --- ücretler ------------------------------------------------------------------------------------


class EmployeeWageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Brüt aylık ücretler (geçerlilik tarihli). Silme ve düzeltme yok: zam yeni tarihle eklenir,
    yanlış kayıt `remove` ile gerekçeyle kaldırılır. `summary` çalışan personeli güncel ücretiyle
    verir."""

    serializer_class = s.EmployeeWageSerializer
    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]
    queryset = EmployeeWage.objects.select_related("employee", "created_by")
    filterset_fields = ["employee", "is_active"]
    ordering = ["employee", "-valid_from", "-id"]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Ücret girer (zam yeni geçerlilik tarihiyle)."""
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        wage = services.add_wage(_user(request), body.validated_data)
        return Response(self.get_serializer(wage).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.WageRemoveSerializer, responses=s.EmployeeWageSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, pk: str | None = None) -> Response:
        """Yanlış ücret kaydını kaldırır (neden zorunlu)."""
        body = s.WageRemoveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        reason = body.validated_data["reason"]
        wage = services.remove_wage(_user(request), self.get_object(), reason)
        return Response(self.get_serializer(wage).data)

    @extend_schema(
        parameters=[s.WageSummaryQuerySerializer], responses=s.WageSummarySerializer(many=True)
    )
    @action(detail=False, methods=["get"], pagination_class=None, filter_backends=[])
    def summary(self, request: Request) -> Response:
        """Çalışanlar (ayrılanlar isteğe bağlı), güncel ücretleri ve ücret geçmişleri."""
        query = s.WageSummaryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        rows = selectors.wage_summary(include_former=query.validated_data["include_former"])
        return Response(s.WageSummarySerializer(rows, many=True).data)


# --- ön bordro (docs/DECISIONS.md "Personel bordrosu") -------------------------------------------

PDF = "application/pdf"


def _private_file(
    content: bytes, content_type: str, filename: str, *, inline: bool
) -> HttpResponse:
    """Ücret içeren dosya: tarayıcı önbelleğine alınmaz, içerik türü tahmin edilmez."""
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(not inline, filename) or ""
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


def _payroll(request: Request, year: int, month: int) -> selectors.PayrollMonth:
    _check_month(year, month)
    return selectors.payroll_month(year, month, department=_department(request))


class PayrollMonthView(APIView):
    """Ayın ön bordrosu (canlı hesap): kişi satırları, toplamlar, parametreler ve uyarılar."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(parameters=[DEPARTMENT_PARAM], responses=s.PayrollMonthSerializer)
    def get(self, request: Request, year: int, month: int) -> Response:
        return Response(s.PayrollMonthSerializer(_payroll(request, year, month)).data)


class PayrollEmployerCostPdfView(APIView):
    """İşveren maliyeti tablosu (PDF, A4 yatay); açılış denetim günlüğüne yazılır."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(parameters=[DEPARTMENT_PARAM], responses={(200, PDF): OpenApiTypes.BINARY})
    def get(self, request: Request, year: int, month: int) -> HttpResponse:
        payroll = _payroll(request, year, month)
        content = pdf.employer_cost_pdf(payroll, draft=True)
        services.record_payroll_access(_user(request), year, month, "İşveren maliyeti (PDF)")
        return _private_file(content, PDF, f"isveren-maliyeti-{year}-{month:02d}.pdf", inline=True)


class PayrollExcelView(APIView):
    """Ön bordro Excel'i (işveren maliyeti, parametreler); açılış denetim günlüğüne yazılır."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(parameters=[DEPARTMENT_PARAM], responses={(200, XLSX): OpenApiTypes.BINARY})
    def get(self, request: Request, year: int, month: int) -> HttpResponse:
        payroll = _payroll(request, year, month)
        content = exports.payroll_xlsx(payroll, draft=True)
        services.record_payroll_access(_user(request), year, month, "Bordro (Excel)")
        return _private_file(content, XLSX, f"bordro-{year}-{month:02d}.xlsx", inline=False)


class ExternalPayrollView(APIView):
    """Bordrosu mali müşavirde olan kişinin ay rakamlarını yazar (brüt toplam, işverene maliyet)."""

    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]

    @extend_schema(request=s.ExternalFigureInputSerializer, responses=s.ExternalFigureSerializer)
    def post(self, request: Request, year: int, month: int) -> Response:
        _check_month(year, month)
        body = s.ExternalFigureInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        figure = services.set_external_payroll(
            _user(request),
            data["employee"],
            year,
            month,
            gross_total=data["gross_total"],
            employer_cost=data["employer_cost"],
            note=data["note"],
        )
        return Response(s.ExternalFigureSerializer(figure).data)


class PayrollParameterSetViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Bordro parametre setleri (kaldırılanlar hariç, en yenisi önce). Silinmez; yanlış set `remove`
    ile gerekçeyle kaldırılır. `defaults?year=` yılın yasal değerlerini verir (formu doldurmak
    için)."""

    serializer_class = s.PayrollParameterSetSerializer
    permission_classes = [HasRole(*services.PERSONNEL_ROLES)]
    pagination_class = None
    queryset = PayrollParameterSet.objects.filter(is_active=True).select_related("updated_by")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[PayrollParameterSet]:
        return selectors.parameter_sets().select_related("updated_by")

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Parametre seti açar."""
        body = self.get_serializer(data=request.data)
        body.is_valid(raise_exception=True)
        instance = services.create_parameter_set(_user(request), _parameter_values(body))
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Parametre setini düzeltir (yalnızca gönderilen değerler)."""
        instance = self.get_object()
        body = self.get_serializer(instance, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        instance = services.update_parameter_set(_user(request), instance, _parameter_values(body))
        return Response(self.get_serializer(instance).data)

    @extend_schema(request=s.ReasonSerializer, responses=s.PayrollParameterSetSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request: Request, pk: str | None = None) -> Response:
        """Parametre setini kaldırır (neden zorunlu)."""
        body = s.ReasonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        instance = services.remove_parameter_set(
            _user(request), self.get_object(), body.validated_data["reason"]
        )
        return Response(self.get_serializer(instance).data)

    @extend_schema(
        parameters=[s.ParameterDefaultsQuerySerializer], responses=s.ParameterDefaultsSerializer
    )
    @action(detail=False, methods=["get"])
    def defaults(self, request: Request) -> Response:
        """Yılın yasal değerleri ve kaynakları."""
        query = s.ParameterDefaultsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = s.defaults_data(query.validated_data["year"])
        return Response(s.ParameterDefaultsSerializer(data).data)


def _parameter_values(body: serializers.BaseSerializer) -> dict[str, Any]:
    """Formdan gelen değerler (salt okunur alanlar hariç)."""
    allowed = {"valid_from", *s.PARAMETER_VALUE_FIELDS, "source", "note"}
    return {key: value for key, value in body.validated_data.items() if key in allowed}
