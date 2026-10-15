import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.exceptions import BusinessRuleError


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


@pytest.mark.parametrize("exc", [ValueError("hata")])
def test_unexpected_errors_are_not_swallowed(exc):
    with pytest.raises(ValueError):
        respond(exc)
