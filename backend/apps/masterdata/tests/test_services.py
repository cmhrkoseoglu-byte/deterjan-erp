from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.masterdata import services
from apps.masterdata.models import Equipment, Location, Material, UnitOfMeasure
from apps.masterdata.tests.factories import (
    BulkMaterialFactory,
    EquipmentFactory,
    LocationFactory,
    MaterialCategoryFactory,
    MaterialFactory,
    MaterialUnitConversionFactory,
    WarehouseFactory,
    unit,
)

pytestmark = pytest.mark.django_db


# --- standart birimler -----------------------------------------------------------------------


def test_standard_units_are_loaded_by_migration():
    codes = set(UnitOfMeasure.objects.values_list("code", flat=True))

    assert {"KG", "G", "LT", "ML", "ADET", "KOLI", "PALET"} <= codes
    assert unit("G").factor_to_kind_base == Decimal("0.001")
    assert unit("KOLI").factor_to_kind_base is None


# --- convert_quantity ------------------------------------------------------------------------


def test_convert_same_unit_returns_quantity():
    material = MaterialFactory()

    assert services.convert_quantity(material, Decimal("5"), unit("KG"), unit("KG")) == 5


def test_convert_within_kind_uses_factors():
    material = MaterialFactory()  # temel birim KG

    assert services.convert_quantity(material, Decimal("2500"), unit("G"), unit("KG")) == Decimal(
        "2.5"
    )
    assert services.convert_quantity(material, Decimal("1.2"), unit("KG"), unit("G")) == Decimal(
        "1200"
    )


def test_convert_mass_to_volume_uses_density():
    material = MaterialFactory(density=Decimal("1.25"))  # 1 LT = 1.25 KG

    assert services.convert_quantity(material, Decimal("10"), unit("LT"), unit("KG")) == Decimal(
        "12.5"
    )
    assert services.convert_quantity(material, Decimal("5"), unit("KG"), unit("LT")) == Decimal("4")
    assert services.convert_quantity(material, Decimal("500"), unit("ML"), unit("G")) == Decimal(
        "625"
    )


def test_convert_volume_based_material_from_kg():
    material = MaterialFactory(base_unit=unit("LT"), density=Decimal("0.8"))

    assert services.to_base_quantity(material, Decimal("8"), unit("KG")) == Decimal("10")


def test_convert_mass_to_volume_without_density_is_rejected():
    material = MaterialFactory(density=None)

    with pytest.raises(BusinessRuleError) as exc:
        services.convert_quantity(material, Decimal("1"), unit("LT"), unit("KG"))
    assert exc.value.code == "no_conversion"


def test_convert_uses_material_specific_conversion():
    conversion = MaterialUnitConversionFactory(factor_to_base=Decimal("12"))  # 1 KOLI = 12 ADET
    material = conversion.material

    assert services.to_base_quantity(material, Decimal("3"), unit("KOLI")) == Decimal("36")
    assert services.convert_quantity(
        material, Decimal("30"), unit("ADET"), unit("KOLI")
    ) == Decimal("2.5")


def test_package_unit_without_material_conversion_is_rejected():
    material = MaterialFactory(material_type=Material.Type.PACKAGING, base_unit=unit("ADET"))

    with pytest.raises(BusinessRuleError) as exc:
        services.to_base_quantity(material, Decimal("1"), unit("KOLI"))
    assert exc.value.code == "no_conversion"


def test_inactive_material_conversion_is_ignored():
    conversion = MaterialUnitConversionFactory(is_active=False)

    with pytest.raises(BusinessRuleError):
        services.to_base_quantity(conversion.material, Decimal("1"), unit("KOLI"))


def test_convert_rejects_float():
    with pytest.raises(TypeError):
        services.convert_quantity(MaterialFactory(), 1.5, unit("KG"), unit("G"))  # type: ignore[arg-type]


# --- oluştur / güncelle / pasifleştir --------------------------------------------------------


