"""Stok servisleri: hareket defteri, transfer, ters kayıt, lot, mal kabul, lot kararı, sayım
düzeltme ve açılış stoku.

Değişmez kurallar (CLAUDE.md §4):
- Stoka dokunmanın tek yolu `post_movement`'tır. Hareketler değiştirilmez/silinmez; bakiye aynı
  transaction'da `select_for_update` ile güncellenir.
- Negatif stok yok: bakiye sıfırın altına düşecekse işlem `negative_stock` ile reddedilir.
- Yalnızca serbest bırakılmış (RELEASED) ve SKT'si geçmemiş lot üretimde tüketilir ve sevk edilir.
- Bir lottan tüketip başka lot üreten işlem `link_lots` ile soy ağacına yazılır.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.db.models import F, Max
from django.utils import timezone

from apps.core import events
from apps.core.audit import log_change, snapshot
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, DocumentModel, User
from apps.core.roles import LABORATUVAR
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.core.state import StateMachine
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    Lot,
    LotLink,
    LotNumberSequence,
    StockAdjustment,
    StockAdjustmentLine,
    StockBalance,
    StockMovement,
)
from apps.inventory.state import goods_receipt_states, lot_states, stock_adjustment_states
from apps.masterdata import services as masterdata
from apps.masterdata.models import Location, Material, Supplier, UnitOfMeasure

QUANTITY_STEP = Decimal("0.0001")
MovementType = StockMovement.Type

# Giriş hareketleri pozitif, çıkış hareketleri negatif olmalıdır; düzeltme ve ters kayıt her iki
# yönde olabilir.
INBOUND_TYPES = frozenset(
    {
        MovementType.OPENING,
        MovementType.RECEIPT,
        MovementType.PRODUCTION_OUTPUT,
        MovementType.TRANSFER_IN,
        MovementType.RETURN,
    }
)
OUTBOUND_TYPES = frozenset(
    {
        MovementType.ISSUE_PRODUCTION,
        MovementType.TRANSFER_OUT,
        MovementType.SCRAP,
        MovementType.SHIPMENT,
    }
)
# Kural 4: bu hareketler yalnızca serbest ve SKT'si geçmemiş lottan yapılır. Transfer, fire ve
# düzeltme her durumdaki lota yapılabilir (karantinadaki lot depo içinde taşınabilir).
USABLE_LOT_ONLY_TYPES = frozenset({MovementType.ISSUE_PRODUCTION, MovementType.SHIPMENT})

LOT_DECISION_ROLES = (LABORATUVAR,)
# Lot numarası önekleri (Karar D-2): satın alma H, üretim B, dolum D.
LOT_PREFIXES: dict[str, str] = {
    Lot.Source.PURCHASE: "H",
    Lot.Source.PRODUCTION: "B",
    Lot.Source.FILLING: "D",
}
RECEIVABLE_TYPES = (Material.Type.RAW, Material.Type.PACKAGING)
OPENING_STATUSES = (Lot.Status.RELEASED, Lot.Status.QUARANTINE)


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def quantize(quantity: Decimal) -> Decimal:
    """Miktarı 4 ondalığa yuvarlar (yarım yukarı)."""
    return quantity.quantize(QUANTITY_STEP, rounding=ROUND_HALF_UP)


def format_quantity(quantity: Decimal) -> str:
    """Mesajlar için Türkçe biçim: `1250.5000` → `1250,5`."""
    text = f"{quantity.normalize():f}"
    return text.replace(".", ",")


def _require_active(obj: Any, label: str) -> None:
    if obj is not None and not obj.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif {label} seçilemez: {obj}.")


def _pick(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


# --- lot kullanılabilirliği ------------------------------------------------------------------


def lot_usable_error(lot: Lot, *, today: date | None = None) -> BusinessRuleError | None:
    """Lot üretimde tüketilemez / sevk edilemezse nedeni; kullanılabilirse None."""
    if lot.status != Lot.Status.RELEASED:
        return BusinessRuleError(
            "lot_not_released",
            f"Lot {lot.lot_no} {lot_states.label(lot.status).lower()} durumda; yalnızca serbest "
            "bırakılmış lot kullanılabilir.",
        )
    today = today or timezone.localdate()
    if lot.expiry_date is not None and lot.expiry_date < today:
        return BusinessRuleError(
            "lot_expired",
            f"Lot {lot.lot_no} son kullanma tarihi geçmiş ({lot.expiry_date:%d.%m.%Y}).",
        )
    return None


def assert_lot_usable(lot: Lot) -> None:
    """Lot serbest değilse ya da SKT'si geçmişse `BusinessRuleError` fırlatır (CLAUDE.md §4.4)."""
    error = lot_usable_error(lot)
    if error is not None:
        raise error


# --- hareket defteri -------------------------------------------------------------------------


