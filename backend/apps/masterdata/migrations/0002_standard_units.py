from decimal import Decimal

from django.db import migrations

# Standart birimler: kod, ad, tür, tür temel birimine katsayı (None: yalnızca malzemeye özel
# dönüşümle çevrilir, ör. 1 KOLI = 12 ADET).
UNITS = [
    ("KG", "Kilogram", "MASS", Decimal("1")),
    ("G", "Gram", "MASS", Decimal("0.001")),
    ("LT", "Litre", "VOLUME", Decimal("1")),
    ("ML", "Mililitre", "VOLUME", Decimal("0.001")),
    ("ADET", "Adet", "COUNT", Decimal("1")),
    ("KOLI", "Koli", "COUNT", None),
    ("PALET", "Palet", "COUNT", None),
]


def create_units(apps, schema_editor):
    UnitOfMeasure = apps.get_model("masterdata", "UnitOfMeasure")
    for code, name, kind, factor in UNITS:
        UnitOfMeasure.objects.get_or_create(
            code=code, defaults={"name": name, "kind": kind, "factor_to_kind_base": factor}
        )


class Migration(migrations.Migration):
    dependencies = [("masterdata", "0001_initial")]

    operations = [migrations.RunPython(create_units, migrations.RunPython.noop)]
