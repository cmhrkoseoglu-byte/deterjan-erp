"""Lotun koli düzeni (CUMHUR, 2026-11-05, "lotun koli düzeniyle"; Paket 2 incelemesi arka-2,
gs1-1, belge-1): lot açılırken koli içi miktar ve koli GTIN'i lota yazılır.

Var olan mamul lotlarına lotun açıldığı günkü koli düzeni yazılır. Kural, bu alanlardan önce
irsaliyenin ve etiketin kullandığı `masterdata.services.case_factor_at` / `case_gtin_at`'tir
(lotun `created_at` anında), tarihsel modellerle: lot açıldıktan sonra arşivlenmiş en eski koli
GTIN'i (`RetiredGtin`) varsa onun miktarı ve GTIN'i; yoksa bugünkü KOLI dönüşümü (miktar yalnız
dönüşüm aktifse, GTIN pasif dönüşümde de). Mamul olmayan lot boş kalır.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import migrations, models

CASE_UNIT = "KOLI"
FINISHED = "FINISHED"
MASS, VOLUME = "MASS", "VOLUME"
CHUNK = 1000


def _kind_factor(material, unit):
    """`masterdata.services._kind_factor_to_base`: genel birim katsayısıyla (kütle ↔ hacimde
    yoğunlukla) 1 `unit` kaç temel birim eder; hesaplanamıyorsa None."""
    base = material.base_unit
    if unit.factor_to_kind_base is None or base.factor_to_kind_base is None:
        return None
    if unit.kind == base.kind:
        return unit.factor_to_kind_base / base.factor_to_kind_base
    if {unit.kind, base.kind} != {MASS, VOLUME} or not material.density:
        return None
    if unit.kind == VOLUME:
        in_base_kind = unit.factor_to_kind_base * material.density
    else:
        in_base_kind = unit.factor_to_kind_base / material.density
    return in_base_kind / base.factor_to_kind_base


def _current_layout(material, case_unit, conversion):
    """Bugünkü koli düzeni (miktar, GTIN): `masterdata.services.unit_factor_to_base(malzeme,
    KOLI)` (temel birimin kendisi → aktif KOLI dönüşümü → genel katsayı) ve `case_gtin` (KOLI
    dönüşümünün GTIN'i, pasifse de)."""
    gtin = conversion.gtin if conversion is not None else ""
    if case_unit is None:
        return None, gtin
    if case_unit.pk == material.base_unit_id:
        return Decimal(1), gtin
    if conversion is not None and conversion.is_active:
        return conversion.factor_to_base, gtin
    return _kind_factor(material, case_unit), gtin


def snapshot_case_layout(apps, schema_editor):
    """Var olan mamul lotlarına lotun açıldığı günkü koli içi miktar ve koli GTIN'i."""
    Lot = apps.get_model("inventory", "Lot")
    UnitOfMeasure = apps.get_model("masterdata", "UnitOfMeasure")
    MaterialUnitConversion = apps.get_model("masterdata", "MaterialUnitConversion")
    RetiredGtin = apps.get_model("masterdata", "RetiredGtin")
    case_unit = UnitOfMeasure.objects.filter(code=CASE_UNIT).first()
    conversions = {
        conversion.material_id: conversion
        for conversion in MaterialUnitConversion.objects.filter(
            unit__code=CASE_UNIT, material__material_type=FINISHED
        )
    }
    # Malzeme başına arşiv satırları, eskiden yeniye: (arşivlendiği an, GTIN, eski miktar).
    archive = defaultdict(list)
    for material_id, created_at, gtin, factor in (
        RetiredGtin.objects.filter(conversion__unit__code=CASE_UNIT)
        .order_by("created_at", "pk")
        .values_list("conversion__material_id", "created_at", "gtin", "factor_to_base")
    ):
        archive[material_id].append((created_at, gtin, factor))
    current = {}
    layouts = defaultdict(list)
    lots = (
        Lot.objects.filter(material__material_type=FINISHED)
        .select_related("material__base_unit")
        .order_by("pk")
    )
    for lot in lots:
        material = lot.material
        if material.pk not in current:
            current[material.pk] = _current_layout(
                material, case_unit, conversions.get(material.pk)
            )
        factor, gtin = current[material.pk]
        # Lot açıldıktan sonra arşivlenen ilk koli GTIN'i: lotun açıldığı günkü koli düzeni.
        retired = next((row for row in archive[material.pk] if row[0] > lot.created_at), None)
        if retired is not None:
            factor, gtin = Decimal(retired[2]), retired[1] or gtin
        if factor is not None or gtin:
            layouts[(factor, gtin)].append(lot.pk)
    for (factor, gtin), pks in layouts.items():
        for start in range(0, len(pks), CHUNK):
            Lot.objects.filter(pk__in=pks[start : start + CHUNK]).update(
                case_factor=factor, case_gtin=gtin
            )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0007_inventory_settings"),
        # Veri adımı koli dönüşümlerini ve eski koli GTIN'lerini okur.
        ("masterdata", "0008_retired_gtin"),
    ]

    operations = [
        migrations.AddField(
            model_name="lot",
            name="case_factor",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                editable=False,
                max_digits=18,
                null=True,
                verbose_name="koli içi miktar (lotun açıldığı gün)",
            ),
        ),
        migrations.AddField(
            model_name="lot",
            name="case_gtin",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=14,
                verbose_name="koli GTIN'i (lotun açıldığı gün)",
            ),
        ),
        migrations.RunPython(snapshot_case_layout, migrations.RunPython.noop),
    ]
