from django.apps import AppConfig


class MasterdataConfig(AppConfig):
    name = "apps.masterdata"
    label = "masterdata"
    verbose_name = "Ana veriler"

    def ready(self) -> None:
        # Ana veri kodları: biçim Sistem > Kodlama sistematiği ayarından (core.coding). Varsayılan
        # biçimler canlıda kullanılan düzendir (CUMHUR, 2026-11-04).
        from apps.core.coding.registry import register_master_code, register_standard_code
        from apps.core.roles import PLANLAMA
        from apps.masterdata import services
        from apps.masterdata.models import Equipment

        write = (PLANLAMA,)
        register_master_code(
            "masterdata.material",
            label="Malzeme",
            model="masterdata.material",
            default_prefix="MLZ",
            default_width=7,
            scanned=True,
            write_roles=write,
            recode=services.recode_record,
        )
        register_master_code(
            "masterdata.materialcategory",
            label="Malzeme kategorisi",
            model="masterdata.materialcategory",
            default_prefix="KAT",
            default_width=4,
            write_roles=write,
            recode=services.recode_record,
        )
        register_master_code(
            "masterdata.warehouse",
            label="Depo",
            model="masterdata.warehouse",
            default_prefix="DEPO",
            default_width=5,
            write_roles=write,
            recode=services.recode_record,
        )
        register_master_code(
            "masterdata.location",
            label="Lokasyon",
            model="masterdata.location",
            default_prefix="LOKASYON",
            default_width=4,
            scanned=True,
            write_roles=write,
            recode=services.recode_record,
        )
        register_master_code(
            "masterdata.equipment",
            label="Ekipman",
            model="masterdata.equipment",
            default_width=5,
            type_field="equipment_type",
            type_choices=Equipment.Type.choices,
            default_type_prefixes={
                Equipment.Type.MIXING_TANK: "TANK",
                Equipment.Type.STORAGE_TANK: "STOK",
                Equipment.Type.FILLING_LINE: "DOLUM",
                Equipment.Type.SCALE: "TERAZI",
                Equipment.Type.OTHER: "EKIPMAN",
            },
            write_roles=write,
            recode=services.recode_record,
        )
        register_master_code(
            "masterdata.supplier",
            label="Tedarikçi",
            model="masterdata.supplier",
            default_prefix="TED",
            default_width=6,
            write_roles=write,
            recode=services.recode_record,
        )
        register_master_code(
            "masterdata.customer",
            label="Müşteri",
            model="masterdata.customer",
            default_prefix="MUS",
            default_width=6,
            write_roles=write,
            recode=services.recode_record,
        )
        # Yazıcıyı yalnız admin tanımlar (yazma rolü yok).
        register_master_code(
            "masterdata.printer",
            label="Yazıcı",
            model="masterdata.printer",
            default_prefix="YAZICI",
            default_width=3,
            recode=services.recode_record,
        )
        register_standard_code(
            "masterdata.unitofmeasure", label="Birim", model="masterdata.unitofmeasure"
        )