def test_create_record_uppercases_code_and_audits(make_user):
    user = make_user("planlama")

    material = services.create_record(
        user,
        Material,
        {
            "code": "  hm-sles ",
            "name": "SLES",
            "material_type": Material.Type.RAW,
            "base_unit": unit("KG"),
        },
    )

    assert material.code == "HM-SLES"
    assert material.created_by == user
    entry = AuditLog.objects.get(action=AuditLog.Action.CREATE, object_id=material.pk)
    assert entry.changes["code"] == [None, "HM-SLES"]


def test_create_record_rejects_duplicate_code_case_insensitively(make_user):
    MaterialFactory(code="HM-LAS")

    with pytest.raises(ValidationError) as exc:
        services.create_record(
            make_user("planlama"),
            Material,
            {"code": "hm-las", "name": "x", "material_type": "RAW", "base_unit": unit("KG")},
        )
    assert "code" in exc.value.message_dict


def test_create_record_rejects_invalid_choice_and_negative_density(make_user):
    with pytest.raises(ValidationError) as exc:
        services.create_record(
            make_user("planlama"),
            Material,
            {
                "code": "X",
                "name": "x",
                "material_type": "WRONG",
                "base_unit": unit("KG"),
                "density": Decimal("-1"),
            },
        )
    assert "material_type" in exc.value.message_dict


def test_update_record_logs_old_and_new_values(make_user):
    user = make_user("planlama")
    material = MaterialFactory(name="Eski ad")

    services.update_record(user, material, {"name": "Yeni ad"})

    entry = AuditLog.objects.get(action=AuditLog.Action.UPDATE, object_id=material.pk)
    assert entry.changes == {"name": ["Eski ad", "Yeni ad"]}
    assert entry.actor == user


def test_update_record_cannot_change_is_active(make_user):
    with pytest.raises(ValueError):
        services.update_record(make_user("planlama"), MaterialFactory(), {"is_active": False})


def test_inactive_reference_is_rejected(make_user):
    category = MaterialCategoryFactory(is_active=False)

    with pytest.raises(BusinessRuleError) as exc:
        services.update_record(make_user("planlama"), MaterialFactory(), {"category": category})
    assert exc.value.code == "inactive_reference"


def test_base_unit_locked_when_material_is_referenced(make_user):
    from apps.recipes.tests.factories import RecipeFactory

    product = BulkMaterialFactory()
    RecipeFactory(product=product)

    with pytest.raises(BusinessRuleError) as exc:
        services.update_record(make_user("planlama"), product, {"base_unit": unit("LT")})
    assert exc.value.code == "base_unit_locked"


def test_base_unit_can_change_when_material_unused(make_user):
    material = MaterialFactory()

    services.update_record(make_user("planlama"), material, {"base_unit": unit("LT")})

    material.refresh_from_db()
    assert material.base_unit.code == "LT"


def test_set_active_deactivates_and_audits(make_user):
    material = MaterialFactory()

    services.set_active(make_user("planlama"), material, False)

    material.refresh_from_db()
    assert material.is_active is False
    entry = AuditLog.objects.get(action=AuditLog.Action.UPDATE, object_id=material.pk)
    assert entry.changes == {"is_active": [True, False]}


def test_unit_used_as_base_unit_cannot_be_deactivated(make_user):
    MaterialFactory(base_unit=unit("G"))

    with pytest.raises(BusinessRuleError) as exc:
        services.set_active(make_user("admin"), unit("G"), False)
    assert exc.value.code == "unit_in_use"


def test_unit_factor_cannot_change_when_in_use(make_user):
    MaterialFactory(base_unit=unit("G"))

    with pytest.raises(BusinessRuleError) as exc:
        services.update_record(make_user("admin"), unit("G"), {"factor_to_kind_base": Decimal("2")})
    assert exc.value.code == "unit_in_use"


def test_warehouse_with_active_locations_cannot_be_deactivated(make_user):
    location = LocationFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.set_active(make_user("planlama"), location.warehouse, False)
    assert exc.value.code == "warehouse_has_locations"