def _source_fields(source: models.Model | None) -> dict[str, Any]:
    if source is None:
        return {"source_content_type": None, "source_object_id": None, "document_number": ""}
    return {
        "source_content_type": ContentType.objects.get_for_model(source),
        "source_object_id": source.pk,
        "document_number": str(getattr(source, "number", "") or ""),
    }


def _lock_balance(material: Material, lot: Lot, location: Location) -> StockBalance:
    # Satır yoksa çakışmasız oluştur, sonra kilitle (eşzamanlı ilk harekette IntegrityError olmaz).
    StockBalance.objects.bulk_create(
        [StockBalance(material=material, lot=lot, location=location, quantity=Decimal(0))],
        ignore_conflicts=True,
    )
    return StockBalance.objects.select_for_update().get(
        material=material, lot=lot, location=location
    )


def current_balance(lot: Lot, location: Location) -> Decimal:
    """Lotun lokasyondaki bakiyesi (kayıt yoksa 0)."""
    value = (
        StockBalance.objects.filter(lot=lot, location=location)
        .values_list("quantity", flat=True)
        .first()
    )
    return value if value is not None else Decimal(0)


@transaction.atomic
def post_movement(
    actor: User | None,
    material: Material,
    lot: Lot,
    location: Location,
    quantity: Decimal,
    movement_type: str,
    source: models.Model | None,
    note: str = "",
    *,
    reversal_of: StockMovement | None = None,
    transfer_group: uuid.UUID | None = None,
) -> StockMovement:
    """Stok hareketi yazar ve bakiyeyi aynı transaction'da günceller. **Stoka dokunmanın tek yolu.**

    `quantity` işaretlidir ve malzemenin temel birimindedir (giriş +, çıkış −); 4 ondalığa
    yuvarlanır. Bakiye satırı `select_for_update` ile kilitlenir; sıfırın altına düşecekse
    `BusinessRuleError("negative_stock")`. Üretime çıkış ve sevkiyat yalnızca serbest ve SKT'si
    geçmemiş lottan yapılır (`lot_not_released`, `lot_expired`). `source`: hareketi doğuran belge.
    """
    if not isinstance(quantity, Decimal):
        raise TypeError("Miktar Decimal olmalıdır.")
    if movement_type not in MovementType.values:
        raise ValueError(f"Tanımsız hareket türü: {movement_type}")
    if lot.material_id != material.pk:
        raise ValueError("Lot bu malzemeye ait değil.")
    if (movement_type == MovementType.REVERSAL) != (reversal_of is not None):
        raise ValueError("Ters kayıt yalnızca reversal_of ile ve REVERSAL türünde yazılır.")
    quantity = quantize(quantity)
    if quantity == 0:
        raise BusinessRuleError("zero_quantity", "Hareket miktarı sıfır olamaz.")
    if movement_type in INBOUND_TYPES and quantity < 0:
        raise ValueError(f"{movement_type} hareketi pozitif olmalıdır.")
    if movement_type in OUTBOUND_TYPES and quantity > 0:
        raise ValueError(f"{movement_type} hareketi negatif olmalıdır.")
    if quantity > 0 and not location.is_active:
        raise BusinessRuleError(
            "inactive_reference", f"Pasif lokasyona giriş yapılamaz: {location}."
        )

    if movement_type in USABLE_LOT_ONLY_TYPES:
        # Lot satırı kilitlenir: aynı anda verilen bir red/bloke kararı tüketimi kaçırmasın.
        assert_lot_usable(Lot.objects.select_for_update().get(pk=lot.pk))

    balance = _lock_balance(material, lot, location)
    new_quantity = balance.quantity + quantity
    if new_quantity < 0:
        unit = material.base_unit.code
        raise BusinessRuleError(
            "negative_stock",
            f"Yetersiz stok: {material.code} lot {lot.lot_no}, {location.code} lokasyonunda "
            f"{format_quantity(balance.quantity)} {unit} var, "
            f"{format_quantity(-quantity)} {unit} isteniyor.",
        )
    balance.quantity = new_quantity
    balance.save(update_fields=["quantity", "updated_at"])
    return StockMovement.objects.create(
        movement_type=movement_type,
        material=material,
        lot=lot,
        location=location,
        quantity=quantity,
        reversal_of=reversal_of,
        transfer_group=transfer_group,
        note=note,
        created_by=_actor(actor),
        **_source_fields(source),
    )


