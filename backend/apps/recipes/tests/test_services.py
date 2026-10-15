from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.core import events
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.masterdata.models import Material
from apps.masterdata.tests.factories import BulkMaterialFactory, MaterialFactory, unit
from apps.recipes import services
from apps.recipes.models import RecipeLine, RecipeVersion
from apps.recipes.state import recipe_version_states
from apps.recipes.tests.factories import (
    RecipeFactory,
    RecipeLineFactory,
    RecipeStepFactory,
    RecipeVersionFactory,
)

pytestmark = pytest.mark.django_db

DRAFT = RecipeVersion.Status.DRAFT
APPROVED = RecipeVersion.Status.APPROVED
OBSOLETE = RecipeVersion.Status.OBSOLETE


@pytest.fixture
def planner(make_user):
    return make_user("planlama")


def line_data(material=None, qty="100", unit_code="KG", **extra):
    return {
        "material": material or MaterialFactory(),
        "quantity": Decimal(qty),
        "unit": unit(unit_code),
        **extra,
    }


def draft_with_line(**kwargs):
    version = RecipeVersionFactory(**kwargs)
    RecipeLineFactory(version=version)
    return version


def capture_events():
    seen = []
    events.subscribe("recipe_version.*")(seen.append)
    return seen


# --- reçete ----------------------------------------------------------------------------------


def test_create_recipe_requires_bulk_product(planner):
    raw = MaterialFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.create_recipe(planner, {"code": "r1", "name": "x", "product": raw})
    assert exc.value.code == "recipe_product_not_bulk"


def test_create_recipe_uppercases_code_and_audits(planner):
    recipe = services.create_recipe(
        planner, {"code": "bulasik-1", "name": "Bulaşık", "product": BulkMaterialFactory()}
    )

    assert recipe.code == "BULASIK-1"
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=recipe.pk).exists()


def test_recipe_product_locked_once_versions_exist(planner):
    version = RecipeVersionFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.update_recipe(planner, version.recipe, {"product": BulkMaterialFactory()})
    assert exc.value.code == "recipe_product_locked"


# --- sürüm oluşturma -------------------------------------------------------------------------


def test_create_version_numbers_sequentially_with_lines_and_steps(planner):
    recipe = RecipeFactory()
    services.create_version(planner, recipe, batch_size=Decimal("1000"), batch_unit=unit("KG"))

    version = services.create_version(
        planner,
        recipe,
        batch_size=Decimal("500"),
        batch_unit=unit("KG"),
        change_note="ikinci",
        lines=[line_data(qty="80"), line_data(qty="20", tolerance_pct=Decimal("1"))],
        steps=[{"description": "Suyu ekle", "mixer_rpm": 300}],
    )

    assert version.version_no == 2
    assert version.status == DRAFT
    assert [line.sequence for line in version.lines.order_by("sequence")] == [1, 2]
    assert version.steps.get().mixer_rpm == 300


def test_create_version_on_inactive_recipe_is_rejected(planner):
    recipe = RecipeFactory(is_active=False)

    with pytest.raises(BusinessRuleError) as exc:
        services.create_version(planner, recipe, batch_size=Decimal("1"), batch_unit=unit("KG"))
    assert exc.value.code == "inactive_reference"


def test_create_version_rejects_unconvertible_batch_unit(planner):
    recipe = RecipeFactory(product=BulkMaterialFactory(density=None))

    with pytest.raises(BusinessRuleError) as exc:
        services.create_version(planner, recipe, batch_size=Decimal("1"), batch_unit=unit("LT"))
    assert exc.value.code == "no_conversion"


def test_create_version_rejects_non_positive_batch_size(planner):
    with pytest.raises(ValidationError):
        services.create_version(
            planner, RecipeFactory(), batch_size=Decimal("0"), batch_unit=unit("KG")
        )


# --- satırlar --------------------------------------------------------------------------------


def test_add_line_appends_sequence_and_defaults_tolerance(planner):
    version = RecipeVersionFactory()
    services.add_line(planner, version, line_data())

    line = services.add_line(planner, version, line_data(unit_code="G", qty="250"))

    assert line.sequence == 2
    assert line.tolerance_pct == Decimal("2.00")


def test_line_material_must_be_raw_or_bulk(planner):
    packaging = MaterialFactory(material_type=Material.Type.PACKAGING)

    with pytest.raises(BusinessRuleError) as exc:
        services.add_line(planner, RecipeVersionFactory(), line_data(material=packaging))
    assert exc.value.code == "invalid_ingredient"


