"""Test yardımcıları: numuneyi spesifikasyonuna uygun sonuçlarla serbest bırakma.

Diğer modüllerin uçtan uca testleri lotu gerçek kalite akışından geçirmek için kullanır.
"""

from decimal import Decimal

from apps.core.models import User
from apps.inventory.models import Lot
from apps.masterdata.models import Location
from apps.quality import services
from apps.quality.models import (
    QualityDecision,
    Sample,
    Specification,
    SpecificationLine,
    TestDefinition,
)

ResultType = TestDefinition.ResultType


def ensure_specification(lab: User, sample: Sample) -> Specification:
    """Numunenin spesifikasyonu yoksa malzeme + aşama için tek satırlı (renk) bir sürüm açıp
    onaylar ve numuneye atar."""
    sample.refresh_from_db()
    if sample.specification is not None:
        return sample.specification
    spec = services.approved_specification(sample.lot.material, sample.stage)
    if spec is None:
        spec = services.create_specification(
            lab,
            material=sample.lot.material,
            sample_stage=sample.stage,
            lines=[{"test": TestDefinition.objects.get(code="RENK")}],
        )
        services.approve_specification(lab, spec)
    services.assign_specification(lab, sample, spec)
    return spec


def passing_value(line: SpecificationLine) -> dict[str, object]:
    """Satırı karşılayan sonuç değeri."""
    if line.test.result_type == ResultType.NUMERIC:
        if line.target_value is not None:
            return {"numeric_value": line.target_value}
        low, high = line.min_value, line.max_value
        if low is not None and high is not None:
            return {"numeric_value": (low + high) / Decimal(2)}
        return {"numeric_value": low if low is not None else high}
    if line.test.result_type == ResultType.PASS_FAIL:
        return {"passed": True}
    return {"text_value": line.text_expected or "Uygun", "passed": True}


def pass_sample(
    lab: User,
    sample: Sample,
    *,
    decision: str = QualityDecision.Decision.RELEASE,
    release_location: Location | None = None,
) -> QualityDecision:
    """Numunenin tüm satırlarına uygun sonuç girer ve karar verir (varsayılan: serbest)."""
    spec = ensure_specification(lab, sample)
    for line in spec.lines.select_related("test"):
        services.record_result(lab, sample, line, **passing_value(line))  # type: ignore[arg-type]
    reason = "" if decision == QualityDecision.Decision.RELEASE else "Test"
    return services.decide(lab, sample, decision, reason, release_location=release_location)


def open_sample_for(lot: Lot, stage: str | None = None) -> Sample:
    """Lotun açık numunesi (aşama verilirse o aşamada)."""
    queryset = Sample.objects.filter(lot=lot, status__in=services.OPEN_SAMPLE_STATUSES)
    if stage is not None:
        queryset = queryset.filter(stage=stage)
    return queryset.get()
