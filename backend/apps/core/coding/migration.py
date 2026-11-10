"""Kod göçü: mevcut ana veri kodlarını yeni biçime taşır (docs/plan/kodlama-sistematigi.md §3.5).

- `preview_recode`: salt okunur. Biçime uyan kod korunur; uymayan kayıtlar oluşturulma sırasıyla
  sıradaki boş numarayı alır (dolu ya da başka kaydın eski kodu olan numara atlanır).
- `apply_recode`: önizlemenin özeti (`checksum`) tutmazsa reddedilir (`recode_stale`). Kodu
  türün modülü kendi servisiyle değiştirir (`CodeType.recode`); kaydın öteki alanları yeniden
  doğrulanmaz. Her değişiklik denetim günlüğüne ve eski kod geçmişine yazılır.
- `revert_recode`: kodu hâlâ göçteki yeni kod olan kayıtlar eski koduna döner.
- Kayıtlar başka bir işlemde kilitliyse (`LOCK_TIMEOUT_MS` dolarsa ya da kilitlenme olursa) göç
  ve geri alma `recode_busy` ile reddedilir.

Stok defterine, lotlara ve belge numaralarına dokunulmaz; ilişkiler kimlik üzerinden kurulduğu için
bozulmaz.
"""

import functools
import hashlib
import json
from collections.abc import Callable
from typing import Any

from django.db import OperationalError, connection, models, transaction

from apps.core.coding import formats, selectors
from apps.core.coding.registry import MASTER, CodeType
from apps.core.coding.services import get_type, lock_sequence, require_admin
from apps.core.exceptions import BusinessRuleError, is_busy_error
from apps.core.models import CodeMigrationRun, CodeSequence, User

# Göç kilit beklerken en çok bu kadar bekler (milisaniye); süre dolarsa reddedilir.
LOCK_TIMEOUT_MS = 5000
# PostgreSQL: kilit beklerken süre doldu (lock_not_available), kilitlenme (deadlock_detected).


def _migratable(key: str) -> CodeType:
    item = get_type(key)
    if item.kind != MASTER or item.free or item.recode is None:
        raise BusinessRuleError(
            "recode_not_allowed", "Bu kod türünde kod göçü yapılmaz (standart ya da serbest kod)."
        )
    return item


def _checksum(changes: list[dict[str, Any]]) -> str:
    body = json.dumps(
        [(row["id"], row["old"], row["new"]) for row in changes], ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:16]


def _records(item: CodeType, *, lock: bool = False) -> list[models.Model]:
    queryset = selectors.model_class(item)._base_manager.order_by("created_at", "pk")
    if lock:
        queryset = queryset.select_for_update()
    return list(queryset)


def _plan(item: CodeType, records: list[models.Model]) -> dict[str, Any]:
    fmt = selectors.effective_format(item)
    rows: list[dict[str, Any]] = []
    used: dict[str, set[str]] = {}
    next_after: dict[str, int] = {}
    for record in records:
        code = str(getattr(record, item.field) or "")
        prefix = selectors.instance_prefix(item, fmt, record)
        row: dict[str, Any] = {
            "id": record.pk,
            "label": str(record)[:200],
            "old": code,
            "new": code,
            "action": "keep",
            "is_active": bool(getattr(record, "is_active", True)),
            "problem": "",
        }
        if prefix is None:
            row["action"] = "problem"
            row["problem"] = "Bu kaydın türü için önek tanımlı değil."
        elif formats.master_number(code, prefix, fmt.width) is None:
            if prefix not in used:
                used[prefix] = selectors.used_codes(item, prefix)
                next_after[prefix] = selectors.counter_value(item, prefix)
            new_code, number = selectors.next_free(item, prefix, fmt.width, next_after[prefix])
            while new_code in used[prefix]:  # aynı göçte verilen kod
                new_code, number = selectors.next_free(item, prefix, fmt.width, number)
            used[prefix].add(new_code)
            next_after[prefix] = number
            row["new"] = new_code
            row["action"] = "change"
        rows.append(row)
    changes = [row for row in rows if row["action"] == "change"]
    return {
        "key": item.key,
        "label": item.label,
        "active": selectors.is_active(item),
        "rows": rows,
        "change_count": len(changes),
        "keep_count": sum(1 for row in rows if row["action"] == "keep"),
        "problem_count": sum(1 for row in rows if row["action"] == "problem"),
        "checksum": _checksum(changes),
    }


