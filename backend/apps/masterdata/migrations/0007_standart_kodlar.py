from django.db import migrations, models

# Standart birimlerin UN/ECE Rec 20 ortak kodu ve sembolü (GİB UBL-TR birim listesi bu listeye
# dayanır; ambalaj birimleri Rec 21 kodunun başına "X" konarak yazılır). Koli XCT, palet XPX
# (CUMHUR, 2026-11-05). Admin sonradan değiştirebilir.
UNITS = {
    "KG": ("KGM", "kg"),
    "G": ("GRM", "g"),
    "LT": ("LTR", "L"),
    "ML": ("MLT", "mL"),
    "ADET": ("C62", ""),
    "KOLI": ("XCT", ""),
    "PALET": ("XPX", ""),
}


def fill_unit_codes(apps, schema_editor):
    UnitOfMeasure = apps.get_model("masterdata", "UnitOfMeasure")
    for code, (unece_code, symbol) in UNITS.items():
        UnitOfMeasure.objects.filter(code=code, unece_code="").update(
            unece_code=unece_code, symbol=symbol
        )


class Migration(migrations.Migration):
    dependencies = [
        ("masterdata", "0006_gs1"),
    ]

    operations = [
        migrations.AddField(
            model_name="unitofmeasure",
            name="unece_code",
            field=models.CharField(
                blank=True,
                help_text="UN/ECE Rec 20 ortak kodu: KGM, GRM, LTR, MLT, C62; ambalaj XCT, XPX",
                max_length=3,
                verbose_name="UN/ECE kodu",
            ),
        ),
        migrations.AddField(
            model_name="unitofmeasure",
            name="symbol",
            field=models.CharField(
                blank=True, help_text="kg, g, L, mL", max_length=8, verbose_name="sembol"
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="country_code",
            field=models.CharField(
                default="TR",
                help_text="ISO 3166-1 alpha-2 (TR, DE, IQ …)",
                max_length=2,
                verbose_name="ülke",
            ),
        ),
        migrations.AddField(
            model_name="supplier",
            name="country_code",
            field=models.CharField(
                default="TR",
                help_text="ISO 3166-1 alpha-2 (TR, DE, IQ …)",
                max_length=2,
                verbose_name="ülke",
            ),
        ),
        migrations.RunPython(fill_unit_codes, migrations.RunPython.noop),
    ]
