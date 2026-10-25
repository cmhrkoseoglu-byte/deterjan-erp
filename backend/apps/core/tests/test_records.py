"""Kayda bağlı genel uç noktaların erişim kuralı (`core.records`)."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from apps.core import records
from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.permissions import user_has_role
from apps.core.tests.testapp.models import Widget

pytestmark = pytest.mark.django_db
WIDGET = "core_testapp.widget"


@pytest.fixture
def registry() -> Iterator[dict[str, records.RecordAccess]]:
    """Testte değişen kaydı geri alır (kayıt defteri uygulama genelidir)."""
    saved = dict(records._REGISTRY)
    yield records._REGISTRY
    records._REGISTRY.clear()
    records._REGISTRY.update(saved)


def _widget(**kwargs: Any) -> Widget:
    return Widget.objects.create(name=kwargs.pop("name", "A"), **kwargs)


def test_unregistered_type_is_rejected(registry: dict[str, Any]) -> None:
    with pytest.raises(BusinessRuleError) as exc:
        records.content_type_for("masterdata.material")
    assert exc.value.code == "invalid_record_type"
    assert records.content_type_for(WIDGET).model == "widget"
    del registry[WIDGET]
    with pytest.raises(BusinessRuleError):
        records.content_type_for(WIDGET)
    assert not records.can_view(None, _widget())


def test_roles_filter_and_hidden_fields(
    registry: dict[str, Any], make_user: Callable[..., User]
) -> None:
    owner, other = make_user("depo"), make_user("depo")
    manager, outsider, admin = make_user("yonetim"), make_user("sevkiyat"), make_user("admin")
    records.register_record_type(
        WIDGET,
        roles=("depo", "yonetim"),
        visible=lambda user, qs: qs if user_has_role(user, ("yonetim",)) else qs.filter(owner=user),
        hidden_fields=lambda user: set() if user_has_role(user, ("yonetim",)) else {"quantity"},
    )
    widget = _widget(owner=owner)
    assert records.can_view(owner, widget)
    assert records.can_view(manager, widget) and records.can_view(admin, widget)
    assert not records.can_view(other, widget)  # rolü var ama kayıt başkasının
    assert not records.can_view(outsider, widget)  # rolü yok
    owner.is_active = False
    assert not records.can_view(owner, widget)
    assert records.hidden_fields_for(other, WIDGET) == {"quantity"}
    assert records.hidden_fields_for(manager, WIDGET) == set()
    assert records.hidden_fields_for(manager, "masterdata.material") == set()


def test_missing_and_invisible_records_look_the_same(
    registry: dict[str, Any], make_user: Callable[..., User]
) -> None:
    records.register_record_type(WIDGET, roles=("yonetim",))
    content_type = records.content_type_for(WIDGET)
    widget = _widget()
    assert records.visible_record(make_user("yonetim"), content_type, widget.pk) == widget
    for user, object_id in ((make_user("depo"), widget.pk), (make_user("yonetim"), 999999)):
        with pytest.raises(BusinessRuleError) as exc:
            records.visible_record(user, content_type, object_id)
        assert exc.value.code == "record_not_found"


def test_attachment_only_types_are_not_commentable(registry: dict[str, Any]) -> None:
    records.register_record_type("core_testapp.sampledocument", commentable=False)
    assert "core_testapp.sampledocument" in records.registered_record_types(commentable=False)
    assert WIDGET in records.registered_record_types(commentable=True)
    with pytest.raises(BusinessRuleError):
        records.content_type_for("core_testapp.sampledocument", commentable=True)
    assert records.content_type_for("core_testapp.sampledocument").model == "sampledocument"