def preview_recode(key: str) -> dict[str, Any]:
    """Göç önizlemesi (hiçbir şey yazılmaz): her kaydın eski ve yeni kodu, özet ve `checksum`."""
    item = _migratable(key)
    return _plan(item, _records(item))


def _lock_timeout() -> None:
    # Göç sırasında kayıtlar kilitlenir; açık bir işlem uzun beklerse göç bekletilmez, reddedilir.
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, true)", [f"{LOCK_TIMEOUT_MS}ms"])


def _reject_when_busy[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Kayıtlar başka bir işlemde kilitliyse (bekleme süresi doldu ya da kilitlenme) göç geri
    alınır ve `recode_busy` ile reddedilir (sunucu hatası değil)."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except OperationalError as exc:
            if not is_busy_error(exc):
                raise
            raise BusinessRuleError(
                "recode_busy",
                "Kayıtlar şu an başka bir işlemde kullanılıyor; birkaç saniye sonra yeniden "
                "deneyin.",
            ) from exc

    return wrapper


@_reject_when_busy
@transaction.atomic
def apply_recode(actor: User, key: str, *, checksum: str, note: str) -> CodeMigrationRun:
    """Önizlemedeki göçü uygular (yalnız admin; not zorunlu).

    Kayıtlar kilitlenip eşleme yeniden hesaplanır; önizlemeden sonra kayıtlar değiştiyse
    `recode_stale`. Değişecek kod yoksa `recode_nothing`, öneki tanımsız kayıt varsa
    `recode_problem`, kayıtlar başka bir işlemde kilitliyse `recode_busy`. Önek sayaçları
    verilen en büyük numaraya ilerletilir.
    """
    require_admin(actor)
    item = _migratable(key)
    note = (note or "").strip()
    if not note:
        raise BusinessRuleError("note_required", "Göç notu yazın (geçmişte görünür).")
    _lock_timeout()
    # Önek sayaçları da kilitlenir: göç sürerken yeni kayıt sıradaki kodu alamaz (kod alan kayıt
    # aynı kilidi bekler, `claim_master_code`).
    for prefix in selectors.effective_format(item).prefixes():
        lock_sequence(item, prefix)
    plan = _plan(item, _records(item, lock=True))
    if plan["checksum"] != checksum:
        raise BusinessRuleError(
            "recode_stale", "Önizlemeden sonra kayıtlar değişti; önizlemeyi yenileyin."
        )
    if plan["problem_count"]:
        raise BusinessRuleError(
            "recode_problem", "Öneki tanımsız kayıtlar var; önce biçimi düzeltin."
        )
    changes = [row for row in plan["rows"] if row["action"] == "change"]
    if not changes:
        raise BusinessRuleError("recode_nothing", "Değişecek kod yok.")
    run = CodeMigrationRun.objects.create(
        key=item.key,
        kind=CodeMigrationRun.Kind.APPLY,
        mapping=[{k: row[k] for k in ("id", "label", "old", "new")} for row in changes],
        note=note,
        created_by=actor,
    )
    model = selectors.model_class(item)
    fmt = selectors.effective_format(item)
    highest: dict[str, int] = {}
    assert item.recode is not None
    for row in changes:
        record = model._base_manager.get(pk=row["id"])
        item.recode(actor, record, row["new"], f"Kod göçü #{run.pk}: {note}", run.pk, "migration")
        head = selectors.instance_prefix(item, fmt, record)
        number = formats.master_number(row["new"], head, fmt.width) if head else None
        if head and number is not None:
            highest[head] = max(highest.get(head, 0), number)
    for prefix, number in highest.items():
        sequence = lock_sequence(item, prefix)
        if sequence.last_number < number:
            CodeSequence.objects.filter(pk=sequence.pk).update(last_number=number)
    return run


def _run(run_id: int, *, lock: bool = False) -> CodeMigrationRun:
    queryset = CodeMigrationRun.objects.all()
    if lock:
        queryset = queryset.select_for_update()
    run = queryset.filter(pk=run_id).first()
    if run is None:
        raise BusinessRuleError("run_not_found", "Kod göçü bulunamadı.")
    return run


def preview_revert(run_id: int) -> dict[str, Any]:
    """Geri alma önizlemesi: göçteki her kaydın şimdiki kodu ve geri dönüp dönmeyeceği."""
    run = _run(run_id)
    item = _migratable(run.key)
    if run.kind != CodeMigrationRun.Kind.APPLY:
        raise BusinessRuleError("revert_not_allowed", "Geri alma kaydı geri alınamaz.")
    model = selectors.model_class(item)
    current = dict(
        model._base_manager.filter(pk__in=[row["id"] for row in run.mapping]).values_list(
            "pk", item.field
        )
    )
    rows = []
    for row in run.mapping:
        now = current.get(row["id"])
        rows.append(
            {
                **row,
                "current": now or "",
                "action": "revert" if now == row["new"] else "skip",
            }
        )
    return {
        "run": run.pk,
        "key": run.key,
        "label": item.label,
        "rows": rows,
        "revert_count": sum(1 for row in rows if row["action"] == "revert"),
        "already_reverted": run.reverted_by.exists(),
    }


@_reject_when_busy
@transaction.atomic
def revert_recode(actor: User, run_id: int, *, note: str) -> CodeMigrationRun:
    """Göçü geri alır (yalnız admin; not zorunlu): kodu hâlâ göçteki yeni kod olan kayıtlar eski
    koduna döner, kodu sonradan değişmiş kayıtlar olduğu gibi kalır. Göç bir kez geri alınır;
    kayıtlar başka bir işlemde kilitliyse `recode_busy`."""
    require_admin(actor)
    note = (note or "").strip()
    if not note:
        raise BusinessRuleError("note_required", "Geri alma notu yazın (geçmişte görünür).")
    _lock_timeout()
    run = _run(run_id, lock=True)
    item = _migratable(run.key)
    if run.kind != CodeMigrationRun.Kind.APPLY:
        raise BusinessRuleError("revert_not_allowed", "Geri alma kaydı geri alınamaz.")
    if run.reverted_by.exists():
        raise BusinessRuleError("already_reverted", "Bu göç zaten geri alındı.")
    model = selectors.model_class(item)
    records = {
        record.pk: record
        for record in model._base_manager.select_for_update().filter(
            pk__in=[row["id"] for row in run.mapping]
        )
    }
    back = [
        row
        for row in run.mapping
        if row["id"] in records and getattr(records[row["id"]], item.field) == row["new"]
    ]
    if not back:
        raise BusinessRuleError(
            "revert_nothing", "Geri alınacak kayıt yok; kodların hepsi sonradan değişmiş."
        )
    revert = CodeMigrationRun.objects.create(
        key=run.key,
        kind=CodeMigrationRun.Kind.REVERT,
        mapping=[{**row, "old": row["new"], "new": row["old"]} for row in back],
        note=note,
        reverts=run,
        created_by=actor,
    )
    assert item.recode is not None
    for row in back:
        item.recode(
            actor,
            records[row["id"]],
            row["old"],
            f"Kod göçü #{run.pk} geri alındı (#{revert.pk}): {note}",
            revert.pk,
            "revert",
        )
    return revert
