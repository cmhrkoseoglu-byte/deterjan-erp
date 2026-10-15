"""Standart laboratuvar testleri (Karar D-7: örnek listeyle başla). Laboratuvar sonradan test
tanımı ekranından düzenler. Var olan kod yeniden yazılmaz."""

from django.db import migrations

# kod, ad, sonuç türü, birim, ondalık hane, yöntem
TESTS = [
    ("PH", "pH (%10 çözelti, 25 °C)", "NUMERIC", "", 2, "pH metre, %10 sulu çözelti, 25 °C"),
    ("VISK", "Viskozite (25 °C)", "NUMERIC", "cP", 0, "Brookfield, iğne/devir spesifikasyonda"),
    ("YOGUNLUK", "Yoğunluk (20 °C)", "NUMERIC", "g/ml", 3, "Piknometre ya da dansimetre, 20 °C"),
    ("AKTIF_MADDE", "Aktif madde", "NUMERIC", "%", 2, "İki fazlı titrasyon (Epton)"),
    ("KATI_MADDE", "Katı madde", "NUMERIC", "%", 2, "Etüv, 105 °C sabit tartım"),
    ("RENK", "Renk", "PASS_FAIL", "", 0, "Standart numuneyle gözle karşılaştırma"),
    ("KOKU", "Koku", "PASS_FAIL", "", 0, "Standart numuneyle karşılaştırma"),
    ("GORUNUS", "Görünüş", "TEXT", "", 0, "Gözle; berrak / bulanık, homojen, tortu"),
    ("DOLUM_MIKTARI", "Dolum miktarı", "NUMERIC", "ml", 0, "Ortalama net dolum (10 adet)"),
    ("SIZDIRMAZLIK", "Sızdırmazlık", "PASS_FAIL", "", 0, "Ters çevirme, 5 dakika"),
    ("ETIKET", "Etiket kontrolü", "PASS_FAIL", "", 0, "Ön/arka etiket, lot ve SKT baskısı"),
]


def seed(apps, schema_editor):
    TestDefinition = apps.get_model("quality", "TestDefinition")
    for code, name, result_type, unit, places, method in TESTS:
        TestDefinition.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "result_type": result_type,
                "unit": unit,
                "decimal_places": places,
                "method": method,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("quality", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
