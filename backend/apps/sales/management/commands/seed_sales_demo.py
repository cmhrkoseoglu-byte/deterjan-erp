"""Satış demo verisi (Faz 3): iki müşteri (biri zincir market, 180 gün asgari kalan raf ömrüyle;
D-11), mamul açılış stoku (MAMUL-DEPO) ve üç sipariş: biri onaylı (FEFO rezervasyonlu, toplanmayı
bekleyen sevkiyatıyla), biri taslak, biri sevk edilmiş (Adım 3.2: irsaliyesi basılabilir).

`seed_demo` sonunda, `seed_filling_demo`'dan sonra çağrılır. Tekrar çalıştırılabilir: var olan
müşteri koduyla, stok ve sipariş müşteri sipariş numarasıyla bulunur. Yalnızca geliştirme
ortamında (DEBUG=True) çalışır.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.core.models import User
from apps.core.roles import DEPO, SEVKIYAT
from apps.inventory import services as inventory
from apps.inventory.models import StockBalance
from apps.masterdata import services as masterdata
from apps.masterdata.models import Customer, Location, Material, UnitOfMeasure
from apps.sales import services
from apps.sales.models import SalesOrder

D = Decimal

# kod, ünvan, adres, asgari kalan raf ömrü (gün)
CUSTOMERS: list[tuple[str, str, str, int | None]] = [
    ("M-ZINCIR", "Zincir Market A.Ş.", "Merkez depo, Gebze / Kocaeli", 180),
    ("M-TOPTAN", "Toptan Temizlik Ltd.", "Ostim / Ankara", None),
]
# mamul, açılış lotu, adet, SKT (bugünden gün)
OPENING_STOCK = [
    ("BULASIK-LIMON-750", "ACILIS-BL750-1", "720", 120),
    ("BULASIK-LIMON-750", "ACILIS-BL750-2", "1440", 600),
    ("YUZEY-CAM-1000", "ACILIS-YC1000-1", "1200", 500),
]


class Command(BaseCommand):
    help = "Satış demo verisi: müşteriler, mamul açılış stoku ve örnek siparişler (yalnızca dev)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Demo verisi yalnızca geliştirme ortamında (DEBUG=True) yüklenir.")
        if not User.objects.filter(username=SEVKIYAT).exists():
            call_command("create_demo_users", stdout=self.stdout)
        seller = User.objects.get(username=SEVKIYAT)
        with transaction.atomic():
            seed(seller, self.stdout.write)
        self.stdout.write(self.style.SUCCESS("Satış demo verisi hazır."))


def seed(seller: User, write: Any = print) -> None:
    """Satış demo verisini yükler. Mamuller ve MAMUL-DEPO yoksa (seed_filling_demo) hata."""
    location = Location.objects.filter(code="MAMUL-DEPO").first()
    if location is None:
        raise CommandError("Önce seed_filling_demo çalıştırılmalı (MAMUL-DEPO yok).")
    customers = {}
    for code, name, address, days in CUSTOMERS:
        customer = Customer.objects.filter(code=code).first()
        if customer is None:
            customer = masterdata.create_record(
                seller,
                Customer,
                {
                    "code": code,
                    "name": name,
                    "address": address,
                    "min_remaining_shelf_life_days": days,
                },
                note="seed_demo",
            )
        customers[code] = customer

    today = timezone.localdate()
    for product_code, lot_no, quantity, days in OPENING_STOCK:
        product = Material.objects.get(code=product_code)
        if StockBalance.objects.filter(lot__lot_no=lot_no, material=product).exists():
            continue
        inventory.post_opening_balance(
            seller,
            material=product,
            lot_no=lot_no,
            location=location,
            quantity=D(quantity),
            manufactured_at=today,
            expiry_date=today + timedelta(days=days),
        )

    units = {unit.code: unit for unit in UnitOfMeasure.objects.all()}
    if not SalesOrder.objects.filter(customer_po_no="DEMO-1").exists():
        order = services.create_order(
            seller,
            {
                "customer": customers["M-ZINCIR"],
                "order_date": today,
                "requested_delivery_date": today + timedelta(days=3),
                "customer_po_no": "DEMO-1",
            },
            [
                {
                    "product": Material.objects.get(code="BULASIK-LIMON-750"),
                    "quantity": D(1),
                    "unit": units["PALET"],
                    "unit_price": D("1150"),
                    "currency": "TRY",
                },
                {
                    "product": Material.objects.get(code="YUZEY-CAM-1000"),
                    "quantity": D(20),
                    "unit": units["KOLI"],
                    "unit_price": D("540"),
                    "currency": "TRY",
                },
            ],
        )
        services.confirm_order(seller, order, "Demo sipariş")
        write(f"Onaylı sipariş: {order.number}")
    if not SalesOrder.objects.filter(customer_po_no="DEMO-2").exists():
        order = services.create_order(
            seller,
            {
                "customer": customers["M-TOPTAN"],
                "order_date": today,
                "customer_po_no": "DEMO-2",
            },
            [
                {
                    "product": Material.objects.get(code="BULASIK-LIMON-750"),
                    "quantity": D(30),
                    "unit": units["KOLI"],
                },
            ],
        )
        write(f"Taslak sipariş: {order.number}")

    seed_shipments(seller, customers, units, write)


VEHICLE = {"vehicle_plate": "41 DMO 41", "driver_name": "Demo Şoför", "carrier": "Kendi aracımız"}


def seed_shipments(
    seller: User, customers: dict[str, Customer], units: dict[str, UnitOfMeasure], write: Any
) -> None:
    """DEMO-1 için toplanmayı bekleyen sevkiyat; DEMO-3 siparişi ve sevk edilmiş sevkiyatı."""
    picker = User.objects.filter(username=DEPO).first()
    if picker is None or not Location.objects.filter(code="SEVK").exists():
        return
    today = timezone.localdate()
    demo1 = SalesOrder.objects.filter(customer_po_no="DEMO-1").first()
    if (
        demo1 is not None
        and demo1.status in services.RESERVABLE_STATUSES
        and not demo1.shipments.exists()
    ):
        shipment = services.plan_shipment(
            seller, demo1, {"planned_date": today + timedelta(days=1), **VEHICLE}
        )
        write(f"Toplanacak sevkiyat: {shipment.number}")
    if SalesOrder.objects.filter(customer_po_no="DEMO-3").exists():
        return
    order = services.create_order(
        seller,
        {"customer": customers["M-TOPTAN"], "order_date": today, "customer_po_no": "DEMO-3"},
        [
            {
                "product": Material.objects.get(code="YUZEY-CAM-1000"),
                "quantity": D(10),
                "unit": units["KOLI"],
            }
        ],
    )
    services.confirm_order(seller, order, "Demo sipariş")
    shipment = services.plan_shipment(seller, order, {"planned_date": today, **VEHICLE})
    for reservation in services.active_reservations(order):
        services.pick_lot(picker, shipment, reservation.lot)
    services.mark_loaded(picker, shipment)
    services.dispatch_shipment(seller, shipment, "Demo sevkiyat")
    write(f"Sevk edilmiş sevkiyat: {shipment.number} ({order.number})")
