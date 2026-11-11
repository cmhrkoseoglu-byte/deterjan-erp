"""Sonda: iş akışı kuralları, görevler ve bildirimler (plan §5.5 2. parça, §5.7).

`workflow.rules.RULES`'taki her kural temsilî bir yükle `services.process_event`'e verilir (olay
dinleyicisinin çağırdığı işlev, `workflow/handlers.py`). Her persona için dondurulanlar:

- görev kuralı: "Yeni görev" bildirimini alır mı; görev açılınca anlık mesaj (WebSocket) gelir mi;
  görev listesinde ve Görevlerim'de (`?mine=true`) görünür mü; `can_act`; açıklama ve bildirim
  metni tam mı; üstlenme ve tamamlama yanıtı; üstlenince anlık mesajın kitlesi; görevi kendisi
  üstlenmiş (sonra rolünü kaybetmiş) olsa listede görür ve tamamlar mı;
- bildirim kuralı: bildirimi alır mı; yükten gelen kişi (siparişi açan, raporu isteyen) kendisi
  olsa alır mı;
- iptal kuralı: açık görev yokken ve kayda bağlı her görev kuralının açık göreviyle iptal
  bildirimini alır mı; iptal edilen görevi kendisi üstlenmişse alır mı;
- olayı yapan kişi (actor) kendisi olsa bildirimi alır mı (yalnız alıcılarda, diğerleri `-`);
- bildirimler: liste, okunmamış sayısı ve okundu işaretleme.

Kararlar API yanıtlarından, bildirim kayıtlarından ve kanal katmanına giden mesajlardan okunur.
Dosyada her durum tek satırdır: değerler PERSONAS sırasıyla, kısaltmalar `_codes`'ta.
"""

import logging
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields
from itertools import count
from typing import Any

import pytest
from channels.layers import get_channel_layer
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from pytest_django import DjangoCaptureOnCommitCallbacks
from rest_framework.test import APIClient

from apps.core import events
from apps.core.models import User
from apps.core.tests.access_contract import snapshot
from apps.core.tests.access_contract.personas import PERSONAS, make_personas, persona_client
from apps.workflow import realtime, rules, services
from apps.workflow.models import Notification, Task

NAME = "probe_workflow"
TASKS = "/api/v1/workflow/tasks/"
NOTIFICATIONS = "/api/v1/workflow/notifications/"
ALL_ROWS: dict[str, str | int] = {"page_size": 500}

# Bugünkü kural tablosu. Kural eklenir ya da çıkarsa sayılar, PAYLOADS ve anlık görüntü birlikte
# güncellenir (sahibin onayıyla).
RULE_COUNTS = {"TaskRule": 25, "NotifyRule": 27, "CancelTasksRule": 5}

Payload = dict[str, Any]
Value = bool | int | list[str] | None
Row = dict[str, Value]
Cases = dict[str, Row]

# --- Temsilî olay yükleri (docs/DECISIONS.md "İş akışı olay sözleşmesi") -------------------------
# Kayıtlar veritabanında yoktur: kural yalnız `{"model", "id"}` ile kayda bağlanır.

MATERIAL = {"material_code": "HM-001", "material_name": "Sonda hammaddesi"}
CUSTOMER = {"customer_code": "M-001", "customer_name": "Sonda Müşterisi"}
SUPPLIER = {"supplier_name": "Sonda Tedarikçisi"}


def _lot(n: int, material_type: str, **extra: Any) -> Payload:
    return {
        "model": "inventory.lot",
        "id": n,
        "lot_no": f"L-{n}",
        "material_type": material_type,
        **MATERIAL,
        **extra,
    }


def _sample(n: int, stage: str, material_type: str, **extra: Any) -> Payload:
    """Numune olayı: numune alanları, aşama ve lot."""
    return {
        "model": "quality.sample",
        "id": n,
        "number": f"NM-{n}",
        "stage": stage,
        "material_type": material_type,
        "lot_no": f"L-{n}",
        **MATERIAL,
        "lot": _lot(n, material_type),
        **extra,
    }


