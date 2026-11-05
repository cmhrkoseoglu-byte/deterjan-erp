"""Kodlama sistematiğinden önce değişmiş ana veri kodlarını eski kod geçmişine yükler.

Paket 1'den önce kodu değişen kaydın önceki kodu yalnızca denetim günlüğündedir (`changes =
{"code": [eski, yeni]}`); `core.CodeHistory` boş başlar. Komut, kayıtlı her ana veri kod türü için
günlükteki kod değişikliklerinden eski kod satırları yazar. Böylece o kodlar başka kayda verilmez;
aramada, okutmada ve içe aktarmada tanınır (docs/plan/kodlama-sistematigi.md §3.4).

- Satırın geçerliliği önceki değişiklikten (ilk değişiklikte kaydın oluşturulmasından) bu
  değişikliğe kadardır; neden "Kod değişikliği", not "Önceki kayıtlardan (denetim günlüğü)".
- Sistematikten sonraki her kod değişikliği hem günlüğe hem eski kod geçmişine yazılır; bu yüzden
  kaydın günlükteki değişikliklerinden geçmişte satırı olanlar (en yeniler) atlanır. Geçmişi
  olmayan kayıtta hepsi yazılır. Komutun daha önce satır yazdığı kayıt atlanır: tekrar
  çalıştırmak bir şey yazmaz.
- Eski kod şu an aynı türde başka bir kaydın koduysa (kod sistematikten önce o kayda verilmişti)
  yazılmaz, özette listelenir: o kayıt kendi koduna dönebilsin, göçü geri alınabilsin. Birden çok
  kaydın eski kodu olan kodlar da özette bilgi olarak listelenir.
- Kayıtlar okunurken kilitlenir; çalışırken kodu değişen kayıt komutun bitmesini bekler.
- `--dry-run`: yazılacakları sayar, hiçbir şey yazmaz.
"""

from dataclasses import dataclass, field
from itertools import groupby
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Count

from apps.core.audit import log_change
from apps.core.coding import selectors
from apps.core.coding.registry import MASTER, CodeType, code_types
from apps.core.models import AuditLog, CodeHistory

NOTE = "Önceki kayıtlardan (denetim günlüğü)"


def _old_code(changes: Any, field: str) -> str | None:
    """Günlük satırındaki eski kod (`{"code": [eski, yeni]}`); okunamıyorsa ya da boşsa None."""
    pair = changes.get(field) if isinstance(changes, dict) else None
    if not isinstance(pair, list) or len(pair) != 2:
        return None
    old, new = pair
    if not isinstance(old, str) or not old.strip() or old == new:
        return None
    return old


@dataclass
class Pending:
    """Bir türün yazılacak eski kod satırları ve özet bilgileri."""

    rows: list[CodeHistory] = field(default_factory=list)
    missing: int = 0  # günlükte olup artık bulunmayan kayıt
    in_use: list[tuple[str, Any, Any]] = field(default_factory=list)  # (kod, kayıt, şimdiki sahibi)

    def shared(self) -> dict[str, list[Any]]:
        """Birden çok kaydın eski kodu olacak kodlar → kayıtlar."""
        owners: dict[str, set[Any]] = {}
        for row in self.rows:
            owners.setdefault(row.code, set()).add(row.object_id)
        return {code: sorted(ids) for code, ids in sorted(owners.items()) if len(ids) > 1}