def test_location_requires_active_warehouse_on_activation(make_user):
    user = make_user("planlama")
    location = LocationFactory(is_active=False)
    services.set_active(user, location.warehouse, False)

    with pytest.raises(BusinessRuleError) as exc:
        services.set_active(user, location, True)
    assert exc.value.code == "inactive_reference"


# --- dönüşüm kuralları -----------------------------------------------------------------------


def test_conversion_to_base_unit_is_rejected(make_user):
    material = MaterialFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(
            make_user("planlama"),
            services.MaterialUnitConversion,
            {"material": material, "unit": unit("KG"), "factor_to_base": Decimal("1")},
        )
    assert exc.value.code == "conversion_to_itself"


def test_redundant_same_kind_conversion_is_rejected(make_user):
    material = MaterialFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(
            make_user("planlama"),
            services.MaterialUnitConversion,
            {"material": material, "unit": unit("G"), "factor_to_base": Decimal("0.001")},
        )
    assert exc.value.code == "conversion_redundant"


def test_duplicate_conversion_is_rejected(make_user):
    conversion = MaterialUnitConversionFactory()

    with pytest.raises(ValidationError):
        services.create_record(
            make_user("planlama"),
            services.MaterialUnitConversion,
            {"material": conversion.material, "unit": unit("KOLI"), "factor_to_base": 24},
        )


def test_conversion_material_cannot_change(make_user):
    conversion = MaterialUnitConversionFactory()
    other = MaterialFactory(material_type=Material.Type.PACKAGING, base_unit=unit("ADET"))

    with pytest.raises(BusinessRuleError) as exc:
        services.update_record(make_user("planlama"), conversion, {"material": other})
    assert exc.value.code == "conversion_key_locked"


# --- ekipman ---------------------------------------------------------------------------------


def test_tank_requires_location(make_user):
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(
            make_user("planlama"),
            Equipment,
            {"code": "TK1", "name": "Tank", "equipment_type": Equipment.Type.MIXING_TANK},
        )
    assert exc.value.code == "tank_location_required"


def test_tank_location_must_be_tank_type(make_user):
    location = LocationFactory(location_type=Location.Type.STORAGE)

    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(
            make_user("planlama"),
            Equipment,
            {
                "code": "TK1",
                "name": "Tank",
                "equipment_type": Equipment.Type.STORAGE_TANK,
                "location": location,
            },
        )
    assert exc.value.code == "tank_location_type"


def test_tank_with_tank_location_is_created(make_user):
    location = LocationFactory(location_type=Location.Type.TANK)

    tank = services.create_record(
        make_user("planlama"),
        Equipment,
        {
            "code": "tk-01",
            "name": "Karıştırma tankı 1",
            "equipment_type": Equipment.Type.MIXING_TANK,
            "capacity": Decimal("5000"),
            "capacity_unit": unit("KG"),
            "location": location,
        },
    )

    assert tank.code == "TK-01"
    assert tank.is_tank


def test_capacity_requires_unit(make_user):
    with pytest.raises(BusinessRuleError) as exc:
        services.create_record(
            make_user("planlama"),
            Equipment,
            {
                "code": "TR1",
                "name": "Terazi",
                "equipment_type": Equipment.Type.SCALE,
                "capacity": Decimal("300"),
            },
        )
    assert exc.value.code == "capacity_incomplete"


def test_location_with_active_tank_cannot_change_type(make_user):
    tank = EquipmentFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.update_record(
            make_user("planlama"), tank.location, {"location_type": Location.Type.STORAGE}
        )
    assert exc.value.code == "location_has_equipment"


def test_location_with_active_equipment_cannot_be_deactivated(make_user):
    tank = EquipmentFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.set_active(make_user("planlama"), tank.location, False)
    assert exc.value.code == "location_has_equipment"


def test_location_code_is_unique_across_warehouses(make_user):
    LocationFactory(code="A-01")

    with pytest.raises(ValidationError):
        services.create_record(
            make_user("planlama"),
            Location,
            {
                "warehouse": WarehouseFactory(),
                "code": "a-01",
                "name": "x",
                "location_type": Location.Type.STORAGE,
            },
        )