def _doc(model: str, prefix: str, n: int, **extra: Any) -> Payload:
    """Belge olayı: `{"model", "id", "number"}` ve belgeye özgü alanlar."""
    return {"model": model, "id": n, "number": f"{prefix}-{n}", **extra}


def _batch(n: int, **extra: Any) -> Payload:
    return {
        "model": "production.productionbatch",
        "id": n,
        "batch_no": f"S-{n}",
        "order_number": f"UE-{n}",
        "order": _doc("production.productionorder", "UE", n),
        **extra,
    }


def _downtime(n: int, **extra: Any) -> Payload:
    return {
        "model": "maintenance.downtime",
        "id": n,
        "repr": "T-01 duruşu",
        "equipment_code": "T-01",
        "equipment_name": "Tank 1",
        "reason": "BREAKDOWN",
        "reason_display": "Arıza",
        "started_at": "11.11.2026 09:00",
        "note": "",
        **extra,
    }


def _report_job(n: int, **extra: Any) -> Payload:
    return {
        "model": "reporting.reportjob",
        "id": n,
        "repr": "Stok raporu",
        "report_code": "stock",
        "title": "Stok raporu",
        "file_format": "xlsx",
        **extra,
    }


def _work_order(role: str) -> Callable[[int], Payload]:
    """Bakım iş emri: görev yalnız sorumlu rolün kuralından açılır."""

    def build(n: int) -> Payload:
        return _doc(
            "maintenance.maintenanceworkorder",
            "BE",
            n,
            equipment_code="T-01",
            title="Pompa bakımı",
            kind_display="Arızalı bakım",
            due_date="20.11.2026",
            responsible_role=role,
            open_task=True,
        )

    return build


