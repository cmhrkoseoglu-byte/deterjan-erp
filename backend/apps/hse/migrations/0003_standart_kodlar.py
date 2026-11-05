from django.db import migrations

import apps.masterdata.fields

# Eski GBF kayıtlarında dil serbest metindi. ISO 639-1 koduna çevrilir: boşluklar atılır, küçük harf
# yapılır; yaygın üç harfli kodlar ve Türkçe/İngilizce adlar iki harfli koda çevrilir. Tanınmayan
# değer olduğu gibi kalır (kayıt düzenlenirken listeden seçilir).
LANGUAGE_ALIASES = {
    "tur": "tr",
    "türkçe": "tr",
    "turkce": "tr",
    "turkish": "tr",
    "eng": "en",
    "ingilizce": "en",
    "english": "en",
    "deu": "de",
    "ger": "de",
    "almanca": "de",
    "german": "de",
    "fra": "fr",
    "fre": "fr",
    "fransızca": "fr",
    "french": "fr",
    "ara": "ar",
    "arapça": "ar",
    "rus": "ru",
    "rusça": "ru",
}


def normalize_sds_languages(apps, schema_editor):
    SafetyDataSheet = apps.get_model("hse", "SafetyDataSheet")
    for sheet in SafetyDataSheet.objects.all().only("pk", "language"):
        value = (sheet.language or "").strip().lower()
        value = LANGUAGE_ALIASES.get(value, value) or "tr"
        if value != sheet.language:
            SafetyDataSheet.objects.filter(pk=sheet.pk).update(language=value)


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
