from decimal import Decimal

import factory

from apps.masterdata.models import (
    Customer,
    Equipment,
    Location,
    Material,
    MaterialCategory,
    MaterialUnitConversion,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)


def unit(code: str) -> UnitOfMeasure:
    """Migration ile yüklenen standart birim (KG, G, LT, ML, ADET, KOLI, PALET)."""
    return UnitOfMeasure.objects.get(code=code)


class MaterialCategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MaterialCategory

    code = factory.Sequence(lambda n: f"KAT{n}")
    name = factory.Sequence(lambda n: f"Kategori {n}")


class MaterialFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Material

    code = factory.Sequence(lambda n: f"HM{n:04d}")
    name = factory.Sequence(lambda n: f"Hammadde {n}")
    material_type = Material.Type.RAW
    base_unit = factory.LazyFunction(lambda: unit("KG"))


class BulkMaterialFactory(MaterialFactory):
    code = factory.Sequence(lambda n: f"YM{n:04d}")
    name = factory.Sequence(lambda n: f"Dökme ürün {n}")
    material_type = Material.Type.BULK
    density = Decimal("1.0500")


class MaterialUnitConversionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MaterialUnitConversion

    material = factory.SubFactory(
        MaterialFactory,
        material_type=Material.Type.PACKAGING,
        base_unit=factory.LazyFunction(lambda: unit("ADET")),
    )
    unit = factory.LazyFunction(lambda: unit("KOLI"))
    factor_to_base = Decimal("12")


class WarehouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Warehouse

    code = factory.Sequence(lambda n: f"D{n}")
    name = factory.Sequence(lambda n: f"Depo {n}")


class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    warehouse = factory.SubFactory(WarehouseFactory)
    code = factory.Sequence(lambda n: f"L{n:03d}")
    name = factory.Sequence(lambda n: f"Lokasyon {n}")
    location_type = Location.Type.STORAGE


class EquipmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Equipment

    code = factory.Sequence(lambda n: f"TK{n:02d}")
    name = factory.Sequence(lambda n: f"Karıştırma tankı {n}")
    equipment_type = Equipment.Type.MIXING_TANK
    capacity = Decimal("5000")
    capacity_unit = factory.LazyFunction(lambda: unit("KG"))
    location = factory.SubFactory(LocationFactory, location_type=Location.Type.TANK)


class SupplierFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Supplier

    code = factory.Sequence(lambda n: f"T{n:03d}")
    name = factory.Sequence(lambda n: f"Tedarikçi {n} A.Ş.")


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer

    code = factory.Sequence(lambda n: f"M{n:03d}")
    name = factory.Sequence(lambda n: f"Müşteri {n} Ltd.")