@transaction.atomic
def transfer(
    actor: User | None,
    lot: Lot,
    from_location: Location,
    to_location: Location,
    quantity: Decimal,
    source: models.Model | None = None,
    note: str = "",
) -> tuple[StockMovement, StockMovement]:
    """Lotu bir lokasyondan diğerine taşır: `TRANSFER_OUT` + `TRANSFER_IN`, ortak `transfer_group`.

    `quantity` pozitif ve temel birimdedir. Karantinadaki lot da taşınabilir.
    """
    if from_location.pk == to_location.pk:
        raise BusinessRuleError("same_location", "Kaynak ve hedef lokasyon aynı olamaz.")
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Transfer miktarı sıfırdan büyük olmalıdır.")
    _require_active(to_location, "lokasyon")
    group = uuid.uuid4()
    material = lot.material
    out = post_movement(
        actor,
        material,
        lot,
        from_location,
        -quantity,
        MovementType.TRANSFER_OUT,
        source,
        note,
        transfer_group=group,
    )
    into = post_movement(
        actor,
        material,
        lot,
        to_location,
        quantity,
        MovementType.TRANSFER_IN,
        source,
        note,
        transfer_group=group,
    )
    return out, into


@transaction.atomic
def reverse_movement(
    actor: User | None, movement: StockMovement, reason: str
) -> list[StockMovement]:
    """Hareketi ters kayıtla geri alır (`REVERSAL`, ters işaretli miktar). Neden zorunludur.

    Transferin bir bacağı verilirse transferin iki bacağı birlikte geri alınır. Bir hareket bir
    kez geri alınır (`already_reversed`); ters kaydın kendisi geri alınamaz. Geri alma bakiyeyi
    negatife düşürecekse `negative_stock`.
    """
    reason = reason.strip()
    if not reason:
        raise BusinessRuleError("reversal_reason_required", "Ters kayıt nedeni girilmelidir.")
    movement = StockMovement.objects.select_related("material__base_unit", "lot", "location").get(
        pk=movement.pk
    )
    if movement.movement_type == MovementType.REVERSAL:
        raise BusinessRuleError("cannot_reverse_reversal", "Ters kayıt geri alınamaz.")
    if movement.transfer_group is not None:
        group = list(
            StockMovement.objects.filter(transfer_group=movement.transfer_group)
            .select_related("material__base_unit", "lot", "location")
            .order_by("id")
        )
    else:
        group = [movement]
    if StockMovement.objects.filter(reversal_of__in=group).exists():
        raise BusinessRuleError("already_reversed", "Bu hareket zaten geri alınmış.")
    new_group = uuid.uuid4() if movement.transfer_group is not None else None
    reversals = []
    # Önce girişleri geri al: transferde hedefteki stok kaynağa dönmeden önce düşülür.
    for original in sorted(group, key=lambda m: m.quantity, reverse=True):
        reversals.append(
            post_movement(
                actor,
                original.material,
                original.lot,
                original.location,
                -original.quantity,
                MovementType.REVERSAL,
                original.source,
                f"Ters kayıt: {reason}",
                reversal_of=original,
                transfer_group=new_group,
            )
        )
    return reversals


# --- lot -------------------------------------------------------------------------------------


def next_lot_number(prefix: str, day: date | None = None) -> str:
    """Gün bazında sıfırlanan lot numarası: `H-261015-001` (Karar D-2).

    Sayaç önek + gün başınadır, tüm malzemelerde ortaktır; satır `select_for_update` ile
    kilitlenir. Lotu oluşturan transaction'ın içinde çağrılmalıdır.
    """
    if prefix not in LOT_PREFIXES.values():
        raise ValueError(f"Geçersiz lot öneki: {prefix!r}")
    day = day or timezone.localdate()
    with transaction.atomic():
        LotNumberSequence.objects.bulk_create(
            [LotNumberSequence(prefix=prefix, day=day, last_number=0)], ignore_conflicts=True
        )
        sequence = LotNumberSequence.objects.select_for_update().get(prefix=prefix, day=day)
        sequence.last_number = F("last_number") + 1
        sequence.save(update_fields=["last_number"])
        sequence.refresh_from_db(fields=["last_number"])
    return f"{prefix}-{day:%y%m%d}-{sequence.last_number:03d}"


def default_expiry_date(material: Material, start: date) -> date | None:
    """Malzemenin raf ömrüne göre SKT (`start` + raf ömrü); raf ömrü yoksa None."""
    if not material.shelf_life_days:
        return None
    return start + timedelta(days=material.shelf_life_days)


