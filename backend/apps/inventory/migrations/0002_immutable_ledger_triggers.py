"""Hareket defteri ve soy ağacı veritabanı düzeyinde de değiştirilemez (CLAUDE.md §4.1).

Uygulama katmanı (`ImmutableModel`) zaten engeller; tetikleyici, ham SQL ya da yönetim kabuğundan
yapılacak UPDATE/DELETE'i de reddeder.
"""

from django.db import migrations

TABLES = ("inventory_stockmovement", "inventory_lotlink")

FUNCTION = """
CREATE OR REPLACE FUNCTION inventory_forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% kayitlari degistirilemez ve silinemez', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def _create(table: str) -> str:
    return (
        f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION inventory_forbid_change();"
    )


def _drop(table: str) -> str:
    return f"DROP TRIGGER IF EXISTS {table}_immutable ON {table};"


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [
        migrations.RunSQL(FUNCTION, "DROP FUNCTION IF EXISTS inventory_forbid_change();"),
        *(migrations.RunSQL(_create(table), _drop(table)) for table in TABLES),
    ]
