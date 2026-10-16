"""Canlıya geçiş okuma sorguları: sistem stoku (bir ana kadar), hazırlık kontrol listesi."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import Group
from django.db.models import Count, Q, Sum

from apps.core.roles import ADMIN, ALL_ROLES, ROLE_LABELS
from apps.filling.models import PackagingSpec
from apps.inventory import services as inventory
from apps.inventory.models import StockMovement
from apps.masterdata.models import (
    Customer,
    Equipment,
    Location,
    Material,
    Printer,
    Supplier,
    Warehouse,
)
from apps.quality.models import SampleStage, Specification
from apps.recipes.models import RecipeVersion


@dataclass(frozen=True)
class StockKey:
    material_id: int
    lot_no: str = ""
    location_id: int | None = None


def system_stock(until: datetime, *, by_lot: bool, by_location: bool) -> dict[StockKey, Decimal]:
    """`until` anından önceki tüm hareketlerin toplamı (temel birimde), sıfır olmayanlar.

    Bakiye tablosu yalnızca bugünü bilir; geçmiş bir günün stoğu hareket defterinden hesaplanır.
    """
    fields = ["material_id"]
    if by_lot:
        fields.append("lot__lot_no")
    if by_location:
        fields.append("location_id")
    rows = (
        StockMovement.objects.filter(created_at__lt=until)
        .values(*fields)
        .annotate(total=Sum("quantity"))
        .exclude(total=0)
    )
    return {
        StockKey(
            material_id=row["material_id"],
            lot_no=row.get("lot__lot_no", "") if by_lot else "",
            location_id=row.get("location_id") if by_location else None,
        ): row["total"]
        for row in rows
    }


# --- hazırlık kontrol listesi -----------------------------------------------------------------

OK, WARNING, MISSING = "OK", "WARNING", "MISSING"


def _check(
    code: str,
    group: str,
    title: str,
    status: str,
    detail: str,
    *,
    count: int | None = None,
    link: str = "",
    items: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "group": group,
        "title": title,
        "status": status,
        "detail": detail,
        "count": count,
        "link": link,
        "items": (items or [])[:20],
        "more": max(0, len(items or []) - 20),
    }


def _codes(queryset: Any) -> list[str]:
    return [f"{m.code} {m.name}" for m in queryset.order_by("code")]


def readiness() -> list[dict[str, Any]]:
    """Canlıya geçiş öncesi kontrol listesi: kullanıcılar, ana veriler, reçete ve
    spesifikasyonlar, açılış stoku. Her madde OK / WARNING (eksik ama başlanabilir) / MISSING."""
    checks: list[dict[str, Any]] = []

    # Kullanıcılar: her rolde en az bir aktif kullanıcı.
    counts = dict(
        Group.objects.filter(name__in=ALL_ROLES)
        .annotate(n=Count("user", filter=Q(user__is_active=True)))
        .values_list("name", "n")
    )
    empty = [ROLE_LABELS[role] for role in ALL_ROLES if role != ADMIN and not counts.get(role)]
    checks.append(
        _check(
            "users",
            "Kullanıcılar",
            "Her rolde en az bir kullanıcı",
            MISSING if empty else OK,
            "Kullanıcısı olmayan roller var." if empty else "Tüm rollerde kullanıcı var.",
            count=sum(counts.get(role, 0) for role in ALL_ROLES),
            link="/admin/core/user/",
            items=empty,
        )
    )

    # Ana veriler.
    active = Material.objects.filter(is_active=True)
    for code, material_type, title in (
        ("materials_raw", Material.Type.RAW, "Hammaddeler"),
        ("materials_packaging", Material.Type.PACKAGING, "Ambalaj malzemeleri"),
        ("materials_bulk", Material.Type.BULK, "Yarı mamuller (dökme)"),
        ("materials_finished", Material.Type.FINISHED, "Mamuller"),
    ):
        n = active.filter(material_type=material_type).count()
        checks.append(
            _check(
                code,
                "Ana veriler",
                title,
                OK if n else MISSING,
                f"{n} aktif kayıt." if n else "Hiç kayıt yok; Excel'den yükleyin.",
                count=n,
                link="/ana-veriler/malzemeler",
            )
        )
    for code, model, title, link in (
        ("suppliers", Supplier, "Tedarikçiler", "/ana-veriler/tedarikciler"),
        ("customers", Customer, "Müşteriler", "/ana-veriler/musteriler"),
        ("warehouses", Warehouse, "Depolar", "/ana-veriler/depolar"),
    ):
        n = model.objects.filter(is_active=True).count()
        checks.append(
            _check(
                code,
                "Ana veriler",
                title,
                OK if n else MISSING,
                f"{n} aktif kayıt." if n else "Hiç kayıt yok; Excel'den yükleyin.",
                count=n,
                link=link,
            )
        )
    locations = Location.objects.filter(is_active=True)
    missing_types = [
        str(label)
        for value, label in Location.Type.choices
        if value != Location.Type.TANK and not locations.filter(location_type=value).exists()
    ]
    checks.append(
        _check(
            "locations",
            "Ana veriler",
            "Lokasyonlar (depolama, karantina, üretim, sevkiyat)",
            MISSING if missing_types else OK,
            "Eksik lokasyon türleri var." if missing_types else f"{locations.count()} lokasyon.",
            count=locations.count(),
            link="/ana-veriler/lokasyonlar",
            items=missing_types,
        )
    )
    equipment = Equipment.objects.filter(is_active=True)
    tanks = equipment.filter(equipment_type__in=Equipment.TANK_TYPES).count()
    lines = equipment.filter(equipment_type=Equipment.Type.FILLING_LINE).count()
    scales = equipment.filter(equipment_type=Equipment.Type.SCALE).count()
    absent = [
        label for label, n in (("Tank", tanks), ("Dolum hattı", lines), ("Terazi", scales)) if not n
    ]
    checks.append(
        _check(
            "equipment",
            "Ana veriler",
            "Ekipman (tank, dolum hattı, terazi)",
            MISSING if tanks == 0 or lines == 0 else WARNING if scales == 0 else OK,
            f"{tanks} tank, {lines} dolum hattı, {scales} terazi.",
            count=equipment.count(),
            link="/ana-veriler/ekipmanlar",
            items=absent,
        )
    )
    printers = Printer.objects.filter(is_active=True).count()
    checks.append(
        _check(
            "printers",
            "Ana veriler",
            "Etiket yazıcıları",
            OK if printers else WARNING,
            f"{printers} yazıcı." if printers else "Yazıcı yok; etiketler yalnızca PDF basılır.",
            count=printers,
            link="/ana-veriler/yazicilar",
        )
    )

    # Reçete, ambalaj reçetesi, spesifikasyon.
    bulk = active.filter(material_type=Material.Type.BULK)
    no_recipe = bulk.exclude(
        recipes__versions__status=RecipeVersion.Status.APPROVED, recipes__is_active=True
    )
    checks.append(
        _check(
            "recipes",
            "Reçete ve kalite",
            "Her yarı mamulün onaylı reçetesi",
            WARNING if no_recipe.exists() else OK,
            "Onaylı reçetesi olmayan yarı mamuller üretilemez."
            if no_recipe.exists()
            else "Tüm yarı mamullerin onaylı reçetesi var.",
            count=bulk.count() - no_recipe.count(),
            link="/receteler",
            items=_codes(no_recipe),
        )
    )
    finished = active.filter(material_type=Material.Type.FINISHED)
    no_spec = finished.exclude(packaging_specs__status=PackagingSpec.Status.APPROVED)
    checks.append(
        _check(
            "packaging_specs",
            "Reçete ve kalite",
            "Her mamulün onaylı ambalaj reçetesi",
            WARNING if no_spec.exists() else OK,
            "Onaylı ambalaj reçetesi olmayan mamuller doldurulamaz."
            if no_spec.exists()
            else "Tüm mamullerin onaylı ambalaj reçetesi var.",
            count=finished.count() - no_spec.count(),
            link="/dolum/ambalaj-receteleri",
            items=_codes(no_spec),
        )
    )
    needs_spec = active.filter(
        Q(material_type=Material.Type.RAW, requires_incoming_qc=True)
        | Q(material_type=Material.Type.BULK)
    )
    no_qc = needs_spec.exclude(
        specifications__status=Specification.Status.APPROVED,
        specifications__sample_stage__in=[SampleStage.INCOMING, SampleStage.FINAL],
    )
    checks.append(
        _check(
            "specifications",
            "Reçete ve kalite",
            "Kontrol edilen malzemelerin onaylı spesifikasyonu",
            WARNING if no_qc.exists() else OK,
            "Spesifikasyonu olmayan malzemenin numunesinde test listesi boş gelir."
            if no_qc.exists()
            else "Tüm kontrol edilen malzemelerin spesifikasyonu var.",
            count=needs_spec.count() - no_qc.count(),
            link="/kalite/spesifikasyonlar",
            items=_codes(no_qc),
        )
    )

    # Açılış stoku ve canlı tarihi.
    opening = StockMovement.objects.filter(movement_type=StockMovement.Type.OPENING)
    n_opening = opening.count()
    n_materials = opening.values("material_id").distinct().count()
    checks.append(
        _check(
            "opening_stock",
            "Açılış",
            "Açılış stoku",
            OK if n_opening else MISSING,
            f"{n_materials} malzemede {n_opening} açılış hareketi."
            if n_opening
            else "Sayım gününde açılış stoku yüklenir.",
            count=n_opening,
            link="/depo/sayim",
        )
    )
    settings = inventory.get_inventory_settings()
    checks.append(
        _check(
            "go_live_date",
            "Açılış",
            "Canlı başlangıç tarihi",
            OK if settings.go_live_date else MISSING,
            f"{settings.go_live_date:%d.%m.%Y}; bu tarihten itibaren açılış stoku yüklenemez."
            if settings.go_live_date
            else "Henüz girilmedi.",
        )
    )
    return checks