@transaction.atomic
def create_lot(
    actor: User | None,
    *,
    material: Material,
    source: str,
    lot_no: str = "",
    status: str = Lot.Status.QUARANTINE,
    supplier: Supplier | None = None,
    supplier_lot_no: str = "",
    manufactured_at: date | None = None,
    expiry_date: date | None = None,
    day: date | None = None,
    note: str = "",
) -> Lot:
    """Yeni lot açar (denetim günlüklü).

    `lot_no` verilmezse kaynağa göre otomatik numara (`H-`, `B-`, `D-` + `day`). SKT verilmezse
    üretim tarihi (yoksa `day`/bugün) + malzemenin raf ömrü. Başlangıç durumu `QUARANTINE` ya da
    `RELEASED` olabilir; serbest açılan lotta serbest bırakan ve zaman doldurulur.
    """
    actor = _actor(actor)
    if source not in Lot.Source.values:
        raise ValueError(f"Tanımsız lot kaynağı: {source}")
    if status not in (Lot.Status.QUARANTINE, Lot.Status.RELEASED):
        raise ValueError("Lot karantina ya da serbest olarak açılır.")
    lot_no = lot_no.strip().upper()
    if not lot_no:
        prefix = LOT_PREFIXES.get(source)
        if prefix is None:
            raise BusinessRuleError("lot_no_required", "Lot numarası girilmelidir.")
        lot_no = next_lot_number(prefix, day)
    elif Lot.objects.filter(material=material, lot_no=lot_no).exists():
        raise BusinessRuleError(
            "lot_exists", f"{material.code} malzemesinde {lot_no} lotu zaten var."
        )
    if expiry_date is None:
        expiry_date = default_expiry_date(material, manufactured_at or day or timezone.localdate())
    if manufactured_at and expiry_date and expiry_date < manufactured_at:
        raise BusinessRuleError(
            "invalid_expiry_date", "Son kullanma tarihi üretim tarihinden önce olamaz."
        )
    lot = Lot(
        lot_no=lot_no,
        material=material,
        status=status,
        source=source,
        supplier=supplier,
        supplier_lot_no=supplier_lot_no.strip(),
        manufactured_at=manufactured_at,
        expiry_date=expiry_date,
        status_note=note,
    )
    if status == Lot.Status.RELEASED:
        lot.released_by = actor
        lot.released_at = timezone.now()
    return save_with_audit(lot, actor, note=note)


@transaction.atomic
def link_lots(
    actor: User | None,
    parent_lot: Lot,
    child_lot: Lot,
    quantity: Decimal,
    source: models.Model | None = None,
) -> LotLink:
    """Soy ağacına girdi lot → çıktı lot bağı yazar (CLAUDE.md §4.3). `quantity`: girdi lottan
    kullanılan miktar, temel birimde."""
    quantity = quantize(quantity)
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Kullanılan miktar sıfırdan büyük olmalıdır.")
    if parent_lot.pk == child_lot.pk:
        raise BusinessRuleError("lot_self_link", "Lot kendisine bağlanamaz.")
    fields = _source_fields(source)
    fields.pop("document_number")
    return LotLink.objects.create(
        parent_lot=parent_lot,
        child_lot=child_lot,
        quantity=quantity,
        created_by=_actor(actor),
        **fields,
    )


def can_decide_lot(actor: User | None) -> bool:
    """Lot serbest bırakma / reddetme / bloke yetkisi: laboratuvar (ve admin)."""
    actor = _actor(actor)
    return (
        actor is not None
        and actor.is_active
        and (actor.is_admin or actor.has_role(*LOT_DECISION_ROLES))
    )


def lot_payload(lot: Lot, **extra: Any) -> dict[str, Any]:
    """Olay sözleşmesindeki lot sözlüğü (DECISIONS.md "İş akışı olay sözleşmesi")."""
    return {
        "model": lot._meta.label_lower,
        "id": lot.pk,
        "lot_no": lot.lot_no,
        "material_code": lot.material.code,
        "material_name": lot.material.name,
        **extra,
    }


def _set_lot_status(actor: User | None, lot: Lot, to_status: str, note: str) -> Lot:
    if not can_decide_lot(actor):
        raise PermissionDenied("Lot kararını yalnızca laboratuvar verir.")
    actor = _actor(actor)
    lot = Lot.objects.select_for_update().select_related("material").get(pk=lot.pk)
    from_status = lot.status
    lot_states.assert_can_transition(from_status, to_status)
    lot.status = to_status
    lot.status_note = note
    lot.updated_by = actor
    fields = ["status", "status_note", "updated_by", "updated_at"]
    if to_status == Lot.Status.RELEASED:
        lot.released_by = actor
        lot.released_at = timezone.now()
        fields += ["released_by", "released_at"]
    lot.save(update_fields=fields)
    log_change(
        actor, lot, AuditLog.Action.STATUS_CHANGE, {"status": [from_status, to_status]}, note
    )
    events.publish(
        lot_states.event_name(to_status),
        lot_payload(
            lot,
            material_type=lot.material.material_type,
            note=note,
            from_status=from_status,
            to_status=to_status,
        ),
        actor,
    )
    return lot


