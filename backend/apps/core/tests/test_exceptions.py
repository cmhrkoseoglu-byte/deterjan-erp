import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import OperationalError
from django.http import Http404
from rest_framework import exceptions, serializers
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.exceptions import BUSY_DETAIL, BusinessRuleError


def respond(exc):
    class FailingView(APIView):
        authentication_classes: list = []
        permission_classes: list = []

        def get(self, request):
            raise exc

    return FailingView.as_view()(APIRequestFactory().get("/x/"))


def test_business_rule_error_is_400_with_code_and_detail():
    response = respond(BusinessRuleError("negative_stock", "Stok eksiye düşemez."))

    assert response.status_code == 400
    assert response.data == {"code": "negative_stock", "detail": "Stok eksiye düşemez."}


def test_serializer_validation_error_has_field_errors():
    response = respond(serializers.ValidationError({"quantity": ["Pozitif olmalı."]}))

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert response.data["detail"]
    assert response.data["errors"] == {"quantity": ["Pozitif olmalı."]}


def test_non_field_validation_error():
    response = respond(serializers.ValidationError("Genel hata."))

    assert response.data["errors"] == {"non_field_errors": ["Genel hata."]}


def test_django_validation_error_converted():
    response = respond(DjangoValidationError({"name": "Zorunlu."}))

    assert response.status_code == 400
    assert response.data["errors"] == {"name": ["Zorunlu."]}


def test_not_found_has_code():
    response = respond(Http404())

    assert response.status_code == 404
    assert response.data["code"] == "not_found"
    assert response.data["detail"]


def test_permission_denied_keeps_service_message():
    message = "Kod oluşturulduktan sonra yalnızca sistem yöneticisi değiştirebilir."
    response = respond(DjangoPermissionDenied(message))

    assert response.status_code == 403
    assert response.data == {"code": "permission_denied", "detail": message}


@pytest.mark.parametrize("exc", [DjangoPermissionDenied(), DjangoPermissionDenied("  ")])
def test_permission_denied_without_message_has_generic_detail(exc):
    response = respond(exc)

    assert response.status_code == 403
    assert response.data == {
        "code": "permission_denied",
        "detail": str(exceptions.PermissionDenied.default_detail),
    }


@pytest.mark.parametrize("exc", [ValueError("hata")])
def test_unexpected_errors_are_not_swallowed(exc):
    with pytest.raises(ValueError):
        respond(exc)


class _Cause(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> OperationalError:
    try:
        raise OperationalError("kilit") from _Cause(sqlstate)
    except OperationalError as exc:
        return exc


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01"])
def test_lock_conflicts_are_400_busy(sqlstate):
    """Kilit bekleme süresi dolması ve kilitlenme sunucu hatası değil: kullanıcı yeniden dener."""
    response = respond(_db_error(sqlstate))

    assert response.status_code == 400
    assert response.data == {"code": "busy", "detail": BUSY_DETAIL}


def test_other_database_errors_are_not_swallowed():
    with pytest.raises(OperationalError):
        respond(_db_error("08006"))
