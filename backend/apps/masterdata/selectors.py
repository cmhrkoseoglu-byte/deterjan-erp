"""Ana veri okuma sorguları."""

from django.db.models import QuerySet, Value
from django.db.models.functions import LPad

from apps.core.labels import gtin14
from apps.masterdata.models import Material, MaterialUnitConversion


def _by_gtin14[M: (Material, MaterialUnitConversion)](
    queryset: QuerySet[M], gtin: str
) -> QuerySet[M]:
    return (
        queryset.exclude(gtin="")
        .annotate(gtin_14=LPad("gtin", 14, Value("0")))
        .filter(gtin_14=gtin14(gtin))
    )


def gtin_owner(gtin: str) -> tuple[Material | None, MaterialUnitConversion | None]:
    """GTIN'in sahibi, 14 haneli normal biçimde aranır (GTIN-8/12/13/14 eşleşir).

    Ürün GTIN'iyse (malzeme, None), koli GTIN'iyse (malzeme, koli dönüşümü), kayıtlı değilse
    (None, None). Ürün ve koli GTIN'leri birlikte tektir (`masterdata.services`)."""
    gtin = (gtin or "").strip()
    if not gtin:
        return None, None
    material = _by_gtin14(Material.objects.select_related("base_unit"), gtin).first()
    if material is not None:
        return material, None
    conversion = _by_gtin14(
        MaterialUnitConversion.objects.select_related("material__base_unit", "unit"), gtin
    ).first()
    if conversion is not None:
        return conversion.material, conversion
    return None, None
