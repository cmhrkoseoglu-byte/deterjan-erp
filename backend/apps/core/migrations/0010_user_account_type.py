from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_kisiye_ozel_yetkiler"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="account_type",
            field=models.CharField(
                choices=[
                    ("", "Çalışan"),
                    ("customer_portal", "Müşteri portalı"),
                    ("supplier_portal", "Tedarikçi portalı"),
                ],
                blank=True,
                default="",
                editable=False,
                max_length=16,
                verbose_name="hesap türü",
            ),
        ),
    ]
