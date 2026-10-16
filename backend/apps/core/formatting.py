"""Kullanıcıya giden metinler (görev, bildirim, hata mesajı, PDF) için Türkçe sayı biçimleri."""

from decimal import Decimal, InvalidOperation


def format_money(value: Decimal | str | None) -> str:
    """Tutar: binlik ayırıcı nokta, ondalık virgül, 2 basamak (`1250000` → `1.250.000,00`).

    Sayıya çevrilemeyen değer olduğu gibi döner (eski olay yükleri bozulmasın)."""
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return str(value)
    text = f"{amount:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")
