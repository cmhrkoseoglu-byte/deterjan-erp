from decimal import Decimal

import factory

from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, unit
from apps.recipes.models import Recipe, RecipeLine, RecipeStep, RecipeVersion


class RecipeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Recipe

    code = factory.Sequence(lambda n: f"REC{n:03d}")
    name = factory.Sequence(lambda n: f"Reçete {n}")
    product = factory.SubFactory(BulkMaterialFactory)


class RecipeVersionFactory(factory.django.DjangoModelFactory):
    """Taslak sürüm (durum yalnızca servisle değişir; onaylı sürüm için `approve_version`)."""

    class Meta:
        model = RecipeVersion

    recipe = factory.SubFactory(RecipeFactory)
    version_no = factory.Sequence(lambda n: n + 1)
    batch_size = Decimal("1000")
    batch_unit = factory.LazyFunction(lambda: unit("KG"))


class RecipeLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RecipeLine

    version = factory.SubFactory(RecipeVersionFactory)
    sequence = factory.Sequence(lambda n: n + 1)
    material = factory.SubFactory(MaterialFactory)
    quantity = Decimal("100")
    unit = factory.LazyFunction(lambda: unit("KG"))


class RecipeStepFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RecipeStep

    version = factory.SubFactory(RecipeVersionFactory)
    sequence = factory.Sequence(lambda n: n + 1)
    description = "Karıştır"
