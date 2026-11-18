"""Cari hesaplar API serializer'ları. Tutar alanları "Fiyatları görür" olmayana yanıtta yoktur
(`AMOUNT_FIELDS`); okuma yanıtları seçicilerin sözlüklerinden üretilir."""

from typing import Any

from rest_framework import serializers

from apps.core.access import PRICES
from apps.core.models import Currency
from apps.core.permissions import has_access
from apps.ledger.models import LedgerEntry

AMOUNT_FIELDS = frozenset(
    {
        "debit",
        "credit",
        "balance",
        "overdue",
        "aging",
        "net_amount",
        "vat_amount",
        "exchange_rate",
        "opening",
        "closing",
        "total_debit",
        "total_credit",
        "totals",
        "suggestion",
    }
)


def can_see_prices(context: dict[str, Any]) -> bool:
    request = context.get("request")
    return request is not None and has_access(request.user, PRICES)


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=20, decimal_places=2, **kwargs)


class AmountHidingMixin:
    """Fiyat yetkisi olmayanda tutar alanlarını yanıttan çıkarır."""

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)  # type: ignore[misc]
        if not can_see_prices(self.context):  # type: ignore[attr-defined]
            for name in AMOUNT_FIELDS:
                data.pop(name, None)
        return data


class AgingSerializer(serializers.Serializer):
    not_due = _money(help_text="Vadesi gelmemiş")
    d1_30 = _money(help_text="Vadesi 1-30 gün geçmiş")
    d31_60 = _money(help_text="Vadesi 31-60 gün geçmiş")
    d61_90 = _money(help_text="Vadesi 61-90 gün geçmiş")
    d90_plus = _money(help_text="Vadesi 90 günden fazla geçmiş")


class BalanceSerializer(AmountHidingMixin, serializers.Serializer):
    currency = serializers.CharField()
    debit = _money()
    credit = _money()
    balance = _money(help_text="Borç − alacak; artı: cari borçlu (B), eksi: cari alacaklı (A)")
    overdue = _money(help_text="Vadesi geçen açık tutar")
    aging = AgingSerializer()
    last_date = serializers.DateField(allow_null=True)


class PartnerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    payment_term_days = serializers.IntegerField(allow_null=True)
    vat_exempt = serializers.BooleanField()
    is_active = serializers.BooleanField()


class PartnerRowSerializer(serializers.Serializer):
    partner = PartnerSerializer()
    balances = BalanceSerializer(many=True)
    missing = serializers.IntegerField(help_text="Tutarı eksik belge sayısı")


class TotalSerializer(serializers.Serializer):
    currency = serializers.CharField()
    open = _money(help_text="Doğal yöndeki bakiyeler: müşteride alacağımız, tedarikçide borcumuz")
    advance = _money(help_text="Ters yöndeki bakiyeler (avans)")
    overdue = _money()


class PartnerListSerializer(serializers.Serializer):
    """Sayfalı liste; `totals` süzgece uyan bütün carilerin toplamıdır (yalnız fiyat hakkıyla)."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = PartnerRowSerializer(many=True)
    totals = TotalSerializer(many=True, required=False)


class EntrySerializer(AmountHidingMixin, serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    shipment_number = serializers.CharField(source="shipment.number", default=None)
    goods_receipt_number = serializers.CharField(source="goods_receipt.number", default=None)
    customer_return_number = serializers.CharField(source="customer_return.number", default=None)
    reversal_of_number = serializers.CharField(source="reversal_of.number", default=None)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "number",
            "entry_date",
            "kind",
            "kind_display",
            "currency",
            "debit",
            "credit",
            "net_amount",
            "vat_amount",
            "exchange_rate",
            "method",
            "method_display",
            "reference",
            "description",
            "shipment",
            "shipment_number",
            "goods_receipt",
            "goods_receipt_number",
            "customer_return",
            "customer_return_number",
            "reversal_of",
            "reversal_of_number",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_created_by_name(self, entry: LedgerEntry) -> str:
        user = entry.created_by
        return (user.get_full_name() or user.username) if user else "Sistem"


class StatementRowSerializer(AmountHidingMixin, serializers.Serializer):
    entry = EntrySerializer()
    balance = _money(help_text="Yürüyen bakiye (borç − alacak)")
    due_date = serializers.DateField(allow_null=True)
    is_reversed = serializers.BooleanField()


class StatementCurrencySerializer(AmountHidingMixin, serializers.Serializer):
    currency = serializers.CharField()
    opening = _money(help_text="Devreden bakiye")
    rows = StatementRowSerializer(many=True)
    total_debit = _money()
    total_credit = _money()
    closing = _money()


class ReturnInfoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField()
    return_date = serializers.DateField()
    status = serializers.CharField()
    shipment_number = serializers.CharField(source="shipment.number", default=None)
    has_credit = serializers.BooleanField(help_text="İade dekontu girilmiş")


class StatementSerializer(serializers.Serializer):
    partner = PartnerSerializer()
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    currencies = StatementCurrencySerializer(many=True)
    returns = ReturnInfoSerializer(many=True)


class SummarySerializer(serializers.Serializer):
    partner = PartnerSerializer()
    balances = BalanceSerializer(many=True)
    missing = serializers.IntegerField()


MISSING_PRICE_KINDS = [("shipment", "Sevkiyat"), ("goods_receipt", "Mal kabul")]


class MissingPriceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MISSING_PRICE_KINDS)
    line_id = serializers.IntegerField()
    document_id = serializers.IntegerField()
    document_number = serializers.CharField()
    document_date = serializers.DateField(allow_null=True)
    partner = PartnerSerializer()
    material_code = serializers.CharField()
    material_name = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    unit_code = serializers.CharField()


class StatementQuerySerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False, allow_null=True, default=None)
    date_to = serializers.DateField(required=False, allow_null=True, default=None)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("date_from"), attrs.get("date_to")
        if start and end and start > end:
            raise serializers.ValidationError({"date_to": "Bitiş tarihi başlangıçtan önce olamaz."})
        return attrs


class ListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, default="")
    with_balance = serializers.BooleanField(required=False, default=False)
    overdue = serializers.BooleanField(required=False, default=False)
    currency = serializers.ChoiceField(
        choices=Currency.choices, required=False, allow_blank=True, default=""
    )
    include_inactive = serializers.BooleanField(required=False, default=False)


class ManualEntrySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=LedgerEntry.Kind.choices)
    entry_date = serializers.DateField()
    currency = serializers.ChoiceField(choices=Currency.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    direction = serializers.ChoiceField(
        choices=[("debit", "Borç"), ("credit", "Alacak")],
        required=False,
        allow_null=True,
        default=None,
        help_text="Yalnız açılış bakiyesinde",
    )
    method = serializers.ChoiceField(
        choices=LedgerEntry.Method.choices, required=False, allow_blank=True, default=""
    )
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    description = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    exchange_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, required=False, allow_null=True, default=None
    )
    customer_return = serializers.IntegerField(required=False, allow_null=True, default=None)


class EntryReverseSerializer(serializers.Serializer):
    entry = serializers.IntegerField()
    reason = serializers.CharField()


class ShipmentLinePriceSerializer(serializers.Serializer):
    line = serializers.IntegerField(help_text="Sevkiyat satırı")
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4)
    currency = serializers.ChoiceField(choices=Currency.choices)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ReturnCreditAmountSerializer(serializers.Serializer):
    currency = serializers.CharField()
    amount = _money()


class ReturnSuggestionSerializer(serializers.Serializer):
    customer_return = serializers.IntegerField()
    suggestion = ReturnCreditAmountSerializer(many=True)