def pending_rows(item: CodeType) -> Pending:
    """Türün yazılacak eski kod satırları, günlükte olup artık bulunmayan kayıtlar ve şu an başka
    kaydın kodu olduğu için yazılmayan eski kodlar.

    Transaction içinde çağrılır: günlükte kodu değişmiş kayıtlar önce kilitlenir, sonra günlük ve
    geçmiş okunur (bu arada kodu değişen kayıt olmaz, sayılar tutarlı kalır)."""
    model = selectors.model_class(item)
    content_type = ContentType.objects.get_for_model(model)
    changed = AuditLog.objects.filter(
        content_type=content_type,
        action=AuditLog.Action.UPDATE,
        object_id__isnull=False,
        changes__has_key=item.field,
    )
    ids = list(changed.order_by().values_list("object_id", flat=True).distinct())
    result = Pending()
    if not ids:
        return result
    records = model._base_manager.select_for_update().filter(pk__in=ids).order_by("pk")
    if any(field.name == "created_at" for field in model._meta.concrete_fields):
        created: dict[Any, Any] = dict(records.values_list("pk", "created_at"))
    else:
        created = dict.fromkeys(records.values_list("pk", flat=True))
    history = CodeHistory.objects.filter(
        content_type=content_type, field=item.field, object_id__in=list(created)
    )
    # Komutun daha önce satır yazdığı kayıtlar atlanır (tekrar çalıştırma bir şey yazmaz).
    done = set(history.filter(note=NOTE).values_list("object_id", flat=True))
    # Sistematikten sonraki değişikliklerin satırları (komutun yazdıkları sayılmaz).
    known = dict(
        history.exclude(note=NOTE)
        .values("object_id")
        .annotate(count=Count("id"))
        .values_list("object_id", "count")
    )
    logs = (
        changed.filter(object_id__in=list(created))
        .order_by("object_id", "timestamp", "id")
        .values_list("object_id", "timestamp", "actor_id", "changes")
    )
    for object_id, group in groupby(logs, key=lambda log: log[0]):
        changes = list(group)
        if object_id in done:
            continue
        # Geçmişte satırı olan değişiklikler en yenilerdir (sistematikten sonra yazıldılar).
        todo = max(len(changes) - known.get(object_id, 0), 0)
        for index, (_, timestamp, actor_id, values) in enumerate(changes[:todo]):
            old = _old_code(values, item.field)
            if old is None:
                continue
            holder = _current_holder(model, item, old, object_id)
            if holder is not None:
                result.in_use.append((old, object_id, holder))
                continue
            start = changes[index - 1][1] if index else (created[object_id] or timestamp)
            result.rows.append(
                CodeHistory(
                    content_type=content_type,
                    object_id=object_id,
                    field=item.field,
                    code=old,
                    valid_from=min(start, timestamp),
                    valid_to=timestamp,
                    reason=CodeHistory.Reason.CHANGE,
                    note=NOTE,
                    created_by_id=actor_id,
                )
            )
    result.missing = len(ids) - len(created)
    return result


def _current_holder(model: Any, item: CodeType, code: str, object_id: Any) -> Any:
    """Kod şu an aynı türde başka bir kaydın koduysa o kaydın numarası, değilse None."""
    return (
        model._base_manager.filter(**{item.field: code})
        .exclude(pk=object_id)
        .values_list("pk", flat=True)
        .first()
    )


class Command(BaseCommand):
    help = (
        "Kodlama sistematiğinden önce değişmiş ana veri kodlarını denetim günlüğünden eski kod "
        "geçmişine yükler (canlıya alırken bir kez; tekrar çalıştırmak bir şey yazmaz)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true", help="Yazılacakları say, hiçbir şey yazma."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = bool(options["dry_run"])
        verb = "yazılacak" if dry_run else "yazıldı"
        self.stdout.write("Eski kod geçmişi (denetim günlüğünden):")
        written: dict[str, int] = {}
        objects_total = rows_total = 0
        with transaction.atomic():
            for item in code_types(MASTER):
                pending = pending_rows(item)
                rows = pending.rows
                objects = len({row.object_id for row in rows})
                line = f"  {item.label}: {objects} kayıt, {len(rows)} eski kod {verb}"
                if pending.missing:
                    line += f" ({pending.missing} kayıt bulunamadı, atlandı)"
                self.stdout.write(line)
                for code, object_id, holder in pending.in_use:
                    self.stdout.write(
                        f"    {code}: şu an başka bir kaydın kodu (#{holder}); #{object_id} "
                        "kaydına eski kod olarak yazılmadı."
                    )
                for code, owners in pending.shared().items():
                    numbers = ", ".join(f"#{owner}" for owner in owners)
                    self.stdout.write(f"    {code}: birden çok kaydın eski kodu ({numbers}).")
                objects_total += objects
                rows_total += len(rows)
                if rows and not dry_run:
                    CodeHistory.objects.bulk_create(rows)
                    written[item.key] = len(rows)
            if written:
                log_change(
                    None,
                    None,
                    AuditLog.Action.CUSTOM,
                    {"code_history": written},
                    "Eski kodlar denetim günlüğünden eski kod geçmişine yüklendi "
                    "(backfill_code_history).",
                )
        summary = f"Toplam: {objects_total} kayıt, {rows_total} eski kod {verb}."
        if dry_run:
            summary += " Deneme çalıştırması: hiçbir şey yazılmadı."
        self.stdout.write(self.style.SUCCESS(summary))
