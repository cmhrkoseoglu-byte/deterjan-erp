"""Personel testleri için yardımcılar (kartlar servislerle açılır)."""

from typing import Any

from apps.core.models import User
from apps.personnel import services
from apps.personnel.models import Employee


def employee(actor: User, **overrides: Any) -> Employee:
    """Varsayılan: dolum biriminde, sistemi kullanmayan bir operatör."""
    data = {
        "full_name": "Ayşe Demir",
        "department": "Dolum",
        "title": "Dolum operatörü",
        **overrides,
    }
    return services.create_employee(actor, data)
