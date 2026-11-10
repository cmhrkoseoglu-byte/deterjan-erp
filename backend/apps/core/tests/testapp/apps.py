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
            recode=_test_recode,
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


def _test_recode(actor, instance, new_code, note, run_id, reason):  # type: ignore[no-untyped-def]
    """Deneme parçasının kod göçü: yalnız kodu değiştirir ve eski kodu saklar."""
    from apps.core.audit import log_change
    from apps.core.coding import registry, services
    from apps.core.models import AuditLog

    old = instance.code
    instance.code = new_code
    instance.save(update_fields=["code", "updated_at"])
    log_change(actor, instance, AuditLog.Action.UPDATE, {"code": [old, new_code]}, note)
    item = registry.get_code_type("core_testapp.widget")
    services.record_code_change(actor, item, instance, old, reason=reason, note=note, run_id=run_id)
    return instance
