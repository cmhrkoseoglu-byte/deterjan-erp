from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0003_promised_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="salesorder",
            name="overdue_notified_due_date",
            field=models.DateField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="gecikme bildirilen vade",
            ),
        ),
    ]
