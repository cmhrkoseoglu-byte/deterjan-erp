"""Etiket uç noktaları için ortak yardımcılar: çıktı biçimi (PDF / A4 PDF / ZPL), kopya sayısı
ve yazıcıya gönderim isteği."""

from collections.abc import Sequence

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers

from apps.core.labels import DEFAULT_DPI, Label, render_pdf, render_zpl

PDF = "application/pdf"
ZPL = "text/plain"
MAX_COPIES = 100
OUTPUTS = (("pdf", "PDF (etiket boyutu)"), ("a4", "PDF (A4)"), ("zpl", "ZPL (Zebra)"))


class LabelOutputSerializer(serializers.Serializer):
    output = serializers.ChoiceField(choices=OUTPUTS, default="pdf", label="çıktı")
    copies = serializers.IntegerField(min_value=1, max_value=MAX_COPIES, default=1, label="kopya")


class PrintRequestSerializer(serializers.Serializer):
    printer = serializers.IntegerField(label="yazıcı")
    copies = serializers.IntegerField(min_value=1, max_value=MAX_COPIES, default=1, label="kopya")


class PrintResultSerializer(serializers.Serializer):
    printed = serializers.IntegerField()
    printer = serializers.CharField()


LABEL_PARAMETERS = [
    OpenApiParameter("output", OpenApiTypes.STR, enum=[key for key, _ in OUTPUTS]),
    OpenApiParameter("copies", OpenApiTypes.INT),
]


def label_response(
    labels: Sequence[Label], output: str, filename: str, *, dpi: int = DEFAULT_DPI
) -> HttpResponse:
    """Etiketleri istenen biçimde yanıt olarak döner (`filename` uzantısız)."""
    if output == "zpl":
        response = HttpResponse(render_zpl(labels, dpi=dpi), content_type=f"{ZPL}; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}.zpl"'
        return response
    response = HttpResponse(render_pdf(labels, a4=output == "a4"), content_type=PDF)
    response["Content-Disposition"] = f'inline; filename="{filename}.pdf"'
    return response
