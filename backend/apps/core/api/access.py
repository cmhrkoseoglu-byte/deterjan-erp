"""Yetki kataloğu API'si (docs/plan/kisi-yetkileri.md §5.1)."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import access
from apps.core.permissions import SignedIn
from apps.core.roles import ROLE_LABELS


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
                "holders": {
                    **access.HOLDER_LABELS,
                    **{role: ROLE_LABELS[role] for role in access.ROLES},
                },
                **access.catalog(),
            }
        )