PAYLOADS: dict[str, Callable[[int], Payload]] = {
    # Görev kuralları
    "incoming_qc": lambda n: _sample(n, "INCOMING", "RAW"),
    "material_prep": lambda n: _doc("production.productionorder", "UE", n),
    "start_batch": lambda n: _doc("production.productionorder", "UE", n),
    "batch_sample_analysis": lambda n: _sample(n, "IN_PROCESS", "BULK"),
    "conditional_release_approval": lambda n: _sample(n, "INCOMING", "RAW", reason="Renk sınırda."),
    "rework_order": lambda n: _sample(n, "FINAL", "BULK", decision="REWORK", reason="pH düşük."),
    "packaging_prep": lambda n: _doc("filling.fillingorder", "DE", n, product_code="MM-001"),
    "start_filling": lambda n: _doc("filling.fillingorder", "DE", n, product_code="MM-001"),
    "finished_qc": lambda n: {
        "model": "filling.fillingrun",
        "id": n,
        "order_number": f"DE-{n}",
        "sample_number": f"NM-{n}",
        "output_lot": _lot(n, "FINISHED"),
    },
    "return_qc": lambda n: _sample(n, "RETURN", "FINISHED"),
    "return_rework": lambda n: _sample(
        n, "RETURN", "FINISHED", decision="REWORK", reason="Ambalaj hasarlı."
    ),
    "return_scrap": lambda n: _doc("returns.customerreturn", "IA", n, **CUSTOMER),
    "plan_shipment": lambda n: _doc("sales.salesorder", "SS", n, **CUSTOMER),
    "sales_shortage": lambda n: _doc(
        "sales.salesorder",
        "SS",
        n,
        **CUSTOMER,
        reason="",
        lines=[{"product_code": "MM-001", "product_name": "Mamul", "quantity": "10", "unit": "ad"}],
    ),
    "pick_shipment": lambda n: _doc(
        "sales.shipment",
        "SV",
        n,
        **CUSTOMER,
        order_number=f"SS-{n}",
        order=_doc("sales.salesorder", "SS", n),
        order_fully_planned=False,
    ),
    "dispatch_shipment": lambda n: _doc(
        "sales.shipment", "SV", n, **CUSTOMER, order_number=f"SS-{n}", vehicle_plate="34 ABC 123"
    ),
    "purchase_request": lambda n: _doc(
        "purchasing.purchaserequest",
        "ST",
        n,
        **MATERIAL,
        quantity="100",
        unit="kg",
        need_date="01.12.2026",
        reason="",
    ),
    "purchase_order_approval": lambda n: _doc(
        "purchasing.purchaseorder",
        "SA",
        n,
        **SUPPLIER,
        currency="TRY",
        total="125000.00",
        total_try="125000.00",
    ),
    **{
        f"maintenance_work_order_{role}": _work_order(role)
        for role in ("uretim", "dolum", "laboratuvar", "planlama", "yonetim")
    },
    "incident_review": lambda n: _doc(
        "hse.incident",
        "OL",
        n,
        incident_type_display="Ramak kala",
        place="Depo",
        occurred_at="11.11.2026 09:00",
        injury=False,
    ),
    "problem_reported": lambda n: _doc(
        "golive.problemreport",
        "SB",
        n,
        summary="Sonda",
        reporter="Sonda",
        page_url="/",
        page_title="Ana sayfa",
    ),
    # Bildirim kuralları
    "lot_rejected": lambda n: _lot(n, "RAW", note="Renk uygun değil.", **SUPPLIER),
    "production_deviation": lambda n: _batch(
        n,
        material_code="HM-001",
        lot_no=f"L-{n}",
        planned_quantity="100 kg",
        actual_quantity="103 kg",
        deviation_pct="3",
        note="",
    ),
    "in_process_out_of_spec": lambda n: _sample(
        n, "IN_PROCESS", "BULK", decision="REJECT", reason="pH yüksek."
    ),
    "bulk_lot_released": lambda n: _lot(n, "BULK"),
    "bulk_lot_rejected": lambda n: _lot(n, "BULK", note=""),
    "production_low_yield": lambda n: _batch(n, yield_pct="90", threshold_pct="95"),
    "filling_bulk_variance": lambda n: _doc(
        "filling.fillingorder",
        "DE",
        n,
        lot_no=f"L-{n}",
        product_code="MM-001",
        good_units=100,
        theoretical_quantity="100 kg",
        actual_quantity="104 kg",
        variance_pct="4",
        threshold_pct="2",
    ),
    "finished_lot_released": lambda n: _lot(n, "FINISHED"),
    "finished_lot_rejected": lambda n: _lot(n, "FINISHED", note=""),
    "return_closed": lambda n: _doc("returns.customerreturn", "IA", n, **CUSTOMER),
    "lots_expiring": lambda n: {
        "days": 30,
        "lots": [{"lot_no": f"L-{n}", **MATERIAL, "expiry_date": "01.12.2026"}],
    },
    "below_min_stock": lambda n: {
        "materials": [
            {"code": "HM-001", "name": "Hammadde", "quantity": "5", "min_stock": "10", "unit": "kg"}
        ]
    },
    "reserved_lots_expiring": lambda n: {
        "days": 14,
        "lots": [
            {
                "lot_no": f"L-{n}",
                "material_code": "MM-001",
                "expiry_date": "01.12.2026",
                "reserved_quantity": "10",
                "unit": "ad",
                "orders": [f"SS-{n}"],
            }
        ],
    },
    "shipment_dispatched": lambda n: _doc(
        "sales.shipment",
        "SV",
        n,
        **CUSTOMER,
        order_number=f"SS-{n}",
        vehicle_plate="34 ABC 123",
        lots=[{"lot_no": f"L-{n}", "quantity": "10"}],
    ),
    "purchase_order_returned": lambda n: _doc(
        "purchasing.purchaseorder", "SA", n, note="Fiyatı gözden geçirin."
    ),
    "expected_delivery": lambda n: _doc(
        "purchasing.purchaseorder",
        "SA",
        n,
        **SUPPLIER,
        expected_date="01.12.2026",
        lines=[{**MATERIAL, "quantity": "100", "line_unit": "kg", "expected_date": "01.12.2026"}],
    ),
    "purchase_order_received": lambda n: _doc(
        "purchasing.purchaseorder", "SA", n, **SUPPLIER, receipt_number=f"MK-{n}"
    ),
    "equipment_down": lambda n: _downtime(n, ended_at="", minutes=None),
    "equipment_up": lambda n: _downtime(n, ended_at="11.11.2026 10:00", minutes=60),
    "maintenance_overdue": lambda n: {
        "model": "maintenance.maintenanceplan",
        "id": 0,
        "repr": "Bakım planları",
        "count": 1,
        "plans": [{"equipment_code": "T-01", "title": "Yağlama", "next_due_date": "01.11.2026"}],
    },
    "incident_injury": lambda n: _doc(
        "hse.incident",
        "OL",
        n,
        incident_type_display="İş kazası",
        place="Dolum hattı",
        occurred_at="11.11.2026 09:00",
        injury=True,
    ),
    "storage_limit_exceeded": lambda n: {
        "model": "masterdata.location",
        "id": n,
        "repr": "D-01",
        "location_code": "D-01",
        "hazard_class": "FLAMMABLE",
        "hazard_class_display": "Yanıcı",
        "quantity_kg": "1200",
        "limit_kg": "1000",
    },
    "report_ready": lambda n: _report_job(n, row_count=3, error=""),
    "report_failed": lambda n: _report_job(n, row_count=0, error="Zaman aşımı."),
    "user_locked": lambda n: {
        "model": "core.user",
        "id": n,
        "repr": "kilitli",
        "user_id": n,
        "username": "kilitli",
        "minutes": 15,
        "locked_until": "11.11.2026 09:15",
    },
    "ops_alert": lambda n: {"check": "disk", "title": "Disk", "detail": "Disk %95 dolu."},
    "ops_recovered": lambda n: {"check": "disk", "title": "Disk", "detail": "Disk %60 dolu."},
    # İptal kuralları
    "production_order_cancelled": lambda n: _doc("production.productionorder", "UE", n),
    "filling_order_cancelled": lambda n: _doc("filling.fillingorder", "DE", n),
    "sales_order_cancelled": lambda n: _doc("sales.salesorder", "SS", n, **CUSTOMER),
    "shipment_cancelled": lambda n: _doc("sales.shipment", "SV", n, **CUSTOMER),
    "purchase_order_cancelled": lambda n: _doc("purchasing.purchaseorder", "SA", n),
}

