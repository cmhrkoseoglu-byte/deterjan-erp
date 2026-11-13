from django.apps import AppConfig


class HseConfig(AppConfig):
    name = "apps.hse"
    label = "hse"
    verbose_name = "İSG ve çevre"

    def ready(self) -> None:
        from apps.core.attachments import register_attachment_target
        from apps.core.records import register_record_type
        from apps.hse import services  # stok hareketi kancasını kaydeder
        from apps.hse.access import INCIDENT_REPORT, INCIDENTS, SDS, WASTE

        # GBF PDF'i, atık taşıma formu, olay fotoğrafı.
        register_attachment_target("hse.safetydatasheet", can_add=services.can_attach_sds)
        register_attachment_target("hse.wasterecord", can_add=services.can_attach_waste)
        register_attachment_target("hse.incident", can_add=services.can_attach_incident)
        # Yorum, geçmiş, ek: ekranlarıyla aynı kural (GBF arşivi, Atık okuması). Olay sağlık verisi
        # içerir: Olaylar ve kazalar: Görür'ü olan hepsini, öteki kişi yalnızca kendi
        # bildirdiklerini görür; rolsüz kullanıcı hiçbirini (docs/KVKK.md).
        register_record_type("hse.safetydatasheet", readers=(SDS,))
        register_record_type("hse.wasterecord", readers=(WASTE,))
        register_record_type(
            "hse.incident",
            readers=(INCIDENTS, INCIDENT_REPORT),
            visible=services.incidents_visible_to,
        )

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("AT", label="Atık kaydı", model="hse.wasterecord")
        register_document_type("OL", label="Olay kaydı", model="hse.incident")

        # H/P/EUH ifadeleri uluslararası standart kodlardır (GHS/CLP): kodlama ayarında değişmez.
        from apps.core.coding.registry import register_standard_code

        register_standard_code(
            "hse.hazardstatement",
            label="Tehlike ve önlem ifadesi (H/P/EUH)",
            model="hse.hazardstatement",
        )

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "hse.sds-gaps",
            label="Eksik GBF listesi",
            group="İSG",
            formats=("Excel",),
            suggested_code="LS-ISG-001",
        )
