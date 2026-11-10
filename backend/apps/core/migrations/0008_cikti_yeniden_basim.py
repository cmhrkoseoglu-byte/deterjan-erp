import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

# Yeniden basım ilk basımdaki gibi (CUMHUR, 2026-11-05): revizyon, girildiği andaki doküman no ve
# ilk yayın tarihini saklar; bandın açılıp kapanması tarihiyle tutulur.


def backfill_snapshots_and_band(apps, schema_editor):
    """Var olan revizyonlara çıktının bugünkü doküman no ve ilk yayın tarihi yazılır. Bugün bandı
    açık her çıktıya bir "açık" kaydı: ilk revizyonun yürürlük tarihinden (revizyon yoksa kaydın
    açıldığı günden) beri açık sayılır."""
    OutputDocument = apps.get_model("core", "OutputDocument")
    OutputDocumentRevision = apps.get_model("core", "OutputDocumentRevision")
    OutputBandChange = apps.get_model("core", "OutputBandChange")
    for row in OutputDocument.objects.order_by("pk"):
        OutputDocumentRevision.objects.filter(
            output=row, doc_code="", first_issue_date__isnull=True
        ).update(doc_code=row.doc_code, first_issue_date=row.first_issue_date)
        if not row.is_active or OutputBandChange.objects.filter(output=row).exists():
            continue
        first = (
            OutputDocumentRevision.objects.filter(output=row)
            .order_by("revision_date", "revision_no")
            .first()
        )
        effective = (
            first.revision_date if first is not None else timezone.localtime(row.created_at).date()
        )
        OutputBandChange.objects.create(output=row, is_active=True, effective_date=effective)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_cikti_dokumanlari"),
    ]

    operations = [
        migrations.AddField(
            model_name="outputdocumentrevision",
            name="doc_code",
            field=models.CharField(
                blank=True, default="", max_length=32, verbose_name="doküman no"
            ),
        ),
        migrations.AddField(
            model_name="outputdocumentrevision",
            name="first_issue_date",
            field=models.DateField(blank=True, null=True, verbose_name="ilk yayın tarihi"),
        ),
        migrations.CreateModel(
            name="OutputBandChange",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("is_active", models.BooleanField(verbose_name="çıktıya basılsın")),
                ("effective_date", models.DateField(verbose_name="geçerlilik tarihi")),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="kayıt zamanı"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="değiştiren",
                    ),
                ),
                (
                    "output",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="band_changes",
                        to="core.outputdocument",
                        verbose_name="çıktı dokümanı",
                    ),
                ),
            ],
            options={
                "verbose_name": "bant değişikliği",
                "verbose_name_plural": "bant değişiklikleri",
                "ordering": ["output", "-effective_date", "-id"],
            },
        ),
        migrations.RunPython(backfill_snapshots_and_band, migrations.RunPython.noop),
    ]
