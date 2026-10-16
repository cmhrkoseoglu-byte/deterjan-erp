"""Stok rezervasyonu (Faz 3, Adım 3.1): rezerve, bırak, kullan; kullanılabilir stok ve rezerve
stoğun çıkışlarla eritilememesi."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog
from apps.inventory import selectors, services
from apps.inventory.models import Lot, StockMovement, StockReservation
from apps.inventory.testing import assert_stock_invariants
from apps.inventory.tests.factories import quarantine_location, stocked_lot, storage_location
from apps.masterdata.models import Customer
from apps.masterdata.tests.factories import CustomerFactory

pytestmark = pytest.mark.django_db

D = Decimal
Status = StockReservation.Status


@pytest.fixture
def source() -> Customer:
    """Rezervasyonun kaynak belgesi (herhangi bir model; satışta sipariş satırı)."""
    return CustomerFactory.create()


def test_reserve_reduces_available_quantity(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("100", location=location)

    reservation = services.reserve(
        None, lot=lot, location=location, quantity=D("30"), source=source, document_number="X-1"
    )

    assert reservation.status == Status.ACTIVE
    assert reservation.document_number == "X-1"
    assert services.reserved_quantity(lot, location) == D("30")
    row = selectors.available_lots(lot.material).get()
    assert row.quantity == D("100")
    assert row.reserved_quantity == D("30")  # type: ignore[attr-defined]
    assert row.available_quantity == D("70")  # type: ignore[attr-defined]
    assert AuditLog.objects.filter(object_id=str(reservation.pk)).exists()
    assert not StockMovement.objects.filter(lot=lot).exclude(movement_type="RECEIPT").exists()
    assert_stock_invariants()


def test_reserved_stock_cannot_be_reserved_twice(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("100", location=location)
    services.reserve(None, lot=lot, location=location, quantity=D("80"), source=source)

    with pytest.raises(BusinessRuleError) as exc:
        services.reserve(None, lot=lot, location=location, quantity=D("21"), source=source)

    assert exc.value.code == "insufficient_available"
    services.reserve(None, lot=lot, location=location, quantity=D("20"), source=source)
    assert not selectors.available_lots(lot.material).exists()
    assert_stock_invariants()


def test_only_released_lot_is_reserved(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("10", location=location, status=Lot.Status.QUARANTINE)

    with pytest.raises(BusinessRuleError) as exc:
        services.reserve(None, lot=lot, location=location, quantity=D("1"), source=source)

    assert exc.value.code == "lot_not_released"


def test_expired_lot_and_quarantine_location_are_not_reserved(source: Customer) -> None:
    location = storage_location()
    expired = stocked_lot(
        "10", location=location, expiry_date=timezone.localdate() - timedelta(days=1)
    )
    with pytest.raises(BusinessRuleError) as exc:
        services.reserve(None, lot=expired, location=location, quantity=D("1"), source=source)
    assert exc.value.code == "lot_expired"

    quarantine = quarantine_location()
    lot = stocked_lot("10", location=quarantine)
    with pytest.raises(BusinessRuleError) as exc:
        services.reserve(None, lot=lot, location=quarantine, quantity=D("1"), source=source)
    assert exc.value.code == "quarantine_location"


def test_reserved_stock_cannot_be_issued_transferred_or_scrapped(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("100", location=location)
    services.reserve(None, lot=lot, location=location, quantity=D("60"), source=source)

    for movement_type in ("ISSUE_PRODUCTION", "SCRAP", "SHIPMENT"):
        with pytest.raises(BusinessRuleError) as exc:
            services.post_movement(None, lot.material, lot, location, D("-41"), movement_type, None)
        assert exc.value.code == "reserved_stock"
    with pytest.raises(BusinessRuleError) as exc:
        services.transfer(None, lot, location, storage_location(), D("41"))
    assert exc.value.code == "reserved_stock"

    # Rezerve edilmemiş kısım kullanılabilir.
    services.transfer(None, lot, location, storage_location(), D("40"))
    assert services.current_balance(lot, location) == D("60")
    assert_stock_invariants()


def test_count_adjustment_is_not_blocked_by_reservation(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("100", location=location)
    services.reserve(None, lot=lot, location=location, quantity=D("60"), source=source)

    services.post_movement(None, lot.material, lot, location, D("-50"), "ADJUSTMENT", None)

    assert services.current_balance(lot, location) == D("50")
    assert not selectors.available_lots(lot.material).exists()
    assert_stock_invariants()


def test_release_makes_stock_available_again(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("100", location=location)
    reservation = services.reserve(
        None, lot=lot, location=location, quantity=D("100"), source=source
    )

    released = services.release_reservation(None, reservation, "değişti")

    assert released.status == Status.RELEASED
    assert released.closed_at is not None
    assert selectors.available_lots(lot.material).get().available_quantity == D("100")  # type: ignore[attr-defined]
    with pytest.raises(BusinessRuleError) as exc:
        services.release_reservation(None, reservation)
    assert exc.value.code == "reservation_not_active"


def test_consume_whole_and_partial_reservation(source: Customer) -> None:
    location = storage_location()
    lot = stocked_lot("100", location=location)
    reservation = services.reserve(
        None, lot=lot, location=location, quantity=D("50"), source=source
    )

    consumed = services.consume_reservation(None, reservation, D("20"))

    assert consumed.pk != reservation.pk
    assert consumed.status == Status.CONSUMED
    assert consumed.quantity == D("20")
    reservation.refresh_from_db()
    assert reservation.status == Status.ACTIVE
    assert reservation.quantity == D("30")
    # Sevkiyat rezervasyonu kullandıktan sonra çıkışı yazar.
    services.post_movement(None, lot.material, lot, location, D("-20"), "SHIPMENT", None)

    with pytest.raises(BusinessRuleError) as exc:
        services.consume_reservation(None, reservation, D("31"))
    assert exc.value.code == "invalid_quantity"
    last = services.consume_reservation(None, reservation)
    assert last.pk == reservation.pk
    assert last.status == Status.CONSUMED
    assert list(services.reservations_for(source).values_list("status", "quantity")) == [
        (Status.CONSUMED, D("30")),
        (Status.CONSUMED, D("20")),
    ]
    assert_stock_invariants()


def test_available_lots_used_by_picking_skip_reserved_stock(source: Customer) -> None:
    location = storage_location()
    first = stocked_lot("10", location=location, expiry_date=timezone.localdate() + timedelta(30))
    second = stocked_lot(
        "10",
        material=first.material,
        location=location,
        expiry_date=timezone.localdate() + timedelta(60),
    )
    services.reserve(None, lot=first, location=location, quantity=D("10"), source=source)

    assert [row.lot_id for row in selectors.available_lots(first.material)] == [second.pk]
    assert selectors.balances().filter(lot=first).get().reserved_quantity == D("10")  # type: ignore[attr-defined]
