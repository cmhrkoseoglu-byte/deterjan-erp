"""Cari hesaplar için ana veri alanları: malzemenin KDV oranı, carinin vade günü ve KDV muafı
(docs/plan/cari-hesaplar.md §2.2)."""

import io
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.models import AuditLog
from apps.masterdata.models import Customer, Material, Supplier
from apps.masterdata.tests.factories import CustomerFactory, MaterialFactory, unit

pytestmark = pytest.mark.django_db


def test_material_vat_rate_defaults_to_20(client_for):
    response = client_for("planlama").post(
        reverse("masterdata:material-list"),
        {"code": "HM-1", "name": "LAS", "material_type": "RAW", "base_unit": unit("KG").pk},
        format="json",
    )

    assert response.status_code == 201, response.json()
    assert response.json()["vat_rate"] == "20.00"
    assert Material.objects.get().vat_rate == Decimal("20")


@pytest.mark.parametrize("rate", ["0", "1", "10", "20"])
def test_material_accepts_turkish_vat_rates(client_for, rate):
    material = MaterialFactory()

    response = client_for("planlama").patch(
        reverse("masterdata:material-detail", args=[material.pk]), {"vat_rate": rate}
    )

    assert response.status_code == 200, response.json()
    material.refresh_from_db()
    assert material.vat_rate == Decimal(rate)


def test_material_rejects_other_vat_rate(client_for):
    material = MaterialFactory()

    response = client_for("planlama").patch(
        reverse("masterdata:material-detail", args=[material.pk]), {"vat_rate": "18"}
    )

    assert response.status_code == 400
    assert "KDV oranı 0, 1, 10 ya da 20" in str(response.json())
    material.refresh_from_db()
    assert material.vat_rate == Decimal("20")


def test_partner_payment_term_and_vat_exempt_are_saved_and_audited(client_for):
    customer = CustomerFactory()

    response = client_for("planlama").patch(
        reverse("masterdata:customer-detail", args=[customer.pk]),
        {"payment_term_days": 45, "vat_exempt": True},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["payment_term_days"] == 45
    assert response.json()["vat_exempt"] is True
    customer.refresh_from_db()
    assert (customer.payment_term_days, customer.vat_exempt) == (45, True)
    log = AuditLog.objects.filter(object_id=str(customer.pk), action="update").latest("id")
    assert "payment_term_days" in log.changes and "vat_exempt" in log.changes


def test_new_partner_is_cash_and_not_vat_exempt(client_for):
    response = client_for("planlama").post(
        reverse("masterdata:supplier-list"), {"code": "T-1", "name": "A Kimya"}
    )

    assert response.status_code == 201, response.json()
    assert response.json()["payment_term_days"] is None
    assert response.json()["vat_exempt"] is False


def test_import_reads_ledger_columns(client_for):
    upload = io.BytesIO("Kod,Ünvan,Vade (gün),KDV muaf\nM1,Müşteri,30,Evet\n".encode())
    upload.name = "m.csv"

    response = client_for("planlama").post(
        reverse("masterdata:import", args=["customers"]),
        {"file": upload, "confirm": "true"},
        format="multipart",
    )

    assert response.status_code == 200, response.json()
    customer = Customer.objects.get(code="M1")
    assert (customer.payment_term_days, customer.vat_exempt) == (30, True)
    assert not Supplier.objects.exists()


def test_import_reads_material_vat_rate(client_for):
    upload = io.BytesIO("Kod,Ad,Tür,Temel birim,KDV oranı (%)\nHM-1,LAS,Hammadde,KG,10\n".encode())
    upload.name = "m.csv"

    response = client_for("planlama").post(
        reverse("masterdata:import", args=["materials"]),
        {"file": upload, "confirm": "true"},
        format="multipart",
    )

    assert response.status_code == 200, response.json()
    assert Material.objects.get(code="HM-1").vat_rate == Decimal("10")