# Yükten gelen alıcılar: kural → yükteki kullanıcı kimliği alanı.
PAYLOAD_USERS = {
    "shipment_dispatched": "order_created_by_id",
    "report_ready": "requested_by_id",
    "report_failed": "requested_by_id",
}

# --- Anlık görüntü dosyası: her durum tek satır --------------------------------------------------

CODES = {
    "y": "evet",
    "n": "hayır",
    "-": "yok: anonim, görmüyor ya da alıcı değil",
    "sayı": "HTTP durum kodu ya da adet",
    "[..]": "personalar (PERSONAS sırasıyla)",
}


def _token(value: Value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "y" if value else "n"
    if isinstance(value, int):
        return str(value)
    return "[" + ",".join(value) + "]"


def _value(token: str) -> Value:
    if token == "-":
        return None
    if token in ("y", "n"):
        return token == "y"
    if token.startswith("["):
        inner = token[1:-1]
        return inner.split(",") if inner else []
    return int(token)


def encode(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {"_personas": list(PERSONAS), "_codes": CODES}
    for case, values in cases.items():
        data[case] = " ".join(_token(values[persona]) for persona in PERSONAS)
    return data


def decode(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    personas = data["_personas"]
    return {
        case: dict(zip(personas, map(_value, value.split(" ")), strict=True))
        for case, value in data.items()
        if not case.startswith("_")
    }


# --- Sonda ---------------------------------------------------------------------------------------


@contextmanager
def rolled_back() -> Iterator[None]:
    """İçindeki yazmalar geri alınır: her deneme aynı başlangıç durumunu görür."""
    with transaction.atomic():
        yield
        transaction.set_rollback(True)


class Pushes:
    """Kanal katmanına giden anlık mesajlar: (kullanıcı grubu, mesaj)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def group_send(self, group: str, message: dict[str, Any]) -> None:
        self.sent.append((group, message["data"]))


def _client(user: User | None) -> APIClient:
    return persona_client(user)


def _status_or(response: Any, value: Callable[[Any], Value]) -> Value:
    """Başarılı yanıtta `value(json)`, değilse HTTP durum kodu."""
    return value(response.json()) if response.status_code == 200 else response.status_code


def _label(task: Task) -> str:
    content_type = task.related_content_type
    assert content_type is not None, task.rule_code
    return f"{content_type.app_label}.{content_type.model}"


class Probe:
    def __init__(self, capture: DjangoCaptureOnCommitCallbacks, pushes: Pushes) -> None:
        self.users = make_personas()
        self.clients = {name: _client(user) for name, user in self.users.items()}
        self.groups = {
            realtime.user_group(user.pk): name
            for name, user in self.users.items()
            if user is not None
        }
        self.capture = capture
        self.pushes = pushes
        self.ids = count(900_001)
        self.task_rules = [rule for rule in rules.RULES if isinstance(rule, rules.TaskRule)]
        self.tasks: dict[str, Task] = {}  # kural → 1. aşamada açılan açık görev

    # --- yardımcılar

    def payload(self, rule: rules.Rule, n: int | None = None) -> Payload:
        """Kuralın temsilî yükü; verilmezse yeni bir kayıt kimliğiyle."""
        return PAYLOADS[rule.code](next(self.ids) if n is None else n)

    def run(self, rule: rules.Rule, payload: Payload, actor: User | None = None) -> None:
        """Olayı iş akışına verir: olay dinleyicisinin çağırdığı `services.process_event`."""
        actor_id = actor.pk if actor is not None else None
        services.process_event(events.Event(name=rule.event, payload=payload, actor_id=actor_id))

    def received(self, notifications: QuerySet[Notification]) -> Row:
        """Bildirimi alan personalar (anonim `-`).

        Her bildirim anlık mesajla yalnız kendi alıcısına gider: anlık kitle alıcılarla aynıdır.
        """
        rows = set(notifications.values_list("pk", "recipient_id"))
        pks = {pk for pk, _ in rows}
        sent = {
            (data["id"], group)
            for group, data in self.pushes.sent
            if data.get("type") == "notification.created" and data.get("id") in pks
        }
        expected = {(pk, realtime.user_group(user_id)) for pk, user_id in rows}
        assert sent == expected, f"Anlık mesaj alıcılardan farklı: {sorted(sent ^ expected)}"
        ids = {user_id for _, user_id in rows}
        return {name: None if user is None else user.pk in ids for name, user in self.users.items()}

    def pushed(self, task: Task, status: str) -> list[str]:
        """Görevin bu durumuyla `task.changed` mesajı giden personalar (PERSONAS sırasıyla)."""
        names = {
            self.groups[group]
            for group, data in self.pushes.sent
            if data.get("type") == "task.changed"
            and data.get("id") == task.pk
            and data.get("status") == status
        }
        return [name for name in PERSONAS if name in names]

    @contextmanager
    def observed(self) -> Iterator[None]:
        """Commit sonrası işler (anlık mesajlar) blok sonunda çalışır ve kaydedilir."""
        self.pushes.sent.clear()
        with self.capture(execute=True):
            yield

    def as_actor(self, recipients: Row, notified: Callable[[User], bool]) -> Row:
        """Alıcı personalardan her biri olayı kendisi yapsa bildirimi alır mı (diğerleri `-`)."""
        row: Row = {}
        for name, user in self.users.items():
            row[name] = None
            if user is not None and recipients[name]:
                with rolled_back():
                    row[name] = notified(user)
        return row

    def new_task(self, rule: rules.TaskRule) -> Task:
        """Kuralın bu denemede açtığı görev (1. aşamadaki görev dışında)."""
        return Task.objects.filter(rule_code=rule.code).exclude(pk=self.tasks[rule.code].pk).get()

    # --- bildirimler (satır kuralı)

    def notifications(self) -> Cases:
        """Her personaya bir bildirim: kim hangisini listeler, sayar ve okundu işaretler."""
        listed: Row = {}
        unread: Row = {}
        marked: Row = {}
        with rolled_back():
            owner = {
                Notification.objects.create(recipient=user, title=f"Sonda: {name}").pk: name
                for name, user in self.users.items()
                if user is not None
            }
            for name, client in self.clients.items():
                listed[name] = _status_or(
                    client.get(NOTIFICATIONS, ALL_ROWS),
                    lambda data: [
                        p
                        for p in PERSONAS
                        if p in {owner.get(item["id"]) for item in data["results"]}
                    ],
                )
                unread[name] = _status_or(
                    client.get(f"{NOTIFICATIONS}unread-count/"), lambda data: data["count"]
                )
                with rolled_back():
                    marked[name] = _status_or(
                        client.post(
                            f"{NOTIFICATIONS}mark-read/", {"ids": sorted(owner)}, format="json"
                        ),
                        lambda data: data["updated"],
                    )
        return {
            "notifications: listed": listed,
            "notifications: unread count": unread,
            "notifications: mark read": marked,
        }

    # --- görev kuralları

    def task_rules_cases(self) -> Cases:
        cases: Cases = {}
        for rule in self.task_rules:
            with self.observed():
                self.run(rule, self.payload(rule))
            task = Task.objects.get(rule_code=rule.code)
            self.tasks[rule.code] = task
            cases[f"task {rule.code}: notified"] = self.received(
                Notification.objects.filter(task=task)
            )
            opened = self.pushed(task, Task.Status.OPEN)
            cases[f"task {rule.code}: pushed"] = {
                name: None if user is None else name in opened for name, user in self.users.items()
            }
        cases.update(self.task_lists())
        cases.update(self.task_notification_bodies())
        cases.update(self.claim_and_complete())
        cases.update(self.claimer())
        for rule in self.task_rules:
            cases[f"task {rule.code}: notified as actor"] = self.as_actor(
                cases[f"task {rule.code}: notified"], self._task_actor_notified(rule)
            )
        return cases

    def _task_actor_notified(self, rule: rules.TaskRule) -> Callable[[User], bool]:
        def notified(user: User) -> bool:
            self.run(rule, self.payload(rule), actor=user)
            return Notification.objects.filter(task=self.new_task(rule), recipient=user).exists()

        return notified

    def task_lists(self) -> Cases:
        """Görev listesi ve Görevlerim (`?mine=true`): görünürlük, `can_act`, açıklama."""
        cases: Cases = {}
        for name, client in self.clients.items():
            for listed, params in (
                ("listed", ALL_ROWS),
                ("listed mine", {**ALL_ROWS, "mine": "true"}),
            ):
                response = client.get(TASKS, params)
                items: dict[int, Any] = {}
                if response.status_code == 200:
                    assert response.json()["next"] is None
                    items = {item["id"]: item for item in response.json()["results"]}
                for rule in self.task_rules:
                    task = self.tasks[rule.code]
                    item = items.get(task.pk)
                    values: dict[str, Value] = {listed: item is not None}
                    if listed == "listed":
                        values["can_act"] = None if item is None else item["can_act"]
                        values["description shown"] = (
                            None if item is None else item["description"] == task.description
                        )
                    for key, value in values.items():
                        cases.setdefault(f"task {rule.code}: {key}", {})[name] = (
                            value if response.status_code == 200 else response.status_code
                        )
        return cases

    def task_notification_bodies(self) -> Cases:
        """Alıcının bildirim listesinde "Yeni görev" metni (görev açıklaması) tam mı."""
        cases: Cases = {}
        for name, client in self.clients.items():
            response = client.get(NOTIFICATIONS, ALL_ROWS)
            by_task: dict[int, Any] = {}
            if response.status_code == 200:
                assert response.json()["next"] is None
                by_task = {item["task"]: item for item in response.json()["results"]}
            for rule in self.task_rules:
                task = self.tasks[rule.code]
                item = by_task.get(task.pk)
                value: Value = None if item is None else item["body"] == task.description
                cases.setdefault(f"task {rule.code}: notification body shown", {})[name] = (
                    value if response.status_code == 200 else response.status_code
                )
        return cases

    def claim_and_complete(self) -> Cases:
        """Açık görevi üstlenme ve tamamlama yanıtı; üstlenince anlık mesajın kitlesi."""
        cases: Cases = {}
        for rule in self.task_rules:
            task = self.tasks[rule.code]
            claim: Row = {}
            claim_pushed: Row = {}
            complete: Row = {}
            for name, client in self.clients.items():
                with rolled_back():
                    with self.observed():
                        response = client.post(f"{TASKS}{task.pk}/claim/")
                    claim[name] = response.status_code
                    claim_pushed[name] = (
                        self.pushed(task, Task.Status.IN_PROGRESS)
                        if response.status_code == 200
                        else None
                    )
                with rolled_back():
                    complete[name] = client.post(
                        f"{TASKS}{task.pk}/complete/", {}, format="json"
                    ).status_code
            cases[f"task {rule.code}: claim"] = claim
            cases[f"task {rule.code}: claim pushed"] = claim_pushed
            cases[f"task {rule.code}: complete"] = complete
        return cases

    def claimer(self) -> Cases:
        """Görevi persona üstlenmiş, sonra rolünü kaybetmiş gibi: listede görür, tamamlar mı.

        Servisler bu durumu üretmez (üstlenmek rol ister); görev doğrudan bu duruma getirilir.
        """
        cases: Cases = {}
        for name, user in self.users.items():
            client = self.clients[name]
            with rolled_back():
                listed: dict[int, Value] = {}
                if user is not None:
                    Task.objects.filter(pk__in=[t.pk for t in self.tasks.values()]).update(
                        status=Task.Status.IN_PROGRESS, claimed_by=user, claimed_at=timezone.now()
                    )
                    response = client.get(TASKS, ALL_ROWS)
                    ok = response.status_code == 200
                    visible = {item["id"] for item in response.json()["results"]} if ok else set()
                    listed = {
                        t.pk: t.pk in visible if ok else response.status_code
                        for t in self.tasks.values()
                    }
                for rule in self.task_rules:
                    task = self.tasks[rule.code]
                    complete: Value = None
                    if user is not None:
                        with rolled_back():
                            complete = client.post(
                                f"{TASKS}{task.pk}/complete/", {}, format="json"
                            ).status_code
                    cases.setdefault(f"task {rule.code}: claimer listed", {})[name] = listed.get(
                        task.pk
                    )
                    cases.setdefault(f"task {rule.code}: claimer complete", {})[name] = complete
        return cases

    # --- bildirim kuralları

    def notify_rules_cases(self) -> Cases:
        cases: Cases = {}
        for rule in rules.RULES:
            if not isinstance(rule, rules.NotifyRule):
                continue
            payload = self.payload(rule)
            assert rule.when(payload), f"{rule.code}: yük kuralı tetiklemiyor"
            with rolled_back():
                with self.observed():
                    self.run(rule, payload)
                notified = self.received(Notification.objects.filter(rule_code=rule.code))
            cases[f"notify {rule.code}: notified"] = notified
            cases[f"notify {rule.code}: notified as actor"] = self.as_actor(
                notified, self._notify_actor_notified(rule)
            )
            key = PAYLOAD_USERS.get(rule.code)
            if key is None:
                continue
            row: Row = {}
            for name, user in self.users.items():
                row[name] = None
                if user is not None:
                    with rolled_back():
                        self.run(rule, {**self.payload(rule), key: user.pk})
                        row[name] = Notification.objects.filter(
                            rule_code=rule.code, recipient=user
                        ).exists()
            cases[f"notify {rule.code}: payload user notified"] = row
        return cases

    def _notify_actor_notified(self, rule: rules.NotifyRule) -> Callable[[User], bool]:
        def notified(user: User) -> bool:
            self.run(rule, self.payload(rule), actor=user)
            return Notification.objects.filter(rule_code=rule.code, recipient=user).exists()

        return notified

    # --- iptal kuralları

    def cancel_rules_cases(self) -> Cases:
        cases: Cases = {}
        for rule in rules.RULES:
            if not isinstance(rule, rules.CancelTasksRule):
                continue
            with rolled_back():
                with self.observed():
                    self.run(rule, self.payload(rule))
                cases[f"cancel {rule.code}: notified"] = self.received(
                    Notification.objects.filter(rule_code=rule.code)
                )
            # Kayda bağlı görev açan kurallar: 1. aşamadaki görevi aynı türde kayda bağlı olanlar.
            model = self.payload(rule)["model"]
            paired = [t for t in self.task_rules if _label(self.tasks[t.code]) == model]
            assert paired, f"{rule.code}: aynı kayda görev açan kural yok"
            for task_rule in paired:
                prefix = f"cancel {rule.code} after {task_rule.code}"
                with rolled_back():
                    with self.observed():
                        self.open_and_cancel(rule, task_rule)
                    notified = self.received(Notification.objects.filter(rule_code=rule.code))
                cases[f"{prefix}: notified"] = notified
                cases[f"{prefix}: notified as actor"] = self.as_actor(
                    notified, self._cancel_actor_notified(rule, task_rule)
                )
                claimer: Row = {}
                for name, user in self.users.items():
                    claimer[name] = None
                    if user is not None:
                        with rolled_back():
                            self.open_and_cancel(rule, task_rule, claimer=user)
                            claimer[name] = Notification.objects.filter(
                                rule_code=rule.code, recipient=user
                            ).exists()
                cases[f"{prefix}: claimer notified"] = claimer
        return cases

    def open_and_cancel(
        self,
        rule: rules.CancelTasksRule,
        task_rule: rules.TaskRule,
        *,
        claimer: User | None = None,
        actor: User | None = None,
    ) -> None:
        """Kayda bağlı görevi açar (istenirse persona üstlenmiş olur) ve kaydı iptal eder."""
        n = next(self.ids)
        self.run(task_rule, self.payload(task_rule, n))
        task = self.new_task(task_rule)
        if claimer is not None:
            Task.objects.filter(pk=task.pk).update(
                status=Task.Status.IN_PROGRESS, claimed_by=claimer, claimed_at=timezone.now()
            )
        self.run(rule, self.payload(rule, n), actor=actor)
        task.refresh_from_db()
        assert task.status == Task.Status.CANCELLED, (rule.code, task_rule.code)

    def _cancel_actor_notified(
        self, rule: rules.CancelTasksRule, task_rule: rules.TaskRule
    ) -> Callable[[User], bool]:
        def notified(user: User) -> bool:
            self.open_and_cancel(rule, task_rule, actor=user)
            return Notification.objects.filter(rule_code=rule.code, recipient=user).exists()

        return notified


def test_every_rule_has_a_probe_payload() -> None:
    """Her kuralın temsilî yükü var, kural sayısı bugünkü: yeni kural sondadan kaçamaz.

    Sonda, olay dinleyicisinin her kural olayında çağırdığı işlevi çağırır.
    """
    assert dict(Counter(type(rule).__name__ for rule in rules.RULES)) == RULE_COUNTS
    codes = [rule.code for rule in rules.RULES]
    assert len(codes) == len(set(codes))
    assert set(PAYLOADS) == set(codes)
    for rule in rules.RULES:
        assert services.process_event in events.handlers_for(rule.event), rule.code
    default_users = next(f.default for f in fields(rules.NotifyRule) if f.name == "users")
    with_users = {
        rule.code
        for rule in rules.RULES
        if isinstance(rule, rules.NotifyRule) and rule.users is not default_users
    }
    assert with_users == set(PAYLOAD_USERS)
    for rule in rules.RULES:
        if rule.code in PAYLOAD_USERS:
            assert isinstance(rule, rules.NotifyRule)
            assert rule.users({PAYLOAD_USERS[rule.code]: 7}) == [7]


@pytest.mark.django_db
def test_workflow_rules_match_snapshot(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    pushes = Pushes()
    monkeypatch.setattr(get_channel_layer(), "group_send", pushes.group_send)
    probe = Probe(django_capture_on_commit_callbacks, pushes)
    cases: Cases = {
        **probe.notifications(),
        **probe.task_rules_cases(),
        **probe.notify_rules_cases(),
        **probe.cancel_rules_cases(),
    }
    # Hata veren kural (process_event loglayıp geçer) kimseye gitmemiş gibi görünmesin.
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert not errors, "Kural hata verdi:\n" + "\n".join(errors)
    snapshot.check(NAME, cases, encode=encode, decode=decode)