def test_line_cannot_use_recipe_product(planner):
    version = RecipeVersionFactory()

    with pytest.raises(BusinessRuleError) as exc:
        services.add_line(planner, version, line_data(material=version.recipe.product))
    assert exc.value.code == "recipe_self_reference"


def test_line_unit_must_be_convertible(planner):
    with pytest.raises(BusinessRuleError) as exc:
        services.add_line(
            planner, RecipeVersionFactory(), line_data(material=MaterialFactory(), unit_code="LT")
        )
    assert exc.value.code == "no_conversion"


def test_water_is_an_ordinary_stocked_ingredient(planner):
    """Karar D-1: su stoktan düşülür; `is_water` yalnızca işaret, ihtiyaç listesinde yer alır."""
    water = MaterialFactory(code="SU", base_unit=unit("LT"), density=Decimal("1"))
    version = RecipeVersionFactory()
    services.add_line(
        planner, version, line_data(material=water, qty="600", unit_code="KG", is_water=True)
    )

    [requirement] = services.scale_requirements(version, Decimal("1000"), unit("KG"))

    assert requirement.material == water
    assert requirement.is_water is True
    assert requirement.quantity == Decimal("600.0000")
    assert requirement.unit.code == "LT"


def test_update_and_remove_line_in_draft(planner):
    version = RecipeVersionFactory()
    line = RecipeLineFactory(version=version, quantity=Decimal("10"))

    services.update_line(planner, line, {"quantity": Decimal("12")})
    services.remove_line(planner, line)

    assert not RecipeLine.objects.filter(pk=line.pk).exists()
    entry = AuditLog.objects.filter(object_id=version.pk, note__contains="silindi").get()
    assert entry.changes["line"][0]["quantity"] == "12.0000"


@pytest.mark.parametrize("operation", ["add_line", "update_line", "remove_line", "add_step"])
def test_approved_version_cannot_be_changed(planner, operation):
    version = draft_with_line()
    services.approve_version(planner, version)
    line = version.lines.get()

    with pytest.raises(BusinessRuleError) as exc:
        if operation == "add_line":
            services.add_line(planner, version, line_data())
        elif operation == "update_line":
            services.update_line(planner, line, {"quantity": Decimal("1")})
        elif operation == "remove_line":
            services.remove_line(planner, line)
        else:
            services.add_step(planner, version, {"description": "x"})
    assert exc.value.code == "version_locked"


def test_approved_version_header_cannot_be_changed(planner):
    version = draft_with_line()
    services.approve_version(planner, version)

    with pytest.raises(BusinessRuleError) as exc:
        services.update_version(planner, version, {"batch_size": Decimal("1")})
    assert exc.value.code == "version_locked"


def test_steps_update_and_remove(planner):
    step = RecipeStepFactory(temperature_c=None)

    services.update_step(planner, step, {"temperature_c": Decimal("45")})
    step.refresh_from_db()
    assert step.temperature_c == Decimal("45")

    services.remove_step(planner, step)
    assert not step.version.steps.exists()


# --- onay ve durum makinesi ------------------------------------------------------------------


def test_state_machine_allowed_transitions():
    assert recipe_version_states.can_transition("DRAFT", "APPROVED")
    assert recipe_version_states.can_transition("APPROVED", "OBSOLETE")


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [("DRAFT", "OBSOLETE"), ("APPROVED", "DRAFT"), ("OBSOLETE", "APPROVED"), ("OBSOLETE", "DRAFT")],
)
def test_state_machine_forbidden_transitions(from_status, to_status):
    with pytest.raises(BusinessRuleError) as exc:
        recipe_version_states.assert_can_transition(from_status, to_status)
    assert exc.value.code == "invalid_transition"


def test_approve_version_sets_approver_audits_and_publishes(
    django_capture_on_commit_callbacks, planner
):
    seen = capture_events()
    version = draft_with_line()

    with django_capture_on_commit_callbacks(execute=True):
        services.approve_version(planner, version, "ilk onay")

    version.refresh_from_db()
    assert version.status == APPROVED
    assert version.approved_by == planner
    assert version.approved_at is not None
    entry = AuditLog.objects.get(action=AuditLog.Action.STATUS_CHANGE, object_id=version.pk)
    assert entry.changes == {"status": ["DRAFT", "APPROVED"]}
    assert [e.name for e in seen] == ["recipe_version.approved"]


