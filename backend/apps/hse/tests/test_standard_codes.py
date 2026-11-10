"""Eski GBF kayıtlarında serbest metin olan dilin ISO 639-1 koduna göçü (hse 0003)."""

import importlib
import unicodedata
from datetime import timedelta

import pytest
from django.apps import apps
from django.db.models import CharField
from django.utils import timezone

from apps.core.models import User
from apps.core.standards import LANGUAGE_CODES
from apps.hse.models import SafetyDataSheet
from apps.masterdata.tests.factories import MaterialFactory

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.hse.migrations.0003_standart_kodlar")

# Eski değer → göçten sonraki değer. Paket 2'den önce düzenleme formu dili olduğu gibi yazardı (en
# çok 8 karakter): Türkçe büyük İ genel küçük harfte iki karakter olur (i + U+0307), İ'li uzun değer
# (İNGİLİZ, İSPANYOL, İbranice) küçük harfle sütuna sığmaz; eski göç bunlarda hata verirdi.
LANGUAGES = {
    " TR ": "tr",
    "Türkçe": "tr",
    "TÜRKÇE": "tr",
    unicodedata.normalize("NFD", "Türkçe"): "tr",  # ü ve ç ayrışık yazılmış
    "turkce": "tr",
    "": "tr",
    "   ": "tr",
    "EN": "en",
    "eng": "en",
    "İNGİLİZ": "en",
    "İngiliz": "en",
    "INGILIZ": "en",
    "i\N{COMBINING DOT ABOVE}ngiliz": "en",  # birleşik noktalı i (U+0307)
    "DEU": "de",
    "Almanca": "de",
    "FRANSIZ": "fr",
    "Fransız": "fr",
    "İSPANYOL": "es",
    "İspanyol": "es",
    "IT": "it",
    "İTALYAN": "it",
    "ARAPÇA": "ar",
    "Rusça": "ru",
    # Tanınmayan değer olduğu gibi kalır: küçük harfe çevrilmez, boşluğu atılmaz.
    "XX": "XX",
    "xx": "xx",
    "İbranice": "İbranice",
    " Kürtçe ": " Kürtçe ",
}


def test_old_sds_languages_become_iso_codes(manager: User) -> None:
    revision_date = timezone.localdate() - timedelta(days=30)
    sheets = {}
    for index, old in enumerate(LANGUAGES):
        # Kayıt doğrudan yazılır: servis bugün bu değerleri düzeltir ya da reddeder.
        sheet = SafetyDataSheet.objects.create(
            material=MaterialFactory.create(),
            revision_no=str(index),
            revision_date=revision_date,
            language=old,
            created_by=manager,
            updated_by=manager,
        )
        sheets[old] = sheet.pk

    migration.normalize_sds_languages(apps, None)

    assert {
        old: SafetyDataSheet.objects.get(pk=pk).language for old, pk in sheets.items()
    } == LANGUAGES


def test_aliases_fit_the_column_and_give_iso_codes() -> None:
    """Eşlemedeki adlar sütuna sığar (daha uzun ad kayıtlı olamaz) ve geçerli ISO 639-1 koduna
    çevrilir."""
    column = SafetyDataSheet._meta.get_field("language")
    assert isinstance(column, CharField)
    assert all(len(name) <= (column.max_length or 0) for name in migration.LANGUAGE_ALIASES)
    assert set(migration.LANGUAGE_ALIASES.values()) <= set(LANGUAGE_CODES)
