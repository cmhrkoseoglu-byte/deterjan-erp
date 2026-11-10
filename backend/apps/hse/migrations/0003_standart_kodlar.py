import unicodedata

from django.db import migrations

import apps.masterdata.fields
from apps.core.standards import LANGUAGE_CODES

# Eski GBF kayıtlarında dil serbest metindi (en çok 8 karakter; düzenleme formu küçük harfe
# çevirmezdi). Değer ISO 639-1 koduna çevrilir: baştaki ve sondaki boşluk atılır, genel ve Türkçe
# kurala göre küçük harf yapılır (İ → i, I → ı; İ'nin genel küçük harfindeki birleşik nokta U+0307
# atılır), yaygın üç harfli kodlar ve Türkçe/İngilizce adlar iki harfli koda çevrilir; boş değer
# "tr" olur. Yalnız geçerli bir ISO 639-1 koduna karşılık gelen değer yazılır: tanınmayan değer
# olduğu gibi kalır (boşluğu, büyük harfi de; kayıt düzenlenirken listeden seçilir). Göç hiçbir
# değerde hata vermez. Adlar sütuna sığan biçimleriyle yazılır (8 karakterden uzun ad kayıtlı
# olamaz).
LANGUAGE_ALIASES = {
    "tur": "tr",
    "türkçe": "tr",
    "turkce": "tr",
    "türk": "tr",
    "turkish": "tr",
    "eng": "en",
    "ing": "en",
    "ingiliz": "en",
    "english": "en",
    "deu": "de",
    "ger": "de",
    "alman": "de",
    "almanca": "de",
    "german": "de",
    "fra": "fr",
    "fre": "fr",
    "fransız": "fr",
    "french": "fr",
    "spa": "es",
    "ispanyol": "es",
    "spanish": "es",
    "ita": "it",
    "italyan": "it",
    "italian": "it",
    "ara": "ar",
    "arap": "ar",
    "arapça": "ar",
    "arabic": "ar",
    "rus": "ru",
    "rusça": "ru",
    "russian": "ru",
}
_LANGUAGES = frozenset(LANGUAGE_CODES)


def language_code(value: str | None) -> str | None:
    """Eski dil değerinin ISO 639-1 kodu; boşsa "tr", tanınmazsa None."""
    # Karşılaştırma için Unicode biçimi birleştirilir (ayrışık yazılmış ü, ç; tam genişlikli harf).
    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        return "tr"
    # Önce genel küçük harf (ITALIAN → italian), sonra Türkçe (FRANSIZ → fransız).
    turkish = text.replace("İ", "i").replace("I", "ı")
    for lowered in (text.lower(), turkish.lower()):
        key = lowered.replace("\N{COMBINING DOT ABOVE}", "")
        code = LANGUAGE_ALIASES.get(key, key)
        if code in _LANGUAGES:
            return code
    return None


def normalize_sds_languages(apps, schema_editor):
    SafetyDataSheet = apps.get_model("hse", "SafetyDataSheet")
    for sheet in SafetyDataSheet.objects.all().only("pk", "language"):
        code = language_code(sheet.language)
        if code is not None and code != sheet.language:
            SafetyDataSheet.objects.filter(pk=sheet.pk).update(language=code)


class Migration(migrations.Migration):
    """H/P/EUH kodlarında büyük/küçük harf korunur (veritabanı değişmez); GBF dili ISO 639-1."""

    dependencies = [
        ("hse", "0002_seed_hazard_statements"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hazardstatement",
            name="code",
            field=apps.masterdata.fields.CodeField(
                max_length=32, unique=True, upper=False, verbose_name="kod"
            ),
        ),
        migrations.RunPython(normalize_sds_languages, migrations.RunPython.noop),
    ]
