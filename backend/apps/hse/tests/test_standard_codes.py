"""Eski GBF kayıtlarında serbest metin olan dilin ISO 639-1 koduna göçü (hse 0003)."""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from apps.core.models import User
from apps.hse import services
from apps.hse.models import SafetyDataSheet
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.hse.migrations.0003_standart_kodlar")


def test_old_sds_languages_become_iso_codes(manager: User) -> None:
    revision_date = timezone.localdate() - timedelta(days=30)
    values = {" TR ": "tr", "Türkçe": "tr", "eng": "en", "DEU": "de", "": "tr", "xx": "xx"}
    sheets = {}
    for index, old in enumerate(values):
        sheet = services.create_sds(
            manager,
            {
                "material": MaterialFactory.create(),
                "revision_no": str(index),
                "revision_date": revision_date,
            },
        )
        SafetyDataSheet.objects.filter(pk=sheet.pk).update(language=old)
        sheets[old] = sheet.pk

    migration.normalize_sds_languages(apps, None)

    assert {
        old: SafetyDataSheet.objects.get(pk=pk).language for old, pk in sheets.items()
    } == values
