from django.apps import AppConfig


class TestAppConfig(AppConfig):
    """Yalnızca testlerde yüklenen, çekirdek soyut modelleri deneyen uygulama."""

    name = "apps.core.tests.testapp"
    label = "core_testapp"
    verbose_name = "Çekirdek test uygulaması"

    def ready(self) -> None:
        from apps.core.coding.registry import (
            register_document_type,
            register_lot_type,
            register_master_code,
        )
        from apps.core.records import register_record_type
        from apps.core.roles import PLANLAMA

        # Yorum ve geçmiş testleri: giriş yapmış herkesin okuyabildiği bir kayıt türü.
        register_record_type("core_testapp.widget")

        # Kodlama testleri (core/tests/test_coding.py).
        register_master_code(
            "core_testapp.widget",
            label="Deneme parçası",
            model="core_testapp.widget",
            default_prefix="WDG",
            default_width=4,
            max_length=20,
            write_roles=(PLANLAMA,),
        )
        register_master_code(
            "core_testapp.typedwidget",
            label="Türlü deneme parçası",
            model="core_testapp.typedwidget",
            default_width=3,
            type_field="kind",
            type_choices=(("ALPHA", "Alfa"), ("BETA", "Beta")),
            default_type_prefixes={"ALPHA": "ALF", "BETA": "BET"},
            scanned=True,
        )
        register_document_type("TD", label="Deneme belgesi", model="core_testapp.sampledocument")
        register_document_type("TK", label="Kilitli deneme belgesi", locked=True)
        register_document_type("TZ", label="Öteki deneme belgesi")
        register_lot_type("Q", label="Deneme lotu", counter=_test_lot_counter)


# Deneme lot türünün sayacı: testler sözlüğe değer yazar.
TEST_LOT_COUNTERS: dict[tuple[str, object], int] = {}


def _test_lot_counter(prefix: str, day: object) -> int:
    return TEST_LOT_COUNTERS.get((prefix, day), 0)
