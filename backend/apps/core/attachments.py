"""Dosya eki eklenebilen kayıt türlerinin kaydı.

Her modül kendi `AppConfig.ready()` içinde ek alabilen modellerini kaydeder:

    register_attachment_target("inventory.lot")
    register_attachment_target("workflow.comment", can_add=lambda user, comment: ...)

`can_add` verilmezse giriş yapmış her kullanıcı ek ekleyebilir.
"""

from collections.abc import Callable
from typing import Any

from apps.core.models import User

CanAdd = Callable[[User, Any], bool]

_TARGETS: dict[str, CanAdd | None] = {}

# İzinli dosya uzantıları (küçük harf) ve en büyük boyut (ayarlarda değiştirilebilir).
ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".heic",
        ".gif",
        ".xlsx",
        ".xls",
        ".docx",
        ".doc",
        ".csv",
        ".txt",
    }
)
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
# Tarayıcıda açılarak gösterilebilecek türler; diğerleri indirilir.
INLINE_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"})


def register_attachment_target(label: str, *, can_add: CanAdd | None = None) -> None:
    """`"app_label.model"` türündeki kayıtlara ek eklenebilmesini sağlar."""
    _TARGETS[label.lower()] = can_add


def is_attachment_target(label: str) -> bool:
    return label.lower() in _TARGETS


def can_add_attachment(user: User, label: str, target: Any) -> bool:
    check = _TARGETS.get(label.lower())
    return check is None or user.is_admin or check(user, target)


def attachment_targets() -> list[str]:
    return sorted(_TARGETS)