@transaction.atomic
def release_lot(
    actor: User | None, lot: Lot, note: str = "", to_location: Location | None = None
) -> Lot:
    """Lotu serbest bırakır (rol: laboratuvar). Karantinadaki ya da bloke lot serbest bırakılır.

    Lotun karantina lokasyonlarındaki stoku `to_location`'a transfer edilir; karantinada stok
    varsa hedef lokasyon zorunludur ve karantina türünde olamaz. Olay: `lot.released`.
    """
    note = note.strip()
    lot = _set_lot_status(actor, lot, Lot.Status.RELEASED, note)
    quarantined = list(
        StockBalance.objects.filter(
            lot=lot, quantity__gt=0, location__location_type=Location.Type.QUARANTINE
        ).select_related("location")
    )
    if not quarantined:
        return lot
    if to_location is None:
        raise BusinessRuleError(
            "release_location_required",
            "Lot karantinada stokta; serbest bırakmak için hedef lokasyon seçilmelidir.",
        )
    if to_location.location_type == Location.Type.QUARANTINE:
        raise BusinessRuleError(
            "invalid_release_location", "Serbest bırakılan lot karantina lokasyonuna taşınamaz."
        )
    for balance in quarantined:
        transfer(
            actor,
            lot,
            balance.location,
            to_location,
            balance.quantity,
            note=f"Serbest bırakma: {lot.lot_no}",
        )
    return lot


def _require_note(note: str, what: str) -> str:
    note = note.strip()
    if not note:
        raise BusinessRuleError("note_required", f"{what} nedeni girilmelidir.")
    return note


@transaction.atomic
def reject_lot(actor: User | None, lot: Lot, note: str) -> Lot:
    """Lotu reddeder (rol: laboratuvar). Neden zorunlu; reddedilen lot geri alınamaz, stoku yerinde
    kalır (iade/imha Faz 4). Olay: `lot.rejected`."""
    return _set_lot_status(actor, lot, Lot.Status.REJECTED, _require_note(note, "Ret"))


@transaction.atomic
def block_lot(actor: User | None, lot: Lot, note: str) -> Lot:
    """Lotu bloke eder (rol: laboratuvar). Neden zorunlu; bloke lot yeniden serbest bırakılabilir
    ya da reddedilebilir. Olay: `lot.blocked`."""
    return _set_lot_status(actor, lot, Lot.Status.BLOCKED, _require_note(note, "Bloke"))


# --- taslak belge satırları (mal kabul, sayım düzeltme) --------------------------------------


def _lock_document[D: DocumentModel](document: D) -> D:
    return type(document)._base_manager.select_for_update().get(pk=document.pk)


def _require_draft(document: DocumentModel, machine: StateMachine) -> None:
    if document.status != "DRAFT":
        raise BusinessRuleError(
            "document_locked",
            f"{document.number} {machine.label(document.status).lower()}; değiştirilemez.",
        )


def _sync_lines(
    actor: User | None,
    document: DocumentModel,
    manager: Any,
    model: type[GoodsReceiptLine] | type[StockAdjustmentLine],
    parent_field: str,
    items: Iterable[Mapping[str, Any]],
    fields: Sequence[str],
    prepare: Any,
) -> None:
    """Taslak belgenin satırlarını verilen listeyle eşitler: `id`'li satır güncellenir, `id`'siz
    satır eklenir, listede olmayan satır kaldırılır (denetim kaydıyla)."""
    existing = {line.pk: line for line in manager.select_for_update().order_by("line_no")}
    keep: set[int] = set()
    next_no = (manager.aggregate(m=Max("line_no"))["m"] or 0) + 1
    pending: list[tuple[models.Model, bool]] = []
    for item in items:
        values = dict(item)
        line_id = values.pop("id", None)
        values = _pick(values, fields)
        if line_id is not None:
            line = existing.get(line_id)
            if line is None:
                raise BusinessRuleError("line_not_found", f"Belgede {line_id} numaralı satır yok.")
            keep.add(line_id)
            for name, value in values.items():
                setattr(line, name, value)
            pending.append((line, False))
        else:
            line = model(**{parent_field: document}, line_no=next_no, **values)
            next_no += 1
            pending.append((line, True))
    for line_id, line in existing.items():
        if line_id in keep:
            continue
        log_change(
            _actor(actor),
            document,
            AuditLog.Action.UPDATE,
            {"line": [snapshot(line), None]},
            f"Satır {line.line_no} kaldırıldı (taslak)",
        )
        line.delete()
    for line, _is_new in pending:
        prepare(line)
        line.full_clean(exclude=["created_by", "updated_by", parent_field, "line_no"])
        save_with_audit(line, actor)


# --- mal kabul -------------------------------------------------------------------------------

RECEIPT_FIELDS = (
    "supplier",
    "receipt_date",
    "delivery_note_no",
    "quarantine_location",
    "storage_location",
    "note",
)
RECEIPT_LINE_FIELDS = (
    "material",
    "quantity",
    "unit",
    "supplier_lot_no",
    "manufactured_at",
    "expiry_date",
    "unit_price",
)


