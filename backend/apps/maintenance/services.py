"""Bakım servisleri (Faz 4, Adım 4.4).

Kurallar:
- Bakım planı gün ya da çalışma sayısı periyotludur. Günlük kontrolde (07:00) vadesi gelen ve açık
  iş emri olmayan plan için `BK-` iş emri açılır, sorumlu role görev düşer; termini geçen plan
  yönetime bildirilir. İş emri tamamlanınca plan ileri atar (gün bazlıda tamamlanma günü + periyot).
- Arıza bildirimi bir onarım iş emri açar, istenirse duruşu başlatır; iş emri tamamlanınca ona bağlı
  açık duruş kapanır. Başarısız kalibrasyon teraziye duruş açar.
- Ekipman kancası (`masterdata.check_equipment`): açık duruştaki ekipman emre atanamaz, şarj /
  dolum partisi başlatılamaz, terazide tartım yapılamaz (`equipment_down`). Tankta farklı ürüne
  geçişte temizlik kaydı zorunludur (`cleaning_required`, Karar D-14 "İstisnalı"). Kalibrasyonu
  geçmiş terazide tartım yapılamaz (`calibration_overdue`), yaklaşan kalibrasyon uyarı döner.
- Stoklu yedek parça `ISSUE_MAINTENANCE` hareketiyle (serbest lottan) düşülür.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.core import event_names as ev
from apps.core import events
from apps.core.audit import log_change
from apps.core.exceptions import BusinessRuleError
from apps.core.models import AuditLog, User
from apps.core.permissions import user_has_role
from apps.core.roles import (
    ALL_ROLES,
    DOLUM,
    LABORATUVAR,
    PLANLAMA,
    URETIM,
    YONETIM,
)
from apps.core.services import cancel_document, create_document, save_with_audit, transition_status
from apps.inventory import services as inventory
from apps.inventory.models import Lot, StockMovement
from apps.inventory.services import quantize
from apps.maintenance import selectors
from apps.maintenance.models import (
    ChangeoverRule,
    Downtime,
    MaintenanceKind,
    MaintenancePlan,
    MaintenanceSettings,
    MaintenanceWorkOrder,
    WorkOrderPart,
)
from apps.maintenance.state import work_order_states
from apps.masterdata import services as masterdata
from apps.masterdata.models import Equipment, Location, Material

Status = MaintenanceWorkOrder.Status
Source = MaintenanceWorkOrder.Source

# Planları sorumlu birimler ve yönetim yönetir.
PLAN_ROLES = (URETIM, DOLUM, LABORATUVAR, YONETIM)
# Duruşu üretim, dolum, laboratuvar (terazi), planlama ve yönetim girer.
DOWNTIME_ROLES = (URETIM, DOLUM, LABORATUVAR, PLANLAMA, YONETIM)
# Arızayı herkes bildirir.
BREAKDOWN_ROLES = ALL_ROLES
# Temizliksiz geçiş kurallarını kalite birimi tanımlar (Karar D-14).
CHANGEOVER_ROLES = (LABORATUVAR,)
SETTINGS_ROLES = (YONETIM,)
# Okuma: bakımla ilgili tüm birimler.
READ_ROLES = (URETIM, DOLUM, LABORATUVAR, PLANLAMA, YONETIM)

PLAN_FIELDS = (
    "equipment",
    "kind",
    "title",
    "interval_days",
    "interval_runs",
    "checklist",
    "responsible_role",
    "next_due_date",
    "note",
)
WORK_ORDER_FIELDS = (
    "equipment",
    "kind",
    "title",
    "description",
    "responsible_role",
    "due_date",
    "checklist",
)
PLAN_KINDS = (MaintenanceKind.PERIODIC, MaintenanceKind.CLEANING, MaintenanceKind.CALIBRATION)
SETTINGS_FIELDS = ("calibration_warning_days", "plan_lead_days")


def _actor(actor: User | None) -> User | None:
    return actor if actor is not None and actor.is_authenticated else None


def _require_role(actor: User | None, roles: Sequence[str], message: str) -> None:
    if not user_has_role(actor, tuple(roles)):
        raise PermissionDenied(message)


def _pick(data: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(f"Tanımsız alan: {', '.join(sorted(unknown))}")
    return dict(data)


def default_role(equipment: Equipment, kind: str) -> str:
    """Ekipman türüne göre sorumlu rol: kalibrasyon laboratuvar, dolum hattı dolum, diğerleri
    üretim."""
    if kind == MaintenanceKind.CALIBRATION:
        return LABORATUVAR
    if equipment.equipment_type == Equipment.Type.FILLING_LINE:
        return DOLUM
    return URETIM


def _clean_checklist(items: Any) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise BusinessRuleError("invalid_checklist", "Kontrol listesi madde listesi olmalıdır.")
    result = [str(item).strip() for item in items]
    return [item for item in result if item]


def _checklist_rows(items: list[str]) -> list[dict[str, Any]]:
    return [{"item": item, "done": False, "note": ""} for item in items]


# --- ayarlar -----------------------------------------------------------------------------------


@transaction.atomic
def update_settings(actor: User, data: Mapping[str, Any]) -> MaintenanceSettings:
    """Kalibrasyon uyarı süresini ve iş emri açma süresini günceller (rol: yonetim)."""
    _require_role(actor, SETTINGS_ROLES, "Bakım ayarlarını yalnızca yönetim değiştirir.")
    instance = MaintenanceSettings.objects.select_for_update().get(pk=selectors.get_settings().pk)
    for name, value in _pick(data, SETTINGS_FIELDS).items():
        setattr(instance, name, value)
    return save_with_audit(instance, actor)


# --- bakım planı -------------------------------------------------------------------------------


def _validate_plan(plan: MaintenancePlan) -> None:
    equipment = plan.equipment
    if not equipment.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif ekipman seçilemez: {equipment}.")
    if plan.kind not in PLAN_KINDS:
        raise BusinessRuleError(
            "invalid_kind", "Plan türü periyodik, temizlik ya da kalibrasyon olmalı."
        )
    if (plan.interval_days is None) == (plan.interval_runs is None):
        raise BusinessRuleError(
            "invalid_interval", "Periyot gün ya da çalışma sayısı olarak girilmelidir."
        )
    if any(value is not None and value <= 0 for value in (plan.interval_days, plan.interval_runs)):
        raise BusinessRuleError("invalid_interval", "Periyot sıfırdan büyük olmalıdır.")
    if plan.kind == MaintenanceKind.CALIBRATION:
        if equipment.equipment_type != Equipment.Type.SCALE:
            raise BusinessRuleError(
                "calibration_scale_only", "Kalibrasyon planı yalnızca terazi için açılır."
            )
        if plan.interval_days is None:
            raise BusinessRuleError(
                "calibration_days_only", "Kalibrasyon periyodu gün olarak girilmelidir."
            )
    if plan.interval_runs is not None and equipment.equipment_type not in (
        Equipment.Type.MIXING_TANK,
        Equipment.Type.STORAGE_TANK,
        Equipment.Type.FILLING_LINE,
    ):
        raise BusinessRuleError(
            "runs_interval_unsupported",
            "Çalışma sayısı periyodu yalnızca tank ve dolum hattında kullanılır.",
        )
    if plan.interval_days is not None and plan.next_due_date is None:
        plan.next_due_date = timezone.localdate() + timedelta(days=plan.interval_days)
    if plan.interval_runs is not None:
        plan.next_due_date = None
    plan.checklist = _clean_checklist(plan.checklist)
    if not plan.title.strip():
        raise BusinessRuleError("title_required", "Plan başlığı girilmelidir.")
    plan.title = plan.title.strip()


@transaction.atomic
def create_plan(actor: User, data: Mapping[str, Any]) -> MaintenancePlan:
    """Bakım planı açar (rol: üretim, dolum, laboratuvar, yönetim). Sorumlu rol verilmezse ekipman
    türünden seçilir; gün bazlı planda sıradaki tarih verilmezse bugün + periyottur."""
    _require_role(actor, PLAN_ROLES, "Bakım planını yalnızca bakımdan sorumlu birimler açar.")
    values = _pick(data, PLAN_FIELDS)
    plan = MaintenancePlan(**values)
    if not plan.responsible_role:
        plan.responsible_role = default_role(plan.equipment, plan.kind)
    _validate_plan(plan)
    return save_with_audit(plan, actor)


@transaction.atomic
def update_plan(actor: User, plan: MaintenancePlan, data: Mapping[str, Any]) -> MaintenancePlan:
    """Planı günceller (eski → yeni değerler denetim günlüğüne)."""
    _require_role(actor, PLAN_ROLES, "Bakım planını yalnızca bakımdan sorumlu birimler değiştirir.")
    values = _pick(data, PLAN_FIELDS)
    locked = MaintenancePlan.objects.select_for_update().get(pk=plan.pk)
    for name, value in values.items():
        setattr(locked, name, value)
    _validate_plan(locked)
    return save_with_audit(locked, actor)


@transaction.atomic
def set_plan_active(
    actor: User, plan: MaintenancePlan, active: bool, note: str = ""
) -> MaintenancePlan:
    """Planı aktif / pasif yapar (planlar silinmez)."""
    _require_role(actor, PLAN_ROLES, "Bakım planını yalnızca bakımdan sorumlu birimler değiştirir.")
    return masterdata.set_active(actor, plan, active, note=note)


# --- iş emri -----------------------------------------------------------------------------------


def _work_order_payload(order: MaintenanceWorkOrder, *, open_task: bool = True) -> dict[str, Any]:
    return {
        "equipment_id": order.equipment_id,
        "equipment_code": order.equipment.code,
        "equipment_name": order.equipment.name,
        "title": order.title,
        "kind": order.kind,
        "kind_display": order.get_kind_display(),
        "source": order.source,
        "responsible_role": order.responsible_role,
        "due_date": order.due_date.isoformat() if order.due_date else "",
        "open_task": open_task,
    }


def _can_work(actor: User | None, order: MaintenanceWorkOrder) -> None:
    _require_role(
        actor,
        (order.responsible_role, YONETIM),
        "Bu iş emrini yalnızca sorumlu birim ya da yönetim yürütür.",
    )


def _lock(order: MaintenanceWorkOrder) -> MaintenanceWorkOrder:
    return (
        MaintenanceWorkOrder.objects.select_for_update(of=("self",))
        .select_related("equipment", "plan")
        .get(pk=order.pk)
    )


def _new_work_order(
    actor: User | None,
    *,
    equipment: Equipment,
    kind: str,
    source: str,
    title: str,
    description: str = "",
    responsible_role: str = "",
    due_date: date | None = None,
    checklist: list[str] | None = None,
    plan: MaintenancePlan | None = None,
    previous_product: Material | None = None,
    open_task: bool = True,
) -> MaintenanceWorkOrder:
    if not equipment.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif ekipman seçilemez: {equipment}.")
    title = (title or "").strip()
    if not title:
        raise BusinessRuleError("title_required", "İş emri başlığı girilmelidir.")
    order = MaintenanceWorkOrder(
        equipment=equipment,
        plan=plan,
        source=source,
        kind=kind,
        title=title,
        description=(description or "").strip(),
        responsible_role=responsible_role or default_role(equipment, kind),
        due_date=due_date,
        checklist=_checklist_rows(_clean_checklist(checklist)),
        previous_product=previous_product,
    )
    return create_document(
        order,
        actor,
        prefix="BK",
        machine=work_order_states,
        event_payload=_work_order_payload(order, open_task=open_task),
    )


@transaction.atomic
def create_work_order(actor: User, data: Mapping[str, Any]) -> MaintenanceWorkOrder:
    """Elle bakım iş emri açar (rol: planları yöneten birimler)."""
    _require_role(actor, PLAN_ROLES, "Bakım iş emrini yalnızca bakımdan sorumlu birimler açar.")
    values = _pick(data, WORK_ORDER_FIELDS)
    return _new_work_order(
        _actor(actor),
        equipment=values["equipment"],
        kind=values.get("kind") or MaintenanceKind.PERIODIC,
        source=Source.MANUAL,
        title=values.get("title", ""),
        description=values.get("description", ""),
        responsible_role=values.get("responsible_role", ""),
        due_date=values.get("due_date"),
        checklist=values.get("checklist"),
    )


@transaction.atomic
def report_breakdown(
    actor: User,
    equipment: Equipment,
    description: str,
    *,
    stop_equipment: bool = True,
) -> MaintenanceWorkOrder:
    """Arıza bildirir (her rol): onarım iş emri açılır; `stop_equipment` ise ekipmanda arıza
    duruşu başlar (açık duruş varsa yenisi açılmaz, iş emrine bağlanır)."""
    _require_role(actor, BREAKDOWN_ROLES, "Arıza bildirmek için bir rolünüz olmalı.")
    real = _actor(actor)
    description = (description or "").strip()
    if not description:
        raise BusinessRuleError("description_required", "Arıza açıklaması girilmelidir.")
    order = _new_work_order(
        real,
        equipment=equipment,
        kind=MaintenanceKind.REPAIR,
        source=Source.BREAKDOWN,
        title=f"Arıza: {equipment.name}",
        description=description,
        due_date=timezone.localdate(),
    )
    if stop_equipment:
        existing = (
            Downtime.objects.select_for_update()
            .filter(equipment=equipment, ended_at__isnull=True)
            .first()
        )
        if existing is None:
            _start_downtime(
                real, equipment, Downtime.Reason.BREAKDOWN, note=description, work_order=order
            )
        elif existing.work_order_id is None:
            existing.work_order = order
            save_with_audit(existing, real)
    return order


@transaction.atomic
def start_work_order(actor: User, order: MaintenanceWorkOrder) -> MaintenanceWorkOrder:
    """İşe başlar (sorumlu rol ya da yönetim)."""
    _can_work(actor, order)
    actor_ = _actor(actor)
    order = _lock(order)
    work_order_states.assert_can_transition(order.status, Status.IN_PROGRESS)
    order.started_at = timezone.now()
    order.started_by = actor_
    order.save(update_fields=["started_at", "started_by"])
    return transition_status(
        order,
        Status.IN_PROGRESS,
        actor_,
        machine=work_order_states,
        event_payload=_work_order_payload(order),
    )


def _merge_checklist(order: MaintenanceWorkOrder, checklist: Any) -> list[dict[str, Any]]:
    """Gelen kontrol listesi işaretlerini iş emrindeki maddelerle birleştirir; tüm maddeler
    işaretlenmelidir."""
    rows = [dict(row) for row in order.checklist]
    if checklist is not None:
        if not isinstance(checklist, list) or len(checklist) != len(rows):
            raise BusinessRuleError(
                "invalid_checklist", "Kontrol listesi iş emrindeki maddelerle aynı olmalıdır."
            )
        for row, given in zip(rows, checklist, strict=True):
            row["done"] = bool(given.get("done"))
            row["note"] = str(given.get("note") or "").strip()
    missing = [row["item"] for row in rows if not row["done"]]
    if missing:
        raise BusinessRuleError(
            "checklist_incomplete",
            f"Kontrol listesinde işaretlenmemiş madde var: {', '.join(missing)}.",
        )
    return rows


def _advance_plan(actor: User | None, plan: MaintenancePlan, done_at: datetime) -> None:
    plan = MaintenancePlan.objects.select_for_update().get(pk=plan.pk)
    before = {"last_done_at": plan.last_done_at, "next_due_date": plan.next_due_date}
    plan.last_done_at = done_at
    if plan.interval_days is not None:
        plan.next_due_date = timezone.localdate(done_at) + timedelta(days=plan.interval_days)
    plan.updated_by = actor
    plan.save(update_fields=["last_done_at", "next_due_date", "updated_by", "updated_at"])
    log_change(
        actor,
        plan,
        AuditLog.Action.UPDATE,
        {
            "last_done_at": [str(before["last_done_at"]), str(plan.last_done_at)],
            "next_due_date": [str(before["next_due_date"]), str(plan.next_due_date)],
        },
        "İş emri tamamlandı",
    )


@transaction.atomic
def complete_work_order(
    actor: User,
    order: MaintenanceWorkOrder,
    *,
    work_done: str,
    duration_minutes: int | None = None,
    checklist: Any = None,
    calibration_result: str = "",
    certificate_no: str = "",
) -> MaintenanceWorkOrder:
    """İş emrini tamamlar (sorumlu rol ya da yönetim): yapılan iş zorunlu, kontrol listesi tam
    olmalı. Kalibrasyonda sonuç zorunludur; "Uygun değil" teraziye kalibrasyon duruşu açar ve plan
    ileri atmaz. Plan kaynaklı iş emri planı ileri atar; iş emrine bağlı açık duruşlar kapanır."""
    _can_work(actor, order)
    actor_ = _actor(actor)
    order = _lock(order)
    work_order_states.assert_can_transition(order.status, Status.COMPLETED)
    work_done = (work_done or "").strip()
    if not work_done:
        raise BusinessRuleError("work_done_required", "Yapılan iş girilmelidir.")
    if duration_minutes is not None and duration_minutes < 0:
        raise BusinessRuleError("invalid_duration", "Süre negatif olamaz.")
    rows = _merge_checklist(order, checklist)
    result = calibration_result or ""
    if order.kind == MaintenanceKind.CALIBRATION:
        if result not in MaintenanceWorkOrder.CalibrationResult.values:
            raise BusinessRuleError(
                "calibration_result_required", "Kalibrasyon sonucu (uygun / uygun değil) seçilmeli."
            )
    else:
        result = ""
    now = timezone.now()
    order.checklist = rows
    order.work_done = work_done
    order.duration_minutes = duration_minutes
    order.calibration_result = result
    order.certificate_no = (certificate_no or "").strip()
    order.completed_at = now
    order.completed_by = actor_
    if order.started_at is None:
        order.started_at = now
        order.started_by = actor_
    order.save(
        update_fields=[
            "checklist",
            "work_done",
            "duration_minutes",
            "calibration_result",
            "certificate_no",
            "completed_at",
            "completed_by",
            "started_at",
            "started_by",
        ]
    )
    failed = result == MaintenanceWorkOrder.CalibrationResult.FAILED
    if order.plan is not None and not failed:
        _advance_plan(actor_, order.plan, now)
    for downtime in Downtime.objects.select_for_update().filter(
        work_order=order, ended_at__isnull=True
    ):
        _end_downtime(actor_, downtime, now, f"{order.number} tamamlandı")
    transition_status(
        order,
        Status.COMPLETED,
        actor_,
        machine=work_order_states,
        event_payload=_work_order_payload(order),
    )
    if failed and selectors.open_downtime(order.equipment) is None:
        _start_downtime(
            actor_,
            order.equipment,
            Downtime.Reason.CALIBRATION,
            note=f"{order.number}: kalibrasyon uygun değil. {work_done}",
        )
    return order


@transaction.atomic
def cancel_work_order(
    actor: User, order: MaintenanceWorkOrder, reason: str
) -> MaintenanceWorkOrder:
    """İş emrini iptal eder (neden zorunlu). Stoktan düşülmüş parça varsa iptal edilemez."""
    _can_work(actor, order)
    order = _lock(order)
    if order.parts.filter(movement__isnull=False).exists():
        raise BusinessRuleError(
            "work_order_has_parts",
            "Stoktan parça düşülmüş iş emri iptal edilemez; iş emrini tamamlayın.",
        )
    return cancel_document(order, _actor(actor), reason=reason, machine=work_order_states)


@transaction.atomic
def record_cleaning(
    actor: User,
    equipment: Equipment,
    *,
    work_done: str,
    checklist: list[str] | None = None,
    duration_minutes: int | None = None,
) -> MaintenanceWorkOrder:
    """Tank temizliği kaydı (rol: üretim, yönetim): tek adımda tamamlanmış temizlik iş emri.
    Kayıt, tankta ürün değişimi temizliği kuralını (Karar D-14) karşılar. Görev açılmaz."""
    _require_role(actor, (URETIM, YONETIM), "Temizlik kaydını üretim girer.")
    if not equipment.is_tank:
        raise BusinessRuleError("cleaning_tank_only", "Temizlik kaydı tanklar için girilir.")
    last = selectors.last_tank_batch(equipment)
    previous = last.order.product if last is not None else None
    items = _clean_checklist(checklist)
    order = _new_work_order(
        _actor(actor),
        equipment=equipment,
        kind=MaintenanceKind.CLEANING,
        source=Source.CHANGEOVER,
        title=f"Ürün değişimi temizliği: {equipment.code}",
        responsible_role=URETIM,
        checklist=items,
        previous_product=previous,
        open_task=False,
    )
    return complete_work_order(
        actor,
        order,
        work_done=work_done,
        duration_minutes=duration_minutes,
        checklist=[{"done": True} for _ in items],
    )


# --- yedek parça -------------------------------------------------------------------------------


@transaction.atomic
def add_part(
    actor: User,
    order: MaintenanceWorkOrder,
    *,
    quantity: Decimal,
    material: Material | None = None,
    lot: Lot | None = None,
    location: Location | None = None,
    description: str = "",
    unit_text: str = "",
) -> WorkOrderPart:
    """İş emrine yedek parça ekler. Malzeme verilirse lot ve lokasyon zorunludur ve parça
    `ISSUE_MAINTENANCE` hareketiyle serbest lottan düşülür (negatif stok olmaz). Stoksuz parça
    için açıklama yeterlidir."""
    _can_work(actor, order)
    actor_ = _actor(actor)
    order = _lock(order)
    if order.status not in selectors.OPEN_STATUSES:
        raise BusinessRuleError("work_order_closed", "Kapanmış iş emrine parça eklenemez.")
    if not isinstance(quantity, Decimal):
        raise TypeError("Miktar Decimal olmalıdır.")
    quantity = quantize(quantity)
    if quantity <= 0:
        raise BusinessRuleError("invalid_quantity", "Miktar sıfırdan büyük olmalıdır.")
    description = (description or "").strip()
    part = WorkOrderPart(
        work_order=order,
        material=material,
        lot=lot,
        location=location,
        description=description,
        quantity=quantity,
        unit_text=(unit_text or "").strip(),
    )
    if material is None:
        if not description:
            raise BusinessRuleError(
                "part_description_required", "Stoksuz parça için açıklama girilmelidir."
            )
        return save_with_audit(part, actor_)
    if lot is None or location is None:
        raise BusinessRuleError(
            "part_lot_required", "Stoklu parça için lot ve lokasyon seçilmelidir."
        )
    movement: StockMovement = inventory.post_movement(
        actor_,
        material,
        lot,
        location,
        -quantity,
        StockMovement.Type.ISSUE_MAINTENANCE,
        order,
        f"Bakım {order.number}",
    )
    part.movement = movement
    part.unit_text = material.base_unit.code
    if not part.description:
        part.description = material.name
    return save_with_audit(part, actor_)


# --- duruş -------------------------------------------------------------------------------------


def downtime_payload(downtime: Downtime) -> dict[str, Any]:
    minutes = None
    if downtime.ended_at is not None:
        minutes = selectors._minutes(downtime.started_at, downtime.ended_at)
    return {
        "model": downtime._meta.label_lower,
        "id": downtime.pk,
        "repr": f"{downtime.equipment.code} duruşu",
        "equipment_id": downtime.equipment_id,
        "equipment_code": downtime.equipment.code,
        "equipment_name": downtime.equipment.name,
        "reason": downtime.reason,
        "reason_display": downtime.get_reason_display(),
        "started_at": timezone.localtime(downtime.started_at).strftime("%d.%m.%Y %H:%M"),
        "ended_at": (
            timezone.localtime(downtime.ended_at).strftime("%d.%m.%Y %H:%M")
            if downtime.ended_at
            else ""
        ),
        "minutes": minutes,
        "note": downtime.note,
    }


def _start_downtime(
    actor: User | None,
    equipment: Equipment,
    reason: str,
    *,
    started_at: datetime | None = None,
    note: str = "",
    work_order: MaintenanceWorkOrder | None = None,
) -> Downtime:
    if reason not in Downtime.Reason.values:
        raise BusinessRuleError("invalid_reason", "Duruş nedeni geçersiz.")
    started_at = started_at or timezone.now()
    if started_at > timezone.now() + timedelta(minutes=5):
        raise BusinessRuleError("future_downtime", "Duruş başlangıcı ileri tarihli olamaz.")
    if (
        Downtime.objects.select_for_update()
        .filter(equipment=equipment, ended_at__isnull=True)
        .exists()
    ):
        raise BusinessRuleError("downtime_open", f"{equipment.code} için açık bir duruş zaten var.")
    downtime = save_with_audit(
        Downtime(
            equipment=equipment,
            reason=reason,
            started_at=started_at,
            note=(note or "").strip(),
            work_order=work_order,
        ),
        actor,
    )
    events.publish(ev.DOWNTIME_STARTED, downtime_payload(downtime), actor)
    return downtime


def _end_downtime(
    actor: User | None, downtime: Downtime, ended_at: datetime | None, note: str = ""
) -> Downtime:
    ended_at = ended_at or timezone.now()
    if ended_at < downtime.started_at:
        raise BusinessRuleError("invalid_end", "Duruş bitişi başlangıçtan önce olamaz.")
    downtime.ended_at = ended_at
    downtime.ended_by = actor
    downtime.end_note = (note or "").strip()
    downtime = save_with_audit(downtime, actor)
    events.publish(ev.DOWNTIME_ENDED, downtime_payload(downtime), actor)
    return downtime


@transaction.atomic
def start_downtime(
    actor: User,
    equipment: Equipment,
    reason: str,
    *,
    started_at: datetime | None = None,
    note: str = "",
) -> Downtime:
    """Ekipman duruşu başlatır. Açık duruşta ekipman emre atanamaz ve çalıştırılamaz."""
    _require_role(actor, DOWNTIME_ROLES, "Duruşu yalnızca ilgili birimler girer.")
    if not equipment.is_active:
        raise BusinessRuleError("inactive_reference", f"Pasif ekipman seçilemez: {equipment}.")
    return _start_downtime(_actor(actor), equipment, reason, started_at=started_at, note=note)


@transaction.atomic
def end_downtime(
    actor: User, downtime: Downtime, *, ended_at: datetime | None = None, note: str = ""
) -> Downtime:
    """Açık duruşu bitirir. Açık arıza iş emrine bağlı duruş da elle bitirilebilir."""
    _require_role(actor, DOWNTIME_ROLES, "Duruşu yalnızca ilgili birimler bitirir.")
    locked = Downtime.objects.select_for_update().select_related("equipment").get(pk=downtime.pk)
    if locked.ended_at is not None:
        raise BusinessRuleError("downtime_closed", "Bu duruş zaten bitmiş.")
    return _end_downtime(_actor(actor), locked, ended_at, note)


# --- temizliksiz geçiş kuralları (Karar D-14) ---------------------------------------------------


def _validate_changeover(rule: ChangeoverRule) -> None:
    for product in (rule.from_product, rule.to_product):
        if product.material_type != Material.Type.BULK:
            raise BusinessRuleError(
                "changeover_bulk_only", f"{product.code}: geçiş kuralı dökme ürünler içindir."
            )
    if rule.from_product.pk == rule.to_product.pk:
        raise BusinessRuleError("changeover_same_product", "Aynı ürün için kural gerekmez.")
    duplicate = ChangeoverRule.objects.filter(
        from_product=rule.from_product, to_product=rule.to_product
    ).exclude(pk=rule.pk)
    if duplicate.exists():
        raise BusinessRuleError("duplicate", "Bu geçiş zaten tanımlı.")


@transaction.atomic
def create_changeover_rule(actor: User, data: Mapping[str, Any]) -> ChangeoverRule:
    """Temizliksiz geçiş çifti tanımlar (rol: laboratuvar)."""
    _require_role(actor, CHANGEOVER_ROLES, "Temizliksiz geçişleri kalite birimi tanımlar.")
    rule = ChangeoverRule(**_pick(data, ("from_product", "to_product", "note")))
    _validate_changeover(rule)
    return save_with_audit(rule, actor)


@transaction.atomic
def set_changeover_active(
    actor: User, rule: ChangeoverRule, active: bool, note: str = ""
) -> ChangeoverRule:
    """Kuralı aktif / pasif yapar (silinmez)."""
    _require_role(actor, CHANGEOVER_ROLES, "Temizliksiz geçişleri kalite birimi değiştirir.")
    return masterdata.set_active(actor, rule, active, note=note)


# --- günlük kontrol ----------------------------------------------------------------------------


@transaction.atomic
def create_due_work_orders(today: date | None = None) -> list[MaintenanceWorkOrder]:
    """Vadesi gelen ve açık iş emri olmayan planlar için iş emri açar (sistem işlemi);
    termini geçmiş planları `maintenance.overdue` olayıyla yönetime bildirir."""
    today = today or timezone.localdate()
    created: list[MaintenanceWorkOrder] = []
    overdue: list[dict[str, Any]] = []
    for status in selectors.due_plans(today):
        plan = status.plan
        has_open = plan.work_orders.filter(status__in=selectors.OPEN_STATUSES).exists()
        if not has_open:
            created.append(
                _new_work_order(
                    None,
                    equipment=plan.equipment,
                    kind=plan.kind,
                    source=Source.PLAN,
                    title=plan.title,
                    description=plan.note,
                    responsible_role=plan.responsible_role,
                    due_date=status.next_due_date or today,
                    checklist=plan.checklist,
                    plan=plan,
                )
            )
        if status.is_overdue:
            overdue.append(
                {
                    "equipment_code": plan.equipment.code,
                    "title": plan.title,
                    "next_due_date": status.next_due_date.strftime("%d.%m.%Y")
                    if status.next_due_date
                    else "",
                    "runs_done": status.runs_done,
                }
            )
    if overdue:
        events.publish(
            ev.MAINTENANCE_OVERDUE,
            {
                "model": "maintenance.maintenanceplan",
                "id": 0,
                "repr": "Bakım planları",
                "count": len(overdue),
                "plans": overdue,
            },
        )
    return created


# --- ekipman kancası ---------------------------------------------------------------------------


@masterdata.register_equipment_guard
def equipment_guard(equipment: Equipment, use: str, context: Mapping[str, Any]) -> list[str]:
    """Üretim ve dolumun ekipman kontrolü (bkz. modül açıklaması)."""
    downtime = selectors.open_downtime(equipment)
    if downtime is not None:
        since = timezone.localtime(downtime.started_at).strftime("%d.%m.%Y %H:%M")
        raise BusinessRuleError(
            "equipment_down",
            f"{equipment.code} {since} itibarıyla duruşta ({downtime.get_reason_display()}); "
            "duruş bitmeden kullanılamaz.",
        )
    warnings: list[str] = []
    product = context.get("product")
    if use == masterdata.EQUIPMENT_START and equipment.is_tank and product is not None:
        previous = selectors.cleaning_needed(equipment, product)
        if previous is not None:
            raise BusinessRuleError(
                "cleaning_required",
                f"{equipment.code} tankında son üretilen ürün {previous.code}; {product.code} "
                "için önce temizlik kaydı girilmelidir.",
            )
    if use == masterdata.EQUIPMENT_WEIGH and equipment.equipment_type == Equipment.Type.SCALE:
        status = selectors.scale_calibration(equipment)
        if status.status == selectors.CAL_OVERDUE:
            assert status.next_due_date is not None
            raise BusinessRuleError(
                "calibration_overdue",
                f"{equipment.code} terazisinin kalibrasyon tarihi "
                f"{status.next_due_date:%d.%m.%Y} geçti; bu teraziyle tartım yapılamaz.",
            )
        if status.status == selectors.CAL_DUE_SOON:
            warnings.append(
                f"{equipment.code} terazisinin kalibrasyonu {status.days_left} gün içinde doluyor."
            )
    return warnings


def format_minutes(minutes: int) -> str:
    """Dakikayı `3 sa 20 dk` biçiminde yazar."""
    hours, rest = divmod(minutes, 60)
    return f"{hours} sa {rest} dk" if hours else f"{rest} dk"
