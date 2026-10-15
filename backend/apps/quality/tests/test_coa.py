"""Analiz sertifikası: yalnızca serbest bırakılan lot için, sonuç tablosu ve onaylayanla."""

from decimal import Decimal

import pytest

from apps.core.exceptions import BusinessRuleError
from apps.inventory.tests.factories import storage_location
from apps.quality import coa, services
from apps.quality.models import QualityDecision
from apps.quality.tests.factories import line, quarantined_raw_lot, sample_with_spec, tdef

D = Decimal


def test_coa_contents(lab, manager):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(lab, lot)
    services.record_result(lab, sample, line(sample, "PH"), numeric_value=D("8.2"))
    services.record_result(lab, sample, line(sample, "GORUNUS"), text_value="Berrak")
    with pytest.raises(BusinessRuleError) as exc:
        coa.coa_pdf(sample)
    assert exc.value.code == "coa_not_available"
    decision = services.decide(
        lab,
        sample,
        QualityDecision.Decision.CONDITIONAL_RELEASE,
        "Müşteri onaylı",
        release_location=storage_location(),
    )
    assert coa.coa_available(sample) is False
    services.review_conditional_release(manager, decision, approve=True)
    assert coa.coa_pdf(sample).startswith(b"%PDF")
    info = dict(coa.info_rows(sample))
    assert info["Lot no"] == lot.lot_no and info["Numune no"] == sample.number
    assert lot.material.name in info["Ürün"]
    rows = [coa.result_row(result) for result in services.current_results(sample)]
    assert [tdef("PH").name, "", "6,00 – 8,00", "8,20", "Spesifikasyon dışı"] in rows
    assert any(row[3] == "Berrak" and row[4] == "Uygun" for row in rows)
    decision.refresh_from_db()
    labels = dict(coa.decision_rows(decision))
    assert labels["Şartlı kabul gerekçesi"] == "Müşteri onaylı"
    assert labels["Yönetim onayı"].startswith(str(manager))
    assert labels["Onaylayan"].startswith(str(lab))


def test_format_decimal():
    assert coa.format_decimal(D("7.5"), 2) == "7,50"
    assert coa.format_decimal(None, 2) == ""


def test_spec_text_variants(lab):
    lot, _q = quarantined_raw_lot()
    sample = sample_with_spec(
        lab,
        lot,
        lines=[
            {"test": services.TestDefinition.objects.get(code="PH"), "min_value": D("6")},
            {"test": services.TestDefinition.objects.get(code="VISK"), "max_value": D("1500")},
            {"test": services.TestDefinition.objects.get(code="RENK")},
        ],
    )
    assert coa.spec_text(line(sample, "PH")) == "≥ 6,00"
    assert coa.spec_text(line(sample, "VISK")).startswith("≤ 1500")
    assert coa.spec_text(line(sample, "RENK")) == "Uygun"
