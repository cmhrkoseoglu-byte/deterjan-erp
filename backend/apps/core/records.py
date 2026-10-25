"""Kayda bağlı genel uç noktaların (yorum, değişiklik geçmişi, dosya eki) erişim kuralı.

Bu uç noktalar kayıt türünü parametre olarak alır (`?content_type=inventory.lot&object_id=5`), bu
yüzden kaydın kendi ekranındaki okuma kuralını kendileri bilemez. Her modül, yorum, geçmiş ya da ek
açılabilen kayıt türlerini `AppConfig.ready()` içinde kendi ekranındaki okuma kuralıyla kaydeder:

    register_record_type("inventory.lot", hidden_fields=lot_cost_fields)
    register_record_type("sales.salesorder", roles=READ_ROLES)
    register_record_type("hse.incident", visible=incidents_visible_to)

- `roles`: kaydı okuyabilen roller (admin her zaman); boşsa giriş yapmış herkes.
- `visible(user, queryset)`: kayıt bazlı süzgeç (ör. olayı yalnızca bildiren ve yönetim görür).
- `hidden_fields(user)`: geçmişte bu kullanıcıya gösterilmeyen alanlar (ör. maliyet, fiyat); kaydın
  kendi ekranı da bu alanları o kullanıcıya göstermez.
- `parent(obj)`: erişimi başka bir kayda bağlı tür (yorumun eki → yorumun kaydı).
- `commentable`: yorum ve geçmiş paneli açılabilir mi (yorumun kendisi için hayır; yalnızca ek).

Kayıtlı olmayan tür bu uç noktalarda kabul edilmez (kapalı varsayılan). Göremeyen kullanıcıya kayıt
yokmuş gibi yanıt verilir; böylece kaydın varlığı da sızmaz.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import QuerySet

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.permissions import user_has_role

Visible = Callable[[User, QuerySet[Any]], QuerySet[Any]]
HiddenFields = Callable[[User], Collection[str]]
Parent = Callable[[Any], models.Model | None]


@dataclass(frozen=True)
class RecordAccess:
    roles: tuple[str, ...] = ()
    visible: Visible | None = None
    hidden_fields: HiddenFields | None = None
    parent: Parent | None = None
    commentable: bool = True


_REGISTRY: dict[str, RecordAccess] = {}


def register_record_type(
    label: str,
    *,
    roles: Collection[str] = (),
    visible: Visible | None = None,
    hidden_fields: HiddenFields | None = None,
    parent: Parent | None = None,
    commentable: bool = True,
) -> None:
    """`"app_label.model"` türünü okuma kuralıyla kaydeder (modülün `AppConfig.ready()`'sinde)."""
    _REGISTRY[label.lower()] = RecordAccess(
        roles=tuple(roles),
        visible=visible,
        hidden_fields=hidden_fields,
        parent=parent,
        commentable=commentable,
    )


def record_access(label: str) -> RecordAccess | None:
    return _REGISTRY.get((label or "").strip().lower())


def registered_record_types(*, commentable: bool | None = None) -> list[str]:
    """Kayıtlı türler; `commentable` verilirse yalnızca yorum/geçmiş paneli açılabilenler ya da
    açılamayanlar."""
    return sorted(
        label
        for label, access in _REGISTRY.items()
        if commentable is None or access.commentable == commentable
    )


def _label(obj: models.Model) -> str:
    return obj._meta.label_lower


def can_view(user: Any, obj: models.Model | None) -> bool:
    """Kullanıcı bu kaydı kendi ekranında görebilir mi (kayıtlı olmayan tür: hayır)."""
    if obj is None or not isinstance(user, User) or not user.is_authenticated:
        return False
    if not user.is_active:
        return False
    access = _REGISTRY.get(_label(obj))
    if access is None:
        return False
    if access.roles and not user_has_role(user, access.roles):
        return False
    if access.visible is not None:
        queryset = type(obj)._base_manager.filter(pk=obj.pk)
        if not access.visible(user, queryset).exists():
            return False
    if access.parent is not None:
        return can_view(user, access.parent(obj))
    return True


def content_type_for(label: str, *, commentable: bool = False) -> ContentType:
    """Kayıtlı tür → ContentType. Kayıtlı değilse (ya da `commentable` istenip yorum paneli
    açılamıyorsa) `BusinessRuleError("invalid_record_type")`."""
    label = (label or "").strip().lower()
    access = _REGISTRY.get(label)
    if access is None or (commentable and not access.commentable):
        raise BusinessRuleError("invalid_record_type", "Geçersiz kayıt türü.")
    app_label, _, model = label.partition(".")
    try:
        return ContentType.objects.get_by_natural_key(app_label, model)
    except ContentType.DoesNotExist:
        raise BusinessRuleError("invalid_record_type", "Geçersiz kayıt türü.") from None


def visible_record(
    user: Any, content_type: ContentType, object_id: int, *, message: str = "Kayıt bulunamadı."
) -> models.Model:
    """Kullanıcının görebildiği kayıt. Kayıt yoksa ya da kullanıcı göremiyorsa ikisi de aynı
    `BusinessRuleError("record_not_found")` olur (kaydın varlığı sızmaz)."""
    model_class = content_type.model_class()
    target = model_class._base_manager.filter(pk=object_id).first() if model_class else None
    if target is None or not can_view(user, target):
        raise BusinessRuleError("record_not_found", message)
    return target


def hidden_fields_for(user: Any, label: str) -> frozenset[str]:
    """Bu türün geçmişinde kullanıcıya gösterilmeyecek alanlar."""
    access = _REGISTRY.get((label or "").strip().lower())
    if access is None or access.hidden_fields is None:
        return frozenset()
    return frozenset(access.hidden_fields(user))