def _validate_receipt(receipt: GoodsReceipt) -> None:
    _require_active(receipt.supplier, "tedarikçi")
    quarantine = receipt.quarantine_location
    if quarantine is not None:
        _require_active(quarantine, "lokasyon")
        if quarantine.location_type != Location.Type.QUARANTINE:
            raise BusinessRuleError(
                "invalid_quarantine_location", "Karantina lokasyonu “Karantina” türünde olmalıdır."
            )
    storage = receipt.storage_location
    if storage is not None:
        _require_active(storage, "lokasyon")
        if storage.location_type == Location.Type.QUARANTINE:
            raise BusinessRuleError(
                "invalid_storage_location", "Depo lokasyonu karantina türünde olamaz."
            )


def _validate_receipt_line(line: GoodsReceiptLine) -> None:
    material = line.material
    _require_active(material, "malzeme")
    _require_active(line.unit, "birim")
    if material.material_type not in RECEIVABLE_TYPES:
        raise BusinessRuleError(
            "receipt_material_type",
            f"{material.code}: mal kabulde yalnızca hammadde ve ambalaj alınır.",
        )
    if line.quantity is None or line.quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    # Birim temel birime çevrilebilmeli (yoksa no_conversion).
    masterdata.to_base_quantity(material, line.quantity, line.unit)
    if line.manufactured_at and line.expiry_date and line.expiry_date < line.manufactured_at:
        raise BusinessRuleError(
            "invalid_expiry_date", "Son kullanma tarihi üretim tarihinden önce olamaz."
        )


@transaction.atomic
def create_goods_receipt(
    actor: User | None, data: Mapping[str, Any], lines: Iterable[Mapping[str, Any]] = ()
) -> GoodsReceipt:
    """Taslak mal kabul açar (`MK-` numaralı); satırlar birlikte verilebilir."""
    receipt = GoodsReceipt(**_pick(data, RECEIPT_FIELDS))
    _validate_receipt(receipt)
    create_document(receipt, actor, prefix="MK", machine=goods_receipt_states)
    _sync_lines(
        actor,
        receipt,
        receipt.lines,
        GoodsReceiptLine,
        "receipt",
        lines,
        RECEIPT_LINE_FIELDS,
        _validate_receipt_line,
    )
    return receipt


@transaction.atomic
def update_goods_receipt(
    actor: User | None,
    receipt: GoodsReceipt,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]] | None = None,
) -> GoodsReceipt:
    """Taslak mal kabulün başlığını günceller; `lines` verilirse satırları onunla eşitler
    (`id`'li satır güncellenir, yenisi eklenir, listede olmayan kaldırılır)."""
    values = _pick(data, RECEIPT_FIELDS)
    receipt = _lock_document(receipt)
    _require_draft(receipt, goods_receipt_states)
    for name, value in values.items():
        setattr(receipt, name, value)
    _validate_receipt(receipt)
    save_with_audit(receipt, actor)
    if lines is not None:
        _sync_lines(
            actor,
            receipt,
            receipt.lines,
            GoodsReceiptLine,
            "receipt",
            lines,
            RECEIPT_LINE_FIELDS,
            _validate_receipt_line,
        )
    return receipt


