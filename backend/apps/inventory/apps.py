from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Stok ve lot"

    def ready(self) -> None:
        from apps.core.access import COSTS, PRICES
        from apps.core.attachments import register_attachment_target
        from apps.core.models import User
        from apps.core.permissions import has_access
        from apps.core.records import register_record_type
        from apps.inventory.services import PRICE_CORRECTION_NOTE, RECEIPT_PRICE_FIELDS

        # Tedarikçi CoA'sı, fotoğraf, irsaliye görüntüsü (Adım 2.4).
        register_attachment_target("inventory.lot")
        register_attachment_target("inventory.goodsreceipt")

        def lot_cost_fields(user: User) -> set[str]:
            # Lot maliyeti Maliyetleri görür'e bağlıdır (plan §5.6; Karar D-15).
            return set() if has_access(user, COSTS) else {"unit_cost", "cost_is_estimated"}

        def receipt_price_fields(user: User) -> set[str]:
            # Mal kabulün fiyatları, silinen satır kaydının içinde de, Fiyatları görür'e bağlıdır
            # (plan §5.6, §8 madde 7). Ek masraf ekranda bütünüyle gizli olduğu için silinen ek
            # masraf kaydı da gösterilmez.
            if has_access(user, PRICES):
                return set()
            return {*RECEIPT_PRICE_FIELDS, "amount", "extra_cost"}

        def receipt_price_note(user: User, note: str) -> bool:
            # Fiyat düzeltmesinin notu tutar içerebilir.
            return note.startswith(PRICE_CORRECTION_NOTE) and not has_access(user, PRICES)

        # Yorum, geçmiş, ek: lot ve stok belgelerini giriş yapmış herkes okur (ekranlarıyla aynı).
        register_record_type("inventory.lot", hidden_fields=lot_cost_fields)
        register_record_type(
            "inventory.goodsreceipt",
            hidden_fields=receipt_price_fields,
            nested_hidden=True,
            hidden_note=receipt_price_note,
        )
        register_record_type("inventory.stockadjustment")

        # Belge numaraları: biçim Sistem > Kodlama sistematiği ayarından (core.coding).
        from apps.core.coding.registry import register_document_type

        register_document_type("MK", label="Mal kabul", model="inventory.goodsreceipt")
        register_document_type("SD", label="Sayım düzeltme", model="inventory.stockadjustment")

        # Lot numaraları (Karar D-2): önek ve tarih biçimi kodlama ayarından.
        from apps.core.coding.registry import register_lot_type
        from apps.inventory.selectors import last_lot_number

        register_lot_type("H", label="Satın alma lotu (mal kabul)", counter=last_lot_number)
        register_lot_type("B", label="Üretim şarjı lotu", counter=last_lot_number)
        register_lot_type("D", label="Dolum lotu", counter=last_lot_number)

        # GS1: SSCC sayacı (masterdata.next_sscc) basılmış palet SSCC'lerini atlar. masterdata
        # inventory'yi import etmez; kaynak burada kaydedilir (başka modülün import sırasına
        # bağlı kalmaz).
        from apps.inventory.services import highest_pallet_sscc
        from apps.masterdata.services import register_sscc_source

        register_sscc_source(highest_pallet_sscc)

        # Çıktı doküman kodları: Sistem > Kodlama sistematiği > Çıktılar (ISO 9001 md. 7.5).
        from apps.core.coding.registry import register_output

        register_output(
            "inventory.opening-template",
            label="Açılış stoku",
            group="İçe aktarma şablonları",
            formats=("Excel",),
            suggested_code="FR-SIS-009",
        )
