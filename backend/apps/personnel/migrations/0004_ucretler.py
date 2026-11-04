"""Ücretler (`EmployeeWage`) maliyet modülünden buraya taşındı (2026-11-01, docs/DECISIONS.md
"Personel bordrosu").

Yalnızca model durumu açılır; tablo (`costing_employeewage`) costing/0002 ile açılmıştır ve adı,
kayıtları ve kısıtlarıyla yerinde kalır. Sıralamayı costing/0003 `run_before` ile verir: personel
modülünün kodu ve geçişleri maliyeti anmaz (CLAUDE.md §3). Geçiş grafiğinde bu geçiş
costing/0003'ten sonra gelir; o geçiş geri alınırken bu da geri alınır.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("personnel", "0003_puantaj"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="EmployeeWage",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "created_at",
                            models.DateTimeField(
                                auto_now_add=True, verbose_name="oluşturulma zamanı"
                            ),
                        ),
                        (
                            "updated_at",
                            models.DateTimeField(auto_now=True, verbose_name="güncellenme zamanı"),
                        ),
                        (
                            "gross_monthly",
                            models.DecimalField(
                                decimal_places=2,
                                max_digits=18,
                                verbose_name="brüt aylık ücret (TL)",
                            ),
                        ),
                        ("valid_from", models.DateField(verbose_name="geçerlilik başlangıcı")),
                        ("note", models.CharField(blank=True, max_length=200, verbose_name="not")),
                        (
                            "is_active",
                            models.BooleanField(db_index=True, default=True, verbose_name="aktif"),
                        ),
                        (
                            "removed_at",
                            models.DateTimeField(
                                blank=True, null=True, verbose_name="kaldırılma zamanı"
                            ),
                        ),
                        (
                            "removal_reason",
                            models.CharField(
                                blank=True, max_length=500, verbose_name="kaldırma nedeni"
                            ),
                        ),
                        (
                            "created_by",
                            models.ForeignKey(
                                blank=True,
                                editable=False,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="+",
                                to=settings.AUTH_USER_MODEL,
                                verbose_name="oluşturan",
                            ),
                        ),
                        (
                            "employee",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="wages",
                                to="personnel.employee",
                                verbose_name="personel",
                            ),
                        ),
                        (
                            "removed_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="+",
                                to=settings.AUTH_USER_MODEL,
                                verbose_name="kaldıran",
                            ),
                        ),
                        (
                            "updated_by",
                            models.ForeignKey(
                                blank=True,
                                editable=False,
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="+",
                                to=settings.AUTH_USER_MODEL,
                                verbose_name="güncelleyen",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "ücret",
                        "verbose_name_plural": "ücretler",
                        "db_table": "costing_employeewage",
                        "ordering": ["employee", "-valid_from", "-id"],
                        "constraints": [
                            models.UniqueConstraint(
                                condition=models.Q(("is_active", True)),
                                fields=("employee", "valid_from"),
                                name="costing_wage_employee_date_uniq",
                                violation_error_message=(
                                    "Bu kişinin bu tarihte başlayan bir ücreti zaten var."
                                ),
                            ),
                            models.CheckConstraint(
                                condition=models.Q(("gross_monthly__gt", 0)),
                                name="costing_wage_positive",
                                violation_error_message="Brüt ücret sıfırdan büyük olmalı.",
                            ),
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
