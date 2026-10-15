"""Kalite okuma sorguları: numune kuyruğu, lotun kalite geçmişi."""

from django.db.models import QuerySet

from apps.inventory.models import Lot
from apps.quality.models import Sample

QUEUE_STATUSES = (
    Sample.Status.PENDING,
    Sample.Status.IN_TEST,
    Sample.Status.AWAITING_APPROVAL,
)


def sample_queryset() -> QuerySet[Sample]:
    """Liste ve detay için ilişkileri yüklenmiş numuneler."""
    return Sample.objects.select_related(
        "lot__material__base_unit",
        "specification",
        "taken_by",
        "retain_location",
        "created_by",
    )


def sample_queue() -> QuerySet[Sample]:
    """Laboratuvar kuyruğu: kararı verilmemiş numuneler, en eski önce (bekleme süresi)."""
    return sample_queryset().filter(status__in=QUEUE_STATUSES).order_by("created_at", "id")


def lot_samples(lot: Lot) -> QuerySet[Sample]:
    """Lotun numuneleri (yeniden eskiye)."""
    return sample_queryset().filter(lot=lot).order_by("-created_at", "-id")
