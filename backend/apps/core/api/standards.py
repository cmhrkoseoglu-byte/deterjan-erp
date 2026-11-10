"""Uluslararası standart kod listeleri (`/api/v1/standards/`): ön yüz ülke ve dil seçimlerini
buradan kurar, adları tarayıcının Türkçe adlarıyla gösterir."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import standards


class StandardsSerializer(serializers.Serializer):
    countries = serializers.ListField(child=serializers.CharField())
    languages = serializers.ListField(child=serializers.CharField())
    default_country = serializers.CharField()
    default_language = serializers.CharField()


class StandardsView(APIView):
    """Ülke (ISO 3166-1 alpha-2) ve dil (ISO 639-1) kodları; giriş yapmış herkes okur."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=StandardsSerializer)
    def get(self, request: Request) -> Response:
        return Response(
            StandardsSerializer(
                {
                    "countries": list(standards.COUNTRY_CODES),
                    "languages": list(standards.LANGUAGE_CODES),
                    "default_country": standards.DEFAULT_COUNTRY,
                    "default_language": standards.DEFAULT_LANGUAGE,
                }
            ).data
        )
