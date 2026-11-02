"""Personel testleri için yardımcılar (kartlar, belgeler ve bordro parametreleri servislerle
açılır)."""

from datetime import date
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import User
from apps.personnel import payroll, services
from apps.personnel.models import Employee, EmployeeDocument, PayrollParameterSet

PDF = b"%PDF-1.4\n" + b"0" * 64


def employee(actor: User, **overrides: Any) -> Employee:
    """Varsayılan: dolum biriminde, sistemi kullanmayan bir operatör."""
    data = {
        "full_name": "Ayşe Demir",
        "department": "Dolum",
        "title": "Dolum operatörü",
        **overrides,
    }
    return services.create_employee(actor, data)


def pdf(name: str = "belge.pdf", content: bytes = PDF) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def document(
    actor: User, card: Employee, kind: str = EmployeeDocument.Kind.DIPLOMA, **overrides: Any
) -> EmployeeDocument:
    """Varsayılan: PDF diploma."""
    data = {"file": pdf(), **overrides}
    return services.add_document(actor, card, kind=kind, **data)


def parameter_values(year: int = 2026, **overrides: Any) -> dict[str, Any]:
    """Yılın yasal değerleri, parametre seti alanları olarak (Ocak'tan geçerli)."""
    legal = payroll.LEGAL_DEFAULTS[year]
    values: dict[str, Any] = {
        "valid_from": date(year, 1, 1),
        "minimum_wage": legal.minimum_wage,
        "ceiling_multiplier": legal.ceiling_multiplier,
        "employee_sgk_rate": legal.employee_sgk_rate,
        "employee_unemployment_rate": legal.employee_unemployment_rate,
        "employer_sgk_rate": legal.employer_sgk_rate,
        "employer_unemployment_rate": legal.employer_unemployment_rate,
        "incentive_points": legal.incentive_points,
        "stamp_tax_per_mille": legal.stamp_tax_per_mille,
        "bes_rate": legal.bes_rate,
        "source": "Test",
        "note": "",
    }
    for index, limit in enumerate(legal.tax_brackets, start=1):
        values[f"tax_bracket_{index}"] = limit
    for index, rate in enumerate(legal.tax_rates, start=1):
        values[f"tax_rate_{index}"] = rate
    return {**values, **overrides}


def parameter_set(actor: User, year: int = 2026, **overrides: Any) -> PayrollParameterSet:
    """Yılın yasal değerleriyle kayıtlı parametre seti (değerler değiştirilebilir)."""
    return services.create_parameter_set(actor, parameter_values(year, **overrides))
