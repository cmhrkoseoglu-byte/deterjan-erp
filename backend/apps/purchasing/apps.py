from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    name = "apps.purchasing"
    label = "purchasing"
    verbose_name = "Satın alma"

    def ready(self) -> None:
        import re

        from apps.core.access import PRICES
        from apps.core.models import User
        from apps.core.permissions import has_access
        from apps.core.records import register_record_type
        from apps.purchasing.access import ORDERS
        from apps.purchasing.api.serializers import PRICE_FIELDS

        # Eski onaya gönderme ve onay notları tutar taşır ("Tutar 12.345,60 TL", "Onay: tutar …
        # TL (kur …), limit …"); yenilerde tutar, kur ve limit alan satırlarıdır (plan §8 madde 7).
        amount_note = re.compile(r"Tutar [\d.]+,\d{2} TL|Onay: tutar [\d.]+,\d{2} TL \(kur .*")

        def price_fields(user: User) -> frozenset[str]:
            # Siparişi görüp Fiyatları görür'ü olmayan geçmişte de tutarları görmez; silinen satırın
            # içindeki fiyatlar dahil (plan §5.6).
            return frozenset() if has_access(user, PRICES) else PRICE_FIELDS

        def price_note(user: User, note: str) -> bool:
            return amount_note.fullmatch(note) is not None and not has_access(user, PRICES)

        register_record_type(
            "purchasing.purchaseorder",
            readers=(ORDERS,),
            hidden_fields=price_fields,
            nested_hidden=True,
            hidden_note=price_note,
        )

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("ST", label="Satın alma talebi", model="purchasing.purchaserequest")
        register_document_type("SA", label="Satın alma siparişi", model="purchasing.purchaseorder")

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "purchasing.order",
            label="Satın alma siparişi",
            group="Satın alma",
            formats=("PDF",),
            suggested_code="FR-SAT-001",
        )
