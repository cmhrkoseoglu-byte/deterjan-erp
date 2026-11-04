"""Kod biçiminin saf fonksiyonları: numara üretme, koddan sıra no okuma, kural denetimi.

Veritabanına dokunmaz. Biçim `Format` nesnesiyle verilir (`selectors.effective_format`).

- Ana veri kodu: `<önek>-<sıra no>` (`MLZ-0000001`). Sıra hanesini aşan numara bir hane uzar;
  uzun biçimde ilk hane sıfır olamaz (böylece `MLZ-00000001` ile `MLZ-0000001` karışmaz).
- Belge numarası: `<önek>-<yıl>-<sıra no>` (`UE-2026-00001`); yıl `YYYY` ya da `YY`.
- Lot numarası: `<önek>-<tarih>-<sıra no>` (`H-20261104-001`); tarih ISO 8601 takvim tarihi
  (`YYYYMMDD`), ISO 8601 sıra tarihi (`YYYYDDD`) ya da GS1 düzeni (`YYMMDD`).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from apps.core.coding.registry import DOCUMENT, LOT, MASTER
from apps.core.exceptions import BusinessRuleError

SEPARATOR = "-"
YEAR_FORMATS: dict[str, str] = {"YYYY": "4 haneli yıl (ISO 8601)", "YY": "2 haneli yıl"}
DATE_FORMATS: dict[str, str] = {
    "YYYYMMDD": "YYYYAAGG: ISO 8601 takvim tarihi",
    "YYYYDDD": "YYYYGGG: ISO 8601 sıra tarihi (yılın günü)",
    "YYMMDD": "YYAAGG: GS1 tarih düzeni",
}
WIDTH_LIMITS: dict[str, tuple[int, int]] = {MASTER: (2, 9), DOCUMENT: (4, 7), LOT: (3, 5)}
PREFIX_RULES: dict[str, tuple[re.Pattern[str], str]] = {
    MASTER: (
        re.compile(r"^[A-Z][A-Z0-9]{0,11}$"),
        "Önek harfle başlamalı ve yalnızca büyük harf (A-Z) ile rakam içermelidir (en fazla 12 "
        "karakter).",
    ),
    DOCUMENT: (
        re.compile(r"^[A-Z][A-Z0-9]{0,9}$"),
        "Belge öneki harfle başlamalı ve yalnızca büyük harf (A-Z) ile rakam içermelidir (en "
        "fazla 10 karakter).",
    ),
    LOT: (
        re.compile(r"^[A-Z]{1,4}$"),
        "Lot öneki 1-4 büyük harf (A-Z) olmalıdır.",
    ),
}
# GS1 AI (10) lot alanı en çok 20 karakter; SK numarası Excel sayfa adı olduğu için en çok 31.
MAX_LENGTH: dict[str, int] = {DOCUMENT: 31, LOT: 20}


@dataclass(frozen=True)
class Format:
    """Bir kod türünün etkin biçimi (kayıttaki varsayılan + admin'in değiştirdikleri)."""

    kind: str
    prefix: str
    width: int
    type_prefixes: Mapping[str, str] = field(default_factory=dict)
    year_format: str = "YYYY"
    date_format: str = "YYYYMMDD"
    free: bool = False

    def prefixes(self) -> list[str]:
        """Bu biçimin bütün önekleri (türe göre önekte her tür için)."""
        if self.type_prefixes:
            return sorted(set(self.type_prefixes.values()))
        return [self.prefix] if self.prefix else []


def sequence_text(number: int, width: int) -> str:
    return f"{number:0{width}d}"


def stem(prefix: str) -> str:
    """Sayaç anahtarı: önek + ayraç (`MLZ-`)."""
    return f"{prefix}{SEPARATOR}"


def master_code(prefix: str, width: int, number: int) -> str:
    """`MLZ`, 7, 24 → `MLZ-0000024`."""
    return f"{stem(prefix)}{sequence_text(number, width)}"


def master_number(code: str, prefix: str, width: int) -> int | None:
    """`MLZ-0000024` → 24; biçime (önek ve sıra hanesi) uymuyorsa None."""
    pattern = rf"^{re.escape(stem(prefix))}(\d{{{width}}}|[1-9]\d{{{width},}})$"
    match = re.match(pattern, code or "")
    return int(match.group(1)) if match else None


def loose_number(code: str, prefix: str) -> int | None:
    """Sıra hanesine bakmadan önekten sonraki sayı (`MLZ-24` → 24); sayaç başlangıcı için."""
    head = stem(prefix)
    rest = (code or "")[len(head) :] if (code or "").startswith(head) else ""
    return int(rest) if rest.isdigit() else None


def year_text(year: int, year_format: str) -> str:
    return f"{year:04d}" if year_format == "YYYY" else f"{year % 100:02d}"


def date_text(day: date, date_format: str) -> str:
    if date_format == "YYYYMMDD":
        return day.strftime("%Y%m%d")
    if date_format == "YYYYDDD":
        return f"{day:%Y}{day.timetuple().tm_yday:03d}"
    if date_format == "YYMMDD":
        return day.strftime("%y%m%d")
    raise ValueError(f"Tanımsız tarih biçimi: {date_format}")


def document_number(fmt: Format, year: int, number: int) -> str:
    """`UE`, YYYY, 5 → `UE-2026-00001`."""
    return SEPARATOR.join(
        (fmt.prefix, year_text(year, fmt.year_format), sequence_text(number, fmt.width))
    )


def lot_number(fmt: Format, day: date, number: int) -> str:
    """`H`, YYYYMMDD, 3 → `H-20261104-001`."""
    return SEPARATOR.join(
        (fmt.prefix, date_text(day, fmt.date_format), sequence_text(number, fmt.width))
    )


def largest_number(width: int) -> int:
    return int("9" * width)


# --- kurallar --------------------------------------------------------------------------------


def validate_prefix(kind: str, prefix: str) -> None:
    pattern, message = PREFIX_RULES[kind]
    if not pattern.match(prefix or ""):
        raise BusinessRuleError("invalid_prefix", message)


def validate_width(kind: str, width: int) -> None:
    low, high = WIDTH_LIMITS[kind]
    if not isinstance(width, int) or not low <= width <= high:
        raise BusinessRuleError(
            "invalid_width", f"Sıra hanesi {low} ile {high} arasında olmalıdır."
        )


def validate_year_format(value: str) -> None:
    if value not in YEAR_FORMATS:
        raise BusinessRuleError("invalid_year_format", "Yıl biçimi YYYY ya da YY olmalıdır.")


def validate_date_format(value: str) -> None:
    if value not in DATE_FORMATS:
        raise BusinessRuleError(
            "invalid_date_format", "Tarih biçimi YYYYMMDD, YYYYDDD ya da YYMMDD olmalıdır."
        )


def character_error(
    code: str, *, scanned: bool, allow_underscore: bool, max_length: int
) -> BusinessRuleError | None:
    """Ana veri kodunun karakter kuralı: A-Z, 0-9, `-` (ve izinliyse `_`); harf ya da rakamla
    başlar ve biter; barkodla okutulan kod harfle başlar. Uygunsa None."""
    if not code:
        return BusinessRuleError("code_required", "Kod girilmelidir.")
    if len(code) > max_length:
        return BusinessRuleError("code_too_long", f"Kod en fazla {max_length} karakter olabilir.")
    allowed = r"A-Z0-9\-_" if allow_underscore else r"A-Z0-9\-"
    if not re.fullmatch(rf"[{allowed}]+", code):
        extra = ", - ve _" if allow_underscore else " ve -"
        return BusinessRuleError(
            "invalid_characters",
            f"Kodda yalnızca A-Z, 0-9{extra} kullanılabilir (Türkçe harf ve boşluk olmaz).",
        )
    if not (code[0].isalnum() and code[-1].isalnum()):
        return BusinessRuleError(
            "invalid_characters", "Kod harf ya da rakamla başlamalı ve bitmelidir."
        )
    if scanned and not code[0].isalpha():
        return BusinessRuleError(
            "code_must_start_with_letter", "Barkodla okutulan kod harfle başlamalıdır."
        )
    return None


def digits(number: int) -> int:
    return len(str(number)) if number > 0 else 0