def test_new_approval_makes_previous_obsolete(django_capture_on_commit_callbacks, planner):
    """Kabul kriteri: onaylı sürüm değişmez; kopyalanıp yeni sürüm onaylanınca eski OBSOLETE."""
    seen = capture_events()
    v1 = draft_with_line()
    services.approve_version(planner, v1)

    v2 = services.copy_version(planner, v1, "parfüm artırıldı")
    services.update_line(planner, v2.lines.get(), {"quantity": Decimal("150")})
    with django_capture_on_commit_callbacks(execute=True):
        services.approve_version(planner, v2)

    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v1.status == OBSOLETE and v1.obsoleted_at is not None
    assert v2.status == APPROVED
    assert v1.lines.get().quantity == Decimal("100")  # eski sürüm değişmedi
    assert v2.copied_from == v1
    assert RecipeVersion.objects.filter(recipe=v1.recipe, status=APPROVED).count() == 1
    assert [e.name for e in seen] == ["recipe_version.obsolete", "recipe_version.approved"]


def test_copy_version_copies_lines_and_steps(planner):
    source = draft_with_line()
    RecipeStepFactory(version=source, description="Isıt", temperature_c=Decimal("40"))

    copy = services.copy_version(planner, source, "kopya")

    assert copy.version_no == source.version_no + 1
    assert copy.status == DRAFT
    assert copy.change_note == "kopya"
    assert copy.lines.count() == 1 and copy.lines.get().pk != source.lines.get().pk
    assert copy.steps.get().temperature_c == Decimal("40")


def test_approve_requires_role(make_user):
    with pytest.raises(PermissionDenied):
        services.approve_version(make_user("depo"), draft_with_line())


def test_laboratuvar_can_approve(make_user):
    version = services.approve_version(make_user("laboratuvar"), draft_with_line())

    assert version.status == APPROVED


def test_approve_without_lines_is_rejected(planner):
    with pytest.raises(BusinessRuleError) as exc:
        services.approve_version(planner, RecipeVersionFactory())
    assert exc.value.code == "version_has_no_lines"


def test_approve_with_inactive_material_is_rejected(planner):
    version = draft_with_line()
    material = version.lines.get().material
    material.is_active = False
    material.save()

    with pytest.raises(BusinessRuleError) as exc:
        services.approve_version(planner, version)
    assert exc.value.code == "inactive_reference"


def test_approving_twice_is_rejected(planner):
    version = services.approve_version(planner, draft_with_line())

    with pytest.raises(BusinessRuleError) as exc:
        services.approve_version(planner, version)
    assert exc.value.code == "version_locked"


# --- ölçekleme -------------------------------------------------------------------------------


def test_scale_requirements_in_base_units(planner):
    las = MaterialFactory(code="LAS")
    perfume = MaterialFactory(code="PARFUM", base_unit=unit("G"))
    version = RecipeVersionFactory(batch_size=Decimal("1000"), batch_unit=unit("KG"))
    services.add_line(planner, version, line_data(material=las, qty="120"))
    services.add_line(
        planner, version, line_data(material=perfume, qty="2.5", tolerance_pct=Decimal("1"))
    )

    result = services.scale_requirements(version, Decimal("2500"), unit("KG"))

    assert [(r.material.code, r.quantity, r.unit.code, r.tolerance_pct) for r in result] == [
        ("LAS", Decimal("300.0000"), "KG", Decimal("2.00")),
        ("PARFUM", Decimal("6250.0000"), "G", Decimal("1.00")),
    ]


def test_scale_with_volume_target_uses_product_density(planner):
    product = BulkMaterialFactory(density=Decimal("1.25"))
    version = RecipeVersionFactory(recipe=RecipeFactory(product=product))
    services.add_line(planner, version, line_data(qty="100"))

    [requirement] = services.scale_requirements(version, Decimal("800"), unit("LT"))  # = 1000 KG

    assert requirement.quantity == Decimal("100.0000")


def test_scale_rejects_non_positive_quantity():
    with pytest.raises(BusinessRuleError) as exc:
        services.scale_requirements(draft_with_line(), Decimal("0"), unit("KG"))
    assert exc.value.code == "invalid_quantity"