@transaction.atomic
def post_goods_receipt(actor: User | None, receipt: GoodsReceipt) -> GoodsReceipt:
    """Mal kabulü kaydeder: her satır için lot açılır ve `RECEIPT` hareketiyle stoka alınır.

    Giriş kontrolü gereken malzemenin lotu `QUARANTINE` olarak karantina lokasyonuna, gerekmeyen
    `RELEASED` olarak depo lokasyonuna alınır. Miktar temel birime çevrilir. SKT verilmezse üretim
    tarihi (yoksa kabul tarihi) + raf ömrü; SKT'si kabul tarihinden önce olan malzeme alınmaz.
    Olay: `goods_receipt.posted` (oluşan lotlarla).
    """
    actor = _actor(actor)
    receipt = _lock_document(receipt)
    goods_receipt_states.assert_can_transition(receipt.status, GoodsReceipt.Status.POSTED)
    _validate_receipt(receipt)
    lines = list(receipt.lines.select_related("material__base_unit", "unit").order_by("line_no"))
    if not lines:
        raise BusinessRuleError("document_empty", "Satırı olmayan mal kabul kaydedilemez.")
    lots = []
    for line in lines:
        _validate_receipt_line(line)
        material = line.material
        base_quantity = quantize(masterdata.to_base_quantity(material, line.quantity, line.unit))
        if base_quantity <= 0:
            raise BusinessRuleError(
                "quantity_too_small", f"Satır {line.line_no}: miktar temel birimde sıfıra iniyor."
            )
        requires_qc = material.requires_incoming_qc
        location = receipt.quarantine_location if requires_qc else receipt.storage_location
        if location is None:
            raise BusinessRuleError(
                "receipt_location_required",
                f"Satır {line.line_no} ({material.code}) için "
                + ("karantina" if requires_qc else "depo")
                + " lokasyonu seçilmelidir.",
            )
        expiry = line.expiry_date or default_expiry_date(
            material, line.manufactured_at or receipt.receipt_date
        )
        if expiry is not None and expiry < receipt.receipt_date:
            raise BusinessRuleError(
                "lot_already_expired",
                f"Satır {line.line_no} ({material.code}): son kullanma tarihi geçmiş malzeme "
                "kabul edilemez.",
            )
        lot = create_lot(
            actor,
            material=material,
            source=Lot.Source.PURCHASE,
            status=Lot.Status.QUARANTINE if requires_qc else Lot.Status.RELEASED,
            supplier=receipt.supplier,
            supplier_lot_no=line.supplier_lot_no,
            manufactured_at=line.manufactured_at,
            expiry_date=expiry,
            day=receipt.receipt_date,
            note=f"Mal kabul {receipt.number}",
        )
        post_movement(actor, material, lot, location, base_quantity, MovementType.RECEIPT, receipt)
        line.base_quantity = base_quantity
        line.created_lot = lot
        line.save(update_fields=["base_quantity", "created_lot", "updated_at"])
        lots.append(lot_payload(lot, requires_qc=requires_qc))
    receipt.posted_at = timezone.now()
    receipt.posted_by = actor
    receipt.save(update_fields=["posted_at", "posted_by"])
    return transition_status(
        receipt,
        GoodsReceipt.Status.POSTED,
        actor,
        machine=goods_receipt_states,
        event_payload={"lots": lots},
    )


@transaction.atomic
def cancel_goods_receipt(actor: User | None, receipt: GoodsReceipt, reason: str) -> GoodsReceipt:
    """Taslak mal kabulü iptal eder (neden zorunlu). Kaydedilmiş mal kabul iptal edilmez."""
    return cancel_document(receipt, actor, reason=reason, machine=goods_receipt_states)


# --- sayım düzeltme (Karar D-3: depo onaylar) ------------------------------------------------

ADJUSTMENT_FIELDS = ("adjustment_date", "note")
ADJUSTMENT_LINE_FIELDS = ("lot", "location", "counted_quantity", "reason")


def _prepare_adjustment_line(line: StockAdjustmentLine) -> None:
    if not line.reason or not line.reason.strip():
        raise BusinessRuleError("reason_required", "Her sayım satırında neden girilmelidir.")
    line.reason = line.reason.strip()
    if line.counted_quantity is None or line.counted_quantity < 0:
        raise BusinessRuleError("invalid_quantity", "Sayılan miktar negatif olamaz.")
    line.counted_quantity = quantize(line.counted_quantity)
    line.system_quantity = current_balance(line.lot, line.location)
    line.difference = line.counted_quantity - line.system_quantity


