import factory

from apps.core.tests.testapp.models import Widget


class WidgetFactory(factory.django.DjangoModelFactory):
    """Olaylardaki "kayıt" yerine geçen test modeli (lot, üretim emri vb. henüz yok)."""

    class Meta:
        model = Widget

    name = factory.Sequence(lambda n: f"Kayıt {n}")


def ref(obj, **extra):
    """Olay payload'ındaki kayıt sözlüğü: {"model", "id", ...}."""
    return {"model": obj._meta.label_lower, "id": obj.pk, **extra}
