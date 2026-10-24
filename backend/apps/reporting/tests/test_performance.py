"""Kabul kriteri: yönetim panosu demo verisiyle 2 sn altında açılır.

Demo verisinin (`seed_demo`) üstüne hacim eklenir: izlenebilirlik performans verisi (≥ 10.000
stok hareketi, 1.500+ lot) ve 3.000 görev (bir kısmı gecikmiş). Panolar sabit sayıda sorguyla
çalışır; sorgu sayısı da sınırlanır ki veri büyüdükçe süre satır sayısıyla artmasın.
"""

import time
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.roles import DEPO, SEVKIYAT, YONETIM
from apps.inventory.testing import assert_stock_invariants
from apps.traceability.tests.perfdata import build_trace_data
from apps.workflow.models import Task

pytestmark = pytest.mark.django_db
BASE = "/api/v1/reporting/dashboards"
LIMIT_SECONDS = 2.0
QUERY_LIMIT = 30
# Yönetim panosu daha çok bölüm toplar (onay bekleyenler, son 14 gün, sevkiyat özeti); sorgu
# sayısı yine sabittir, satır sayısıyla artmaz.
QUERY_LIMITS = {"management": 36}


@override_settings(DEBUG=True)
def test_dashboards_open_fast_on_demo_data(roles, client_for):
    call_command("seed_demo", stdout=StringIO())
    data = build_trace_data()
    now = timezone.now()
    groups = list(Group.objects.filter(name__in=(DEPO, SEVKIYAT, YONETIM)))
    Task.objects.bulk_create(
        [
            Task(
                title=f"Görev {i}",
                assigned_role=groups[i % len(groups)],
                due_at=now - timedelta(hours=i % 48) if i % 3 == 0 else None,
            )
            for i in range(3000)
        ],
        batch_size=1000,
    )
    assert data.movement_count >= 10_000
    client = client_for(YONETIM)
    for code in ("management", "warehouse", "lab", "production", "shipping"):
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = client.get(f"{BASE}/{code}/")
        elapsed = time.perf_counter() - start
        assert response.status_code == 200
        print(f"Pano {code}: {elapsed:.3f} sn, {len(queries)} sorgu")
        assert elapsed < LIMIT_SECONDS, f"{code} panosu {elapsed:.2f} sn sürdü"
        limit = QUERY_LIMITS.get(code, QUERY_LIMIT)
        assert len(queries) <= limit, f"{code}: {len(queries)} sorgu"
    management = client.get(f"{BASE}/management/").json()
    assert management["tasks"]["overdue_total"] >= 900
    assert_stock_invariants()