def _check_duplicate_counts(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    items = list(items)
    seen: set[tuple[Any, Any]] = set()
    for item in items:
        lot, location = item.get("lot"), item.get("location")
        if lot is None or location is None:
            continue
        key = (lot.pk, location.pk)
        if key in seen:
            raise BusinessRuleError(
                "duplicate_count_line",
                f"{lot.lot_no} lotu {location.code} lokasyonunda belgede bir kez sayılır.",
            )
        seen.add(key)
    return items


@transaction.atomic
def create_stock_adjustment(
    actor: User | None, data: Mapping[str, Any], lines: Iterable[Mapping[str, Any]] = ()
) -> StockAdjustment:
    """Taslak sayım düzeltme açar (`SD-` numaralı). Satırda lot, lokasyon, sayılan miktar ve
    neden; sistem miktarı ve fark bilgi amaçlı doldurulur."""
    lines = _check_duplicate_counts(lines)
    adjustment = StockAdjustment(**_pick(data, ADJUSTMENT_FIELDS))
    create_document(adjustment, actor, prefix="SD", machine=stock_adjustment_states)
    _sync_lines(
        actor,
        adjustment,
        adjustment.lines,
        StockAdjustmentLine,
        "adjustment",
        lines,
        ADJUSTMENT_LINE_FIELDS,
        _prepare_adjustment_line,
    )
    return adjustment


@transaction.atomic
def update_stock_adjustment(
    actor: User | None,
    adjustment: StockAdjustment,
    data: Mapping[str, Any],
    lines: Iterable[Mapping[str, Any]] | None = None,
) -> StockAdjustment:
    """Taslak sayım düzeltmeyi günceller; `lines` verilirse satırları onunla eşitler."""
    values = _pick(data, ADJUSTMENT_FIELDS)
    adjustment = _lock_document(adjustment)
    _require_draft(adjustment, stock_adjustment_states)
    for name, value in values.items():
        setattr(adjustment, name, value)
    save_with_audit(adjustment, actor)
    if lines is not None:
        lines = _check_duplicate_counts(lines)
        _sync_lines(
            actor,
            adjustment,
            adjustment.lines,
            StockAdjustmentLine,
            "adjustment",
            lines,
            ADJUSTMENT_LINE_FIELDS,
            _prepare_adjustment_line,
        )
    return adjustment


@transaction.atomic
def post_stock_adjustment(actor: User | None, adjustment: StockAdjustment) -> StockAdjustment:
    """Sayım düzeltmeyi kaydeder (onaylar). Rol: depo (Karar D-3; ayrı yönetim onayı yok).

    Her satırda sistem miktarı o anki bakiyeyle (kilitlenerek) yeniden okunur; fark sıfır değilse
    `ADJUSTMENT` hareketi yazılır. Olay: `stock_adjustment.posted`.
    """
    actor = _actor(actor)
    adjustment = _lock_document(adjustment)
    stock_adjustment_states.assert_can_transition(adjustment.status, StockAdjustment.Status.POSTED)
    lines = list(
        adjustment.lines.select_related("lot__material__base_unit", "location").order_by("line_no")
    )
    if not lines:
        raise BusinessRuleError("document_empty", "Satırı olmayan sayım düzeltme kaydedilemez.")
    for line in lines:
        lot = line.lot
        balance = _lock_balance(lot.material, lot, line.location)
        line.system_quantity = balance.quantity
        line.difference = line.counted_quantity - balance.quantity
        if line.difference != 0:
            line.movement = post_movement(
                actor,
                lot.material,
                lot,
                line.location,
                line.difference,
                MovementType.ADJUSTMENT,
                adjustment,
                line.reason,
            )
        line.save(update_fields=["system_quantity", "difference", "movement", "updated_at"])
    adjustment.posted_at = timezone.now()
    adjustment.posted_by = actor
    adjustment.save(update_fields=["posted_at", "posted_by"])
    return transition_status(
        adjustment, StockAdjustment.Status.POSTED, actor, machine=stock_adjustment_states
    )


@transaction.atomic
def cancel_stock_adjustment(
    actor: User | None, adjustment: StockAdjustment, reason: str
) -> StockAdjustment:
    """Taslak sayım düzeltmeyi iptal eder (neden zorunlu)."""
    return cancel_document(adjustment, actor, reason=reason, machine=stock_adjustment_states)


# --- açılış stoku ----------------------------------------------------------------------------


@transaction.atomic
def post_opening_balance(
    actor: User | None,
    *,
    material: Material,
    lot_no: str,
    location: Location,
    quantity: Decimal,
    unit: UnitOfMeasure | None = None,
    expiry_date: date | None = None,
    manufactured_at: date | None = None,
    supplier_lot_no: str = "",
    status: str = Lot.Status.RELEASED,
) -> StockMovement:
    """Sistem öncesi stoku açılış hareketiyle (`OPENING`) yazar.

    Lot yoksa `OPENING` kaynaklı açılır (varsayılan serbest; karantina da seçilebilir). Aynı açılış
    lotu başka lokasyonlara da eklenebilir; başka kaynaktan gelmiş bir lota açılış yapılamaz.
    """
    _require_active(material, "malzeme")
    _require_active(location, "lokasyon")
    if status not in OPENING_STATUSES:
        raise BusinessRuleError(
            "invalid_opening_status", "Açılış stoku serbest ya da karantina olarak girilir."
        )
    base_quantity = quantize(
        masterdata.to_base_quantity(material, quantity, unit or material.base_unit)
    )
    if base_quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    lot_no = lot_no.strip().upper()
    if not lot_no:
        raise BusinessRuleError("lot_no_required", "Lot numarası girilmelidir.")
    lot = Lot.objects.select_for_update().filter(material=material, lot_no=lot_no).first()
    if lot is None:
        lot = create_lot(
            actor,
            material=material,
            source=Lot.Source.OPENING,
            lot_no=lot_no,
            status=status,
            supplier_lot_no=supplier_lot_no,
            manufactured_at=manufactured_at,
            expiry_date=expiry_date,
            note="Açılış stoku",
        )
    elif lot.source != Lot.Source.OPENING:
        raise BusinessRuleError(
            "lot_exists", f"{material.code} malzemesinde {lot_no} lotu zaten var."
        )
    elif expiry_date is not None and lot.expiry_date != expiry_date:
        raise BusinessRuleError(
            "lot_expiry_mismatch",
            f"{lot_no} lotu sistemde farklı son kullanma tarihiyle kayıtlı.",
        )
    return post_movement(
        actor,
        material,
        lot,
        location,
        base_quantity,
        MovementType.OPENING,
        None,
        "Açılış stoku",
    )
