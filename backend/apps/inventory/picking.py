"""Ortak hazırlama servisi: bir belgenin ihtiyacı için lotu depodan kullanım lokasyonuna taşır.

Faz 1'de üretimin malzeme hazırlamasıyla başlayan desen (Faz 2'de dolumun ambalaj hazırlaması da
kullanır):

- Yalnızca serbest ve SKT'si geçmemiş lot hazırlanır; lot ihtiyacın malzemesinden olmalıdır.
- Kaynak lokasyon verilmezse lotun karantina dışı, yeterli stoklu lokasyonu seçilir.
- Hazırlanan toplam ihtiyacın iki katını geçemez (ambalaj yuvarlaması için pay).
- Hazırlama `transfer` hareketidir; belge iptal edilince hazırlanan lot geldiği yere döner.

Hazırlama kaydını (`PickRecord` alt sınıfı) çağıran modül kendi modeliyle yazar; bu modül stok
hareketini ve ortak kuralları yürütür.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import User
from apps.core.services import save_with_audit
from apps.inventory import services as inventory
from apps.inventory.models import Lot, PickRecord, StockBalance
from apps.inventory.services import format_quantity, quantize
from apps.masterdata.models import Location, Material

# Hazırlanan miktar ihtiyacın en çok bu katı olabilir (ambalaj yuvarlaması için pay).
MAX_PICK_FACTOR = Decimal(2)


@dataclass(frozen=True)
class PickResult:
    """Hazırlama transferinin sonucu: kaynak lokasyon ve transfer grubu."""

    from_location: Location
    to_location: Location
    quantity: Decimal
    transfer_group: UUID


def picked_total(picks: "models.QuerySet[Any]") -> Decimal:
    """Hazırlama kayıtlarının iade edilmemiş toplamı."""
    total = picks.filter(returned_at__isnull=True).aggregate(t=Sum("quantity"))["t"]
    return total or Decimal(0)


def pick_source(
    lot: Lot, quantity: Decimal, exclude: Location, from_location: Location | None
) -> Location:
    """Hazırlamanın kaynak lokasyonu: verilen lokasyon ya da lotun karantina dışı, yeterli stoklu
    (yoksa en çok stoklu) lokasyonu. Hedef lokasyonun kendisi kaynak olamaz."""
    if from_location is not None:
        if from_location.pk == exclude.pk:
            raise BusinessRuleError(
                "same_location",
                "Malzeme zaten kullanım lokasyonunda; başka lokasyondan hazırlanır.",
            )
        return from_location
    balances = list(
        StockBalance.objects.filter(lot=lot, quantity__gt=0)
        .exclude(location=exclude)
        .exclude(location__location_type=Location.Type.QUARANTINE)
        .select_related("location")
        .order_by("-quantity", "location__code")
    )
    if not balances:
        raise BusinessRuleError(
            "lot_not_in_stock", f"Lot {lot.lot_no} için hazırlanacak stok bulunamadı."
        )
    enough = [b for b in balances if b.quantity >= quantity]
    # Yeterli stok tek lokasyondaysa orası; değilse en çok stoklu lokasyon (yetersizse
    # post_movement negatif stok hatası verir).
    return (enough or balances)[0].location


@transaction.atomic
def pick_lot(
    actor: User | None,
    *,
    lot: Lot,
    material: Material,
    quantity: Decimal,
    required_quantity: Decimal,
    already_picked: Decimal,
    to_location: Location,
    document: models.Model,
    from_location: Location | None = None,
    note: str = "",
) -> PickResult:
    """İhtiyaç için lotu kullanım lokasyonuna transfer eder ve ortak kuralları uygular.

    `material`: ihtiyacın malzemesi; `required_quantity` / `already_picked`: ihtiyaç ve şimdiye
    kadar hazırlanan (temel birimde). `document`: hareketlerin kaynak belgesi (emir). Kaydı
    çağıran yazar (`PickResult` alanlarıyla).
    """
    lot = Lot.objects.select_related("material__base_unit").get(pk=lot.pk)
    if lot.material_id != material.pk:
        raise BusinessRuleError(
            "lot_material_mismatch",
            f"Lot {lot.lot_no} {lot.material.code} malzemesine ait; bu satır {material.code} "
            "istiyor.",
        )
    inventory.assert_lot_usable(lot)
    quantity = quantize(quantity)
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    limit = required_quantity * MAX_PICK_FACTOR
    if already_picked + quantity > limit:
        unit = material.base_unit.code
        raise BusinessRuleError(
            "pick_exceeds_requirement",
            f"{material.code} için en çok {format_quantity(limit)} {unit} hazırlanabilir "
            "(ihtiyacın iki katı).",
        )
    source = pick_source(lot, quantity, to_location, from_location)
    out, _into = inventory.transfer(
        actor, lot, source, to_location, quantity, source=document, note=note
    )
    assert out.transfer_group is not None
    return PickResult(source, to_location, quantity, out.transfer_group)


@transaction.atomic
def return_picks(
    actor: User | None,
    picks: Iterable[PickRecord],
    *,
    document: models.Model,
    note: str,
    audit_note: str,
) -> int:
    """Belge iptalinde iade edilmemiş hazırlamaları geldikleri lokasyona geri transfer eder;
    kayıtların iade zamanını doldurur. İade edilen kayıt sayısını döner."""
    now = timezone.now()
    count = 0
    for pick in picks:
        if pick.returned_at is not None:
            continue
        inventory.transfer(
            actor,
            pick.lot,
            pick.to_location,
            pick.from_location,
            pick.quantity,
            source=document,
            note=note,
        )
        pick.returned_at = now
        save_with_audit(pick, actor, note=audit_note)
        count += 1
    return count
