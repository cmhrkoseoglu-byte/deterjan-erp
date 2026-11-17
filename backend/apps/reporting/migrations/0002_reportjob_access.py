"""Rapor dosyasında yetki bölümü ve hassas veri bilgisi (docs/plan/kisi-yetkileri.md §5.6, §8
madde 12).

Var olan işler için bölüm rapor kodundan gelir. Dosyada maliyet sütunu bugünkü kurala göre
yazılmıştır: stok durumu raporunda, isteyen yönetim ya da admin rolündeyse (ya da süper
kullanıcıysa) maliyet sütunları ve stok değeri özeti dosyadadır. Böylece göçten sonra hiçbir
kişinin indirebildiği dosya değişmez. Fiyat sütunu bugün hiçbir raporda yok.
"""

from django.db import migrations, models
from django.db.models import Q

# Rapor kodu → yetki bölümü (reporting/reports.py, göç anındaki hâli).
SECTIONS = {
    "stock-status": "reporting.stock",
    "stock-movements": "reporting.stock",
    "production": "reporting.production",
    "filling": "reporting.filling",
    "quality": "reporting.lab",
    "shipments": "reporting.shipping_report",
    "task-durations": "reporting.management",
}
# Maliyet sütunu ya da tutar özeti olan raporlar ve onları bugün gören roller (Karar D-15).
COST_REPORTS = ("stock-status",)
COST_ROLES = ("yonetim", "admin")


def forwards(apps, schema_editor):
    ReportJob = apps.get_model("reporting", "ReportJob")
    for code, section in SECTIONS.items():
        ReportJob.objects.filter(report_code=code).update(section=section)
    cost_holders = Q(created_by__is_superuser=True) | Q(created_by__groups__name__in=COST_ROLES)
    ids = (
        ReportJob.objects.filter(report_code__in=COST_REPORTS)
        .filter(cost_holders)
        .values_list("id", flat=True)
        .distinct()
    )
    ReportJob.objects.filter(id__in=list(ids)).update(has_costs=True)


class Migration(migrations.Migration):
    dependencies = [
        ("reporting", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportjob",
            name="section",
            field=models.CharField(
                blank=True, editable=False, max_length=64, verbose_name="yetki bölümü"
            ),
        ),
        migrations.AddField(
            model_name="reportjob",
            name="has_costs",
            field=models.BooleanField(default=False, editable=False, verbose_name="maliyet içerir"),
        ),
        migrations.AddField(
            model_name="reportjob",
            name="has_prices",
            field=models.BooleanField(default=False, editable=False, verbose_name="fiyat içerir"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
