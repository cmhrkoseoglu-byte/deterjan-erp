"""Stok okuma sorguları: bakiyeler, FEFO'ya göre kullanılabilir lotlar, lot soy ağacı (geri/ileri
izleme), SKT'si yaklaşan lotlar, minimum stok altındaki malzemeler."""

import calendar
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from django.db import connection
from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce, LPad
from django.utils import timezone

from apps.core.coding.selectors import find_by_code
from apps.core.exceptions import BusinessRuleError
from apps.core.labels import GS1_CHARSET_82, gs1_check_digit, gtin14, is_valid_gtin
from apps.inventory.models import (
    Lot,
    LotLink,
    LotNumberSequence,
    PalletLabel,
    StockBalance,
    StockReservation,
)
from apps.inventory.services import format_quantity
from apps.masterdata.models import Location, Material, MaterialUnitConversion, RetiredGtin
from apps.masterdata.selectors import gtin_owner, retired_gtin

ZERO = Value(Decimal(0), output_field=DecimalField(max_digits=18, decimal_places=4))
# Ağaç görünümünde en fazla derinlik (döngü zaten atlanır; çok derin zincirde yanıtı sınırlar).
MAX_TRACE_DEPTH = 25
# Minimum stok kontrolünde sayılmayan lotlar: kullanılamayacak stok.
UNUSABLE_STATUSES = (Lot.Status.REJECTED, Lot.Status.BLOCKED)
# Koli birimi: koli GTIN'i malzemenin bu birimdeki dönüşümünde tutulur (GS1).
CASE_UNIT = "KOLI"


def last_lot_number(prefix: str, day: date) -> int:
    """Bu önek ve gün için verilen son lot numarası (kodlama ekranı ve sıra hanesi denetimi)."""
    row = LotNumberSequence.objects.filter(prefix=prefix, day=day).first()
    return row.last_number if row is not None else 0


def _reserved_subquery() -> Coalesce:
    reserved = (
        StockReservation.objects.filter(
            lot=OuterRef("lot"),
            location=OuterRef("location"),
            status=StockReservation.Status.ACTIVE,
        )
        .values("lot")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return Coalesce(Subquery(reserved), ZERO)


def balances() -> QuerySet[StockBalance]:
    """Sıfırdan büyük bakiyeler (malzeme, lot, lokasyon ilişkileriyle).

    Açıklamalar: `reserved_quantity` (aktif rezervasyonlar) ve `available_quantity`
    (bakiye − rezerve), temel birimde."""
    return (
        StockBalance.objects.filter(quantity__gt=0)
        .select_related("material__base_unit", "lot", "location__warehouse")
        .annotate(reserved_quantity=_reserved_subquery())
        .annotate(available_quantity=F("quantity") - F("reserved_quantity"))
    )


def stock_by_material(material: Material) -> QuerySet[StockBalance]:
    """Malzemenin lot ve lokasyon bazında bakiyeleri."""
    return balances().filter(material=material).order_by("lot__expiry_date", "lot__lot_no")


def stock_by_location(location: Location) -> QuerySet[StockBalance]:
    """Lokasyondaki malzeme ve lot bakiyeleri."""
    return balances().filter(location=location).order_by("material__code", "lot__lot_no")


def available_lots(
    material: Material, fefo: bool = True, *, today: date | None = None
) -> QuerySet[StockBalance]:
    """Kullanılabilir stok: yalnızca serbest (RELEASED), SKT'si geçmemiş lotların rezerve
    edilmemiş miktarı pozitif bakiyeleri (`available_quantity` = bakiye − aktif rezervasyonlar).
    `fefo=True`: SKT'si en yakın önce (SKT'siz en sonda), sonra en eski lot."""
    today = today or timezone.localdate()
    queryset = (
        balances()
        .filter(material=material, lot__status=Lot.Status.RELEASED)
        .filter(Q(lot__expiry_date__isnull=True) | Q(lot__expiry_date__gte=today))
        .filter(available_quantity__gt=0)  # type: ignore[misc]
    )
    if fefo:
        return queryset.order_by(
            F("lot__expiry_date").asc(nulls_last=True),
            "lot__created_at",
            "lot__id",
            "location__code",
        )
    return queryset.order_by("lot__lot_no", "location__code")


def lots_with_stock() -> QuerySet[Lot]:
    """Lotlar, toplam stok (`total_quantity`) ve malzemenin koli GTIN'i (`material_case_gtin`)
    açıklamalarıyla."""
    total = (
        StockBalance.objects.filter(lot=OuterRef("pk"))
        .values("lot")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    case_gtin = (
        MaterialUnitConversion.objects.filter(material=OuterRef("material"), unit__code=CASE_UNIT)
        .exclude(gtin="")
        .values("gtin")[:1]
    )
    return Lot.objects.select_related("material__base_unit", "supplier").annotate(
        total_quantity=Coalesce(Subquery(total), ZERO),
        material_case_gtin=Coalesce(Subquery(case_gtin), Value("")),
    )


# --- soy ağacı -------------------------------------------------------------------------------

# UNION (ALL değil): aynı bağ ikinci kez işlenmez; ortak girdili ağaçlarda patlama ve döngü olmaz.
_TRACE_SQL = """
WITH RECURSIVE trace(link_id, node) AS (
    SELECT l.id, l.{next}
    FROM inventory_lotlink l
    WHERE l.{start} = %(lot_id)s
  UNION
    SELECT l.id, l.{next}
    FROM trace t
    JOIN inventory_lotlink l ON l.{start} = t.node
)
SELECT link_id FROM trace
"""


def _reachable_link_ids(lot_id: int, direction: Literal["backward", "forward"]) -> list[int]:
    # Geri izleme: çıktı lottan girdilere (child → parent); ileri izleme: girdiden çıktılara.
    start, nxt = ("child_lot_id", "parent_lot_id")
    if direction == "forward":
        start, nxt = nxt, start
    sql = _TRACE_SQL.format(start=start, next=nxt)
    with connection.cursor() as cursor:
        cursor.execute(sql, {"lot_id": lot_id})
        return [row[0] for row in cursor.fetchall()]


def _lot_node(lot: Lot) -> dict[str, Any]:
    material = lot.material
    return {
        "id": lot.pk,
        "lot_no": lot.lot_no,
        "status": lot.status,
        "status_display": lot.get_status_display(),
        "lot_source": lot.source,
        "lot_source_display": lot.get_source_display(),
        "material_id": material.pk,
        "material_code": material.code,
        "material_name": material.name,
        "material_type": material.material_type,
        "unit": material.base_unit.code,
        "expiry_date": lot.expiry_date,
    }


def lot_trace(lot: Lot, direction: Literal["backward", "forward"]) -> dict[str, Any]:
    """Lotun soy ağacı (özyinelemeli CTE ile tek sorguda bulunan bağlar).

    - `backward`: lotun üretiminde kullanılan girdi lotlar ve onların girdileri (geri izleme).
    - `forward`: lotun kullanıldığı çıktı lotlar ve onların çıktıları (ileri izleme).

    Dönüş: `{**lot, "quantity": None, "quantity_unit": None, "children": [{**lot, "quantity",
    "quantity_unit", "children": [...]}, ...]}`. `quantity`, girdi lottan kullanılan miktardır;
    birimi `quantity_unit` (girdi lotun temel birimi). İleri izlemede düğümün kendi birimi (`unit`,
    ör. mamulde ADET) ile aynı olmayabilir. Aynı girdi-çıktı çifti için birden çok bağ (ör. iki
    aşamada eklenen su) toplanır.
    """
    if direction not in ("backward", "forward"):
        raise ValueError("direction backward ya da forward olmalıdır.")
    link_ids = _reachable_link_ids(lot.pk, direction)
    links = LotLink.objects.filter(pk__in=link_ids).select_related(
        "parent_lot__material__base_unit", "child_lot__material__base_unit"
    )
    edges: dict[int, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    lots: dict[int, Lot] = {}
    for link in links:
        if direction == "backward":
            source_lot, target_lot = link.child_lot, link.parent_lot
        else:
            source_lot, target_lot = link.parent_lot, link.child_lot
        lots[source_lot.pk] = source_lot
        lots[target_lot.pk] = target_lot
        edges[source_lot.pk][target_lot.pk] += link.quantity

    def build(
        lot_id: int, quantity: Decimal | None, quantity_unit: str | None, seen: frozenset[int]
    ) -> dict[str, Any]:
        node = {
            **_lot_node(lots.get(lot_id, lot)),
            "quantity": quantity,
            "quantity_unit": quantity_unit,
            "children": [],
        }
        if len(seen) >= MAX_TRACE_DEPTH:
            return node
        for target_id, used in sorted(edges.get(lot_id, {}).items()):
            if target_id in seen:
                continue
            # Bağ miktarı girdi (parent) lotun temel birimindedir: geri izlemede hedef düğüm,
            # ileri izlemede kaynak düğüm girdidir.
            input_lot = lots[target_id] if direction == "backward" else lots[lot_id]
            unit = input_lot.material.base_unit.code
            node["children"].append(build(target_id, used, unit, seen | {target_id}))
        node["children"].sort(key=lambda child: (child["material_code"], child["lot_no"]))
        return node

    lot = Lot.objects.select_related("material__base_unit").get(pk=lot.pk)
    lots[lot.pk] = lot
    return build(lot.pk, None, None, frozenset({lot.pk}))


def lot_trace_backward(lot: Lot) -> dict[str, Any]:
    """Geri izleme: bu lotu oluşturan girdi lotlar ağacı."""
    return lot_trace(lot, "backward")


def lot_trace_forward(lot: Lot) -> dict[str, Any]:
    """İleri izleme: bu lotun kullanıldığı çıktı lotlar ağacı."""
    return lot_trace(lot, "forward")


# --- günlük kontroller -----------------------------------------------------------------------


def expiring_lots(days: int, *, today: date | None = None) -> QuerySet[Lot]:
    """Stokta olan (reddedilmemiş) ve SKT'si `days` gün içinde dolacak ya da dolmuş lotlar,
    SKT'ye göre sıralı."""
    today = today or timezone.localdate()
    return (
        lots_with_stock()
        .filter(total_quantity__gt=0, expiry_date__isnull=False)  # type: ignore[misc]
        .filter(expiry_date__lte=today + timedelta(days=days))
        .exclude(status=Lot.Status.REJECTED)
        .order_by("expiry_date", "lot_no")
    )


def below_min_stock() -> QuerySet[Material]:
    """Minimum stoku tanımlı aktif malzemelerden toplam stoku minimumun altında olanlar.

    Toplam stoka reddedilmiş ve bloke lotlar sayılmaz; karantinadaki (gelen) stok sayılır.
    Açıklama: `stock_quantity` (temel birimde).
    """
    stock = (
        StockBalance.objects.filter(material=OuterRef("pk"))
        .exclude(lot__status__in=UNUSABLE_STATUSES)
        .values("material")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return (
        Material.objects.filter(is_active=True, min_stock__isnull=False)
        .select_related("base_unit")
        .annotate(stock_quantity=Coalesce(Subquery(stock), ZERO))
        .filter(stock_quantity__lt=F("min_stock"))
        .order_by("code")
    )


# --- barkod okutma -----------------------------------------------------------------------------

# Barkod okuyucunun başa eklediği AIM simge kimlikleri (]C1 = GS1-128, ]Q3 = QR, ]d2 = DataMatrix).
_AIM_PREFIX = re.compile(r"^\][A-Za-z][0-9]")
# GS1 verisi taşıyan simgelerin AIM kimlikleri: GS1-128, GS1 DataBar, GS1 DataMatrix, GS1 QR,
# GS1 DotCode.
_GS1_AIM = frozenset({"]C1", "]e0", "]d2", "]Q3", "]J1"})
# GS (FNC1). Python'un strip()'i GS'yi de boşluk sayar: kenardan atılır ama okutulan metnin
# herhangi bir yerindeki GS veriyi GS1 yapar (`_scan_text`).
_GS = "\x1d"
# Ham (parantezsiz) GS1 verisi olarak denenecek başlangıçlar: SSCC ya da GTIN.
_RAW_GS1 = re.compile(r"^(00[0-9]{18}|0[12][0-9]{14})")
# Parantezli GS1 verisinde AI: parantez içinde 2-4 rakam, "(01)…(10)…".
_GS1_BRACKETED = re.compile(r"\(([0-9]{2,4})\)")
SCAN_PREFIXES = {"LOT:": "lot", "LOC:": "location", "MAT:": "material"}

# GS1 AI tablosu (GS1 General Specifications). "X" alanları GS1'in 82 karakterlik kümesindendir
# (`core.labels.GS1_CHARSET_82`, etiketlerle aynı küme). Okurken kümenin tamamı geçerlidir; ZPL'nin
# basamadığı "(", ")", ">" yalnızca basmayı sınırlar (`core.labels.is_gs1_printable`).
_DIGITS = frozenset("0123456789")
# Yazdırılabilir ASCII (0x20-0x7E): okurken (10) alanında eski lot numaraları için ("A" alanı).
_PRINTABLE_ASCII = frozenset(chr(code) for code in range(0x20, 0x7F))
# AI uzunluğu ilk iki hanesinden; listede olmayan önek tanınmaz. 71x (NHRN) 3 hanelidir.
_GS1_AI_LENGTH: dict[str, int] = {
    **dict.fromkeys(("00", "01", "02", "10", "11", "12", "13", "14", "15", "16", "17"), 2),
    **dict.fromkeys(("20", "21", "22", "30", "37"), 2),
    **dict.fromkeys((str(n) for n in range(90, 100)), 2),
    **dict.fromkeys(("23", "24", "25", "40", "41", "42", "71"), 3),
    **dict.fromkeys(("31", "32", "33", "34", "35", "36", "39", "43", "70", "72"), 4),
    **dict.fromkeys(("80", "81", "82"), 4),
}
# Önceden tanımlı uzunluklu alanlar (ilk iki hane → değer uzunluğu): arkalarına FNC1 gerekmez.
# Diğer alanlar GS (FNC1) ya da veri sonuyla biter.
_GS1_PREDEFINED: dict[str, int] = {
    "00": 18,
    "01": 14,
    "02": 14,
    "03": 14,
    "04": 16,
    "20": 2,
    "41": 13,
    **dict.fromkeys((str(n) for n in range(11, 20)), 6),
    **dict.fromkeys((str(n) for n in range(31, 37)), 6),
}
_Gs1Check = Literal["", "csum", "date", "datetime"]
_Gs1Kind = Literal["N", "X", "A"]


@dataclass(frozen=True)
class _Gs1Ai:
    """AI'nın veri biçimi: bileşenler (küme "N" rakam, "X" GS1 karakteri ya da "A" yazdırılabilir
    ASCII; en az, en çok uzunluk) ve ek denetim: "csum" son hane kontrol hanesi, "date" YYMMDD,
    "datetime" YYMMDDHHMM."""

    parts: tuple[tuple[_Gs1Kind, int, int], ...]
    check: _Gs1Check = ""


def _fixed(length: int, check: _Gs1Check = "") -> _Gs1Ai:
    """Sabit uzunluklu rakam alanı."""
    return _Gs1Ai((("N", length, length),), check)


def _upto(kind: _Gs1Kind, length: int) -> _Gs1Ai:
    """En çok `length` karakterlik değişken alan."""
    return _Gs1Ai(((kind, 1, length),))


# Ölçü alanları (31nn-36nn, N6): AI'nın son hanesi ondalık basamak sayısıdır (0-5); 310n net kg,
# 315n net litre, 330n brüt kg …
_GS1_MEASURE_STEMS = (*range(310, 317), *range(320, 338), *range(340, 358), *range(360, 370))
_GS1_AIS: dict[str, _Gs1Ai] = {
    "00": _fixed(18, "csum"),  # SSCC (palet)
    "01": _fixed(14, "csum"),  # GTIN
    "02": _fixed(14, "csum"),  # lojistik birimdeki ürünün GTIN'i
    # Lot (GS1'de X..20). Okurken en çok 64 yazdırılabilir ASCII: açılış stoku ve canlıya geçişte
    # alınan lot numaraları (en çok 64 karakter, boşluk olabilir) bu adımdan önce basılmış koli ve
    # palet etiketlerinin (10) alanındadır. GS alanı yine bitirir.
    "10": _upto("A", 64),
    # üretim, vade, ambalajlama, tavsiye edilen son tüketim, son satış, son kullanma tarihi
    **dict.fromkeys(("11", "12", "13", "15", "16", "17"), _fixed(6, "date")),
    "20": _fixed(2),  # varyant
    "21": _upto("X", 20),  # seri no
    "22": _upto("X", 20),  # tüketici ürün varyantı
    # ek ürün kimliği, müşteri parça no, ikincil seri no, kaynak varlık
    **dict.fromkeys(("240", "241", "250", "251"), _upto("X", 30)),
    "30": _upto("N", 8),  # değişken adet
    "37": _upto("N", 8),  # lojistik birimdeki ürün adedi (palette koli sayısı)
    **{f"{stem}{digits}": _fixed(6) for stem in _GS1_MEASURE_STEMS for digits in range(6)},
    **dict.fromkeys(("400", "401", "403"), _upto("X", 30)),  # sipariş no, sevkiyat no, rota
    **{f"41{n}": _fixed(13, "csum") for n in range(8)},  # GLN'ler (teslim, fatura, yer …)
    "420": _upto("X", 20),  # teslim posta kodu
    "421": _Gs1Ai((("N", 3, 3), ("X", 1, 9))),  # ülke kodu + teslim posta kodu
    **dict.fromkeys(("422", "424", "426"), _fixed(3)),  # menşe, işleme, tüm işlemlerin ülkesi
    "7003": _fixed(10, "datetime"),  # son kullanma tarihi ve saati
    "90": _upto("X", 30),  # taraflar arasında anlaşılmış bilgi
    **{str(n): _upto("X", 90) for n in range(91, 100)},  # firma içi bilgi
}
# Tarih alanları; gün 00: (15)(16)(17) ayın son günü, (11)(12)(13) yalnızca ay bilinir.
_GS1_DATE_AIS = ("11", "12", "13", "15", "16", "17")
_GS1_MONTH_END_AIS = frozenset({"15", "16", "17"})


@dataclass
class ScanResult:
    """Okutulan kodun çözümü. `lots` aynı lot numarasının birden çok malzemede olabileceği için
    listedir (okutma bileşeni beklenen malzemeye göre seçer)."""

    kind: Literal["lot", "location", "material", "pallet"]
    code: str
    lots: list[Lot] = field(default_factory=list)
    material: Material | None = None
    location: Location | None = None
    pallet: PalletLabel | None = None
    gs1: dict[str, str] = field(default_factory=dict)
    # Kayıt eski koduyla bulunduysa okutulan eski kod (etiket yenilenmeli; core.coding).
    former_code: str = ""
    # Koli GTIN'i okutulduysa koli birimi ("KOLI") ve 1 kolideki temel birim miktarı.
    unit: str = ""
    units_per_case: Decimal | None = None
    # Türkçe uyarılar (ör. barkoddaki SKT lot kaydındakinden farklı).
    warnings: list[str] = field(default_factory=list)
    # Çözülen GS1 tarihleri: AI → ISO "YYYY-MM-DD".
    gs1_dates: dict[str, str] = field(default_factory=dict)


def _gs1_year(two_digits: int, today: date) -> int:
    """İki haneli yılın yüzyılı (GS1 General Specifications 7.12): bu yıldan 50 yıldan çok ilerisi
    önceki yüzyıl, 49 yıldan çok gerisi sonraki yüzyıldır."""
    year = today.year - today.year % 100 + two_digits
    if year - today.year > 50:
        return year - 100
    if today.year - year > 49:
        return year + 100
    return year


def _gs1_date(ai: str, value: str, today: date) -> date | None:
    """YYMMDD (7003'te YYMMDDHHMM) değerinin tarihi; geçersizse ValueError. Gün 00: (15)(16)(17)
    ayın son günü, (11)(12)(13) yalnızca ay bilinir (None); 7003'te gün 00 olamaz."""
    year = _gs1_year(int(value[:2]), today)
    month, day = int(value[2:4]), int(value[4:6])
    if len(value) == 10 and (int(value[6:8]) > 23 or int(value[8:10]) > 59):
        raise ValueError(value)
    if day == 0 and ai in _GS1_DATE_AIS:
        if not 1 <= month <= 12:
            raise ValueError(value)
        if ai not in _GS1_MONTH_END_AIS:
            return None
        day = calendar.monthrange(year, month)[1]
    return date(year, month, day)


def gs1_dates(gs1: dict[str, str], *, today: date | None = None) -> dict[str, str]:
    """`parse_gs1` sonucundaki tarihler, AI → ISO "YYYY-MM-DD" ((11)(12)(13)(15)(16)(17)). Gün
    00 olan (11)(12)(13) yalnızca ay bildirdiği için listede yer almaz."""
    today = today or timezone.localdate()
    dates: dict[str, str] = {}
    for ai in _GS1_DATE_AIS:
        if ai in gs1 and (resolved := _gs1_date(ai, gs1[ai], today)) is not None:
            dates[ai] = resolved.isoformat()
    return dates


def gs1_decimal(ai: str, value: str) -> Decimal:
    """Ölçü alanının (31nn-36nn) değeri: AI'nın son hanesi ondalık basamak sayısıdır
    ((3102)001250 = 12,50 kg)."""
    if ai[:2] not in {"31", "32", "33", "34", "35", "36"} or ai not in _GS1_AIS:
        raise ValueError(f"Ölçü alanı değil: {ai}")
    return Decimal(value).scaleb(-int(ai[3]))


def _gs1_format(spec: _Gs1Ai) -> str:
    """Biçimin Türkçe tarifi: "14 hane", "en çok 20 karakter", "3 hane + en çok 9 karakter"."""
    words: list[str] = []
    for kind, low, high in spec.parts:
        unit = "hane" if kind == "N" else "karakter"
        words.append(f"{high} {unit}" if low == high else f"en çok {high} {unit}")
    return " + ".join(words)


def _unsupported_ai(ai: str) -> BusinessRuleError:
    """Tanınmayan AI hatası (sessizce kabul edilmez)."""
    return BusinessRuleError("gs1_unsupported_ai", f"Barkoddaki ({ai}) GS1 alanı tanınmıyor.")


def _check_gs1_value(ai: str, value: str, today: date) -> None:
    """Değeri AI'nın biçimine göre denetler: uzunluk, karakter kümesi, kontrol hanesi, tarih."""
    spec = _GS1_AIS[ai]
    if not value:
        raise BusinessRuleError("gs1_malformed", f"Barkoddaki ({ai}) alanı boş.")
    rest = value
    for index, (kind, low, high) in enumerate(spec.parts):
        last = index == len(spec.parts) - 1
        part, rest = (rest, "") if last else (rest[:high], rest[high:])
        if not low <= len(part) <= high or (kind == "N" and not set(part) <= _DIGITS):
            raise BusinessRuleError(
                "gs1_malformed", f"Barkoddaki ({ai}) alanı hatalı: {_gs1_format(spec)} olmalıdır."
            )
        if not set(part) <= (_PRINTABLE_ASCII if kind == "A" else GS1_CHARSET_82):
            raise BusinessRuleError(
                "gs1_malformed", f"Barkoddaki ({ai}) alanında GS1'de izin verilmeyen karakter var."
            )
    if spec.check == "csum" and gs1_check_digit(value[:-1]) != value[-1]:
        raise BusinessRuleError(
            "gs1_check_digit", f"Barkoddaki ({ai}) alanının kontrol hanesi hatalı: {value}."
        )
    if spec.check in ("date", "datetime"):
        try:
            _gs1_date(ai, value, today)
        except ValueError:
            what = "tarih ya da saat" if spec.check == "datetime" else "tarih"
            raise BusinessRuleError(
                "gs1_invalid_date", f"Barkoddaki ({ai}) alanında geçersiz {what}: {value}."
            ) from None


def _gs1_bracketed_pairs(data: str) -> list[tuple[str, str]]:
    """Parantezli veri "(01)…(10)…" → [(AI, değer)]. "(" ve ")" GS1 karakterleridir; yalnızca
    parantez içindeki 2-4 rakam AI sayılır."""
    pieces = _GS1_BRACKETED.split(data)
    if pieces[0].strip(_GS):
        raise BusinessRuleError(
            "gs1_malformed",
            "Barkoddaki GS1 verisi bozuk: bir alan tanımlayıcısıyla (AI) başlamıyor.",
        )
    pairs: list[tuple[str, str]] = []
    for ai, value in zip(pieces[1::2], pieces[2::2], strict=True):
        if ai not in _GS1_AIS:
            raise _unsupported_ai(ai)
        pairs.append((ai, value.strip(_GS)))
    return pairs


def _gs1_raw_pairs(data: str) -> list[tuple[str, str]]:
    """Ham veri (FNC1 = GS) → [(AI, değer)]. Önceden tanımlı uzunluklu alan kendi uzunluğunda,
    diğerleri GS ya da veri sonunda biter; sabit alanın arkasındaki GS de kabul edilir."""
    pairs: list[tuple[str, str]] = []
    position = 0
    while position < len(data):
        if data[position] == _GS:
            position += 1
            continue
        prefix = data[position : position + 2]
        length = _GS1_AI_LENGTH.get(prefix)
        if length is None:
            if len(prefix) == 2 and set(prefix) <= _DIGITS:
                raise _unsupported_ai(prefix)
            raise BusinessRuleError(
                "gs1_malformed",
                "Barkoddaki GS1 verisi bozuk: "
                f"“{data[position : position + 10]}” bir alan tanımlayıcısıyla (AI) başlamıyor.",
            )
        ai = data[position : position + length]
        if len(ai) < length or not set(ai) <= _DIGITS:
            raise BusinessRuleError(
                "gs1_malformed", f"Barkoddaki GS1 verisi bozuk: ({ai}) alan tanımlayıcısı eksik."
            )
        if ai not in _GS1_AIS:
            raise _unsupported_ai(ai)
        position += length
        size = _GS1_PREDEFINED.get(prefix)
        if size is not None:
            end = position + size
        else:
            end = data.find(_GS, position)
            end = len(data) if end == -1 else end
        pairs.append((ai, data[position:end]))
        position = end
    return pairs


def parse_gs1(code: str, *, today: date | None = None) -> dict[str, str]:
    """GS1 verisini AI → değer sözlüğüne çevirir: parantezli "(01)…(10)…" ya da ham veri (FNC1
    yerine GS, başta AIM öneki olabilir). İki biçim aynı sonucu verir.

    AI uzunluğu ilk iki hanesinden, değer biçimi `_GS1_AIS` tablosundan (GS1 General
    Specifications). Hatalar `BusinessRuleError`, mesaj AI'yı söyler: `gs1_unsupported_ai`
    (tanınmayan AI), `gs1_check_digit` ((00)(01)(02)(41x)), `gs1_invalid_date`, `gs1_malformed`
    (diğer biçim bozuklukları). Tarihlerin yüzyılı `today`'e göre (`gs1_dates`). Kenardaki
    boşluk karakterleri (NBSP, GS dahil) veri sayılmaz."""
    today = today or timezone.localdate()
    data = code.strip()
    aim = _AIM_PREFIX.match(data)
    if aim:
        data = data[aim.end() :]
    data = data.lstrip(_GS)
    pairs = _gs1_bracketed_pairs(data) if data.startswith("(") else _gs1_raw_pairs(data)
    if not pairs:
        raise BusinessRuleError("gs1_malformed", "Barkodda GS1 verisi yok.")
    result: dict[str, str] = {}
    for ai, value in pairs:
        _check_gs1_value(ai, value, today)
        if result.setdefault(ai, value) != value:
            raise BusinessRuleError(
                "gs1_malformed", f"Barkodda ({ai}) alanı iki kez, farklı değerlerle var."
            )
    return result


def _case_conversion(gtin: str) -> MaterialUnitConversion | None:
    """Bu GTIN'in kayıtlı olduğu koli dönüşümü (14 haneli normal biçimde)."""
    return (
        MaterialUnitConversion.objects.select_related("material__base_unit", "unit")
        .filter(unit__code=CASE_UNIT)
        .exclude(gtin="")
        .annotate(gtin_14=LPad("gtin", 14, Value("0")))
        .filter(gtin_14=gtin14(gtin))
        .first()
    )


def _gtin_owner(
    ai: str, gtin: str
) -> tuple[Material | None, MaterialUnitConversion | None, RetiredGtin | None]:
    """GTIN'in sahibi: (01) ve çıplak GTIN'de önce ürün, sonra koli GTIN'i; (02)'de önce koli
    GTIN'i, sonra ürün GTIN'i (eski palet etiketlerinde (02) ürün GTIN'idir). İkisi de değilse
    eski koli GTIN'i (arşiv; koli içi miktar değişince yerine yenisi verildi): dönüşümün
    malzemesi ve arşiv kaydı. Kayıtlı değilse (None, None, None)."""
    if ai == "02" and (conversion := _case_conversion(gtin)) is not None:
        return conversion.material, conversion, None
    material, conversion = gtin_owner(gtin)
    if material is not None:
        return material, conversion, None
    retired = retired_gtin(gtin)
    if retired is not None:
        return retired.conversion.material, None, retired
    return None, None, None


RETIRED_CASE_WARNING = (
    "Eski koli GTIN'i okutuldu: koli düzeni değişti; bu kolide 1 koli = {quantity} {unit}."
)


def _with_case(
    result: ScanResult,
    conversion: MaterialUnitConversion | None,
    retired: RetiredGtin | None = None,
) -> ScanResult:
    """Koli GTIN'i okutulduysa sonuca koli birimini ve 1 kolideki temel birim miktarını yazar.
    Dönüşüm pasifse malzeme yine bulunur (basılmış etiketler okunur) ama koli içi miktar
    önerilmez: birim boş kalır, uyarı eklenir. Eski koli GTIN'inde (arşiv) miktar o GTIN'in
    geçerli olduğu koli düzenindendir, dönüşüm artık pasif olsa da (geçmiş geçerlidir); uyarı
    koli düzeninin değiştiğini söyler."""
    if retired is not None:
        result.unit = retired.conversion.unit.code
        result.units_per_case = retired.factor_to_base
        result.warnings.append(
            RETIRED_CASE_WARNING.format(
                quantity=format_quantity(retired.factor_to_base),
                unit=retired.conversion.material.base_unit.code,
            )
        )
        return result
    if conversion is None:
        return result
    if not conversion.is_active:
        result.warnings.append("Bu koli GTIN'inin dönüşümü pasif; koli içi miktar önerilmez.")
    else:
        result.unit = conversion.unit.code
        result.units_per_case = conversion.factor_to_base
    return result


def case_gtin(material_id: int) -> str:
    """Malzemenin koli (KOLI) dönüşümündeki GTIN; yoksa "" (`LotSerializer`)."""
    gtin = (
        MaterialUnitConversion.objects.filter(material_id=material_id, unit__code=CASE_UNIT)
        .exclude(gtin="")
        .values_list("gtin", flat=True)
        .first()
    )
    return gtin or ""


def _lots_by_no(lot_no: str, material: Material | None = None) -> list[Lot]:
    queryset = Lot.objects.select_related("material__base_unit").filter(lot_no__iexact=lot_no)
    if material is not None:
        queryset = queryset.filter(material=material)
    return list(queryset.order_by("material__code"))


def _location_by_code(code: str, raw: str) -> ScanResult | None:
    """Lokasyon: önce güncel kod, sonra eski kod (yenilenmemiş raf etiketi)."""
    location, former = find_by_code(Location, code)
    if location is None:
        return None
    location = Location.objects.select_related("warehouse").get(pk=location.pk)
    return ScanResult("location", raw, location=location, former_code=code if former else "")


def _material_by_code(code: str, raw: str) -> ScanResult | None:
    """Malzeme: önce güncel kod, sonra eski kod (temel birimiyle; okutma yanıtı birimi söyler)."""
    material, former = find_by_code(Material, code)
    if material is None:
        return None
    material = Material.objects.select_related("base_unit").get(pk=material.pk)
    return ScanResult("material", raw, material=material, former_code=code if former else "")


def _expiry_warnings(lots: list[Lot], dates: dict[str, str]) -> list[str]:
    """Barkoddaki son kullanma tarihi (17) okutulan lotun kaydındakinden farklıysa uyarı."""
    if "17" not in dates or len(lots) != 1:
        return []
    printed, recorded = date.fromisoformat(dates["17"]), lots[0].expiry_date
    if printed == recorded:
        return []
    if recorded is None:
        return [f"Barkoddaki SKT ({printed:%d.%m.%Y}) lot kaydında yok."]
    return [
        f"Barkoddaki SKT ({printed:%d.%m.%Y}) lot kaydındaki SKT'den ({recorded:%d.%m.%Y}) farklı."
    ]


def _decode_gs1(raw: str, gs1: dict[str, str], today: date) -> ScanResult:
    """GS1 verisinin çözümü: (00) SSCC → palet ve lotu; (01)/(02) GTIN → malzeme (koli GTIN'inde,
    eski koli GTIN'inde de, koli birimiyle), (10) varsa o malzemedeki lot; GTIN'siz (10) → o
    numaralı lotlar."""
    gtin_ai = next((ai for ai in ("01", "02") if ai in gs1), "")
    if "00" in gs1:
        pallet = (
            PalletLabel.objects.select_related("lot__material__base_unit")
            .filter(sscc=gs1["00"])
            .first()
        )
        if pallet is None:
            raise BusinessRuleError("scan_not_found", f"Bu SSCC ile palet kaydı yok: {gs1['00']}.")
        result = ScanResult(
            "pallet", raw, lots=[pallet.lot], material=pallet.lot.material, pallet=pallet
        )
    elif gtin_ai:
        material, conversion, retired = _gtin_owner(gtin_ai, gs1[gtin_ai])
        if material is None:
            raise BusinessRuleError(
                "scan_not_found", f"Bu GTIN ile kayıtlı malzeme yok: {gs1[gtin_ai]}."
            )
        result = _with_case(ScanResult("material", raw, material=material), conversion, retired)
        if "10" in gs1:
            result.kind = "lot"
            result.lots = _lots_by_no(gs1["10"], material)
            if not result.lots:
                raise BusinessRuleError(
                    "scan_not_found", f"{material.code} malzemesinde {gs1['10']} lotu bulunamadı."
                )
    elif "10" in gs1:
        lots = _lots_by_no(gs1["10"])
        if not lots:
            raise BusinessRuleError("scan_not_found", f"Okutulan kod bulunamadı: {gs1['10']}.")
        result = ScanResult("lot", raw, lots=lots, material=lots[0].material)
    else:
        raise BusinessRuleError(
            "scan_not_found", "GS1 barkodunda ürün (01, 02), lot (10) ya da SSCC (00) yok."
        )
    result.gs1, result.gs1_dates = gs1, gs1_dates(gs1, today=today)
    result.warnings += _expiry_warnings(result.lots, result.gs1_dates)
    return result


def _scan_text(raw: str) -> tuple[str, bool]:
    """Okutulan metin (kenar boşlukları, AIM öneki ve baştaki GS'ler atılmış) ve GS1 olduğu belli
    mi: GS1 AIM kimliği, herhangi bir yerde GS (baştaki ve sondaki dahil) ya da parantezli AI.
    Kenardan her boşluk karakteri atılır (NBSP, dikey sekme …; GS1 verisinde de, kenardaki boşluk
    veri sayılmaz), GS de: kenardaki GS (AIM göndermeyen okuyucunun FNC1'i) atılsa da işarettir.
    AIM yalnızca bir kez atılır."""
    code = raw.strip()
    aim = _AIM_PREFIX.match(code)
    if aim:
        code = code[aim.end() :]
    marked = (aim is not None and aim.group() in _GS1_AIM) or _GS in raw
    code = code.lstrip(_GS)
    if marked or _GS1_BRACKETED.match(code):
        return code, True
    return code.strip(), False


def decode_scan(raw: str, *, today: date | None = None) -> ScanResult:
    """Okutulan barkodu çözer: `LOT:` / `LOC:` / `MAT:` önekleri, GS1 ((00) SSCC, (01)/(02) GTIN,
    koli GTIN'i koli birimiyle, eski koli GTIN'i arşivdeki koli içi miktarıyla ve uyarıyla; (10)
    lot) ve öneksiz değerler (Faz 1'de basılmış lot no, lokasyon ya da malzeme kodu, eski kodlar,
    GTIN).

    GS1 olduğu belli veri (parantezli, GS1 AIM kimlikli ya da GS ayırıcılı) `parse_gs1`'in
    `gs1_*` hatalarını verir. Yalnızca SSCC/GTIN ile başladığı için GS1 sayılan ham veri
    çözülemezse önce diğer yorumlar denenir (o numarada lot, lokasyon ya da malzeme olabilir),
    hiçbiri yoksa GS1 hatası döner. Bulunamazsa `scan_not_found`.
    """
    today = today or timezone.localdate()
    code, marked = _scan_text(raw)
    upper = code.upper()

    for prefix, kind in SCAN_PREFIXES.items():
        if not upper.startswith(prefix):
            continue
        value = code[len(prefix) :].strip()
        if kind == "lot" and (lots := _lots_by_no(value)):
            return ScanResult("lot", raw, lots=lots, material=lots[0].material)
        if kind == "location" and (found := _location_by_code(value.upper(), raw)):
            return found
        if kind == "material" and (found := _material_by_code(value.upper(), raw)):
            return found
        raise BusinessRuleError("scan_not_found", f"Okutulan kod bulunamadı: {value}.")

    gs1_error: BusinessRuleError | None = None
    if marked or _RAW_GS1.match(code):
        try:
            return _decode_gs1(raw, parse_gs1(code, today=today), today)
        except BusinessRuleError as error:
            if marked:
                raise
            gs1_error = error

    if lots := _lots_by_no(code):
        return ScanResult("lot", raw, lots=lots, material=lots[0].material)
    if found := _location_by_code(upper, raw):
        return found
    if found := _material_by_code(upper, raw):
        return found
    if gs1_error is not None:
        raise gs1_error
    if code.isascii() and is_valid_gtin(code):
        # Çıplak GTIN (EAN-13 ürün, ITF-14 koli barkodu) (01) gibi: önce ürün, sonra koli, arşiv.
        material, conversion, retired = _gtin_owner("01", code)
        if material is not None:
            return _with_case(ScanResult("material", raw, material=material), conversion, retired)
    raise BusinessRuleError("scan_not_found", f"Okutulan kod tanınmadı: {code}.")


def scan_label(code: str) -> str:
    """Okutulan kodun hata mesajlarındaki hâli (`lot_not_found`): GS1 verisinde (10) lot no, yoksa
    (00) SSCC, yoksa (01)/(02) GTIN; diğer kodlarda AIM öneki atılmış metin, GS gibi kontrol
    karakterleri boşluk. Hata vermez: çözülemeyen GS1 verisinde de bu metin döner."""
    text, marked = _scan_text(code)
    if marked or _RAW_GS1.match(text):
        try:
            gs1 = parse_gs1(text)
        except (BusinessRuleError, ValueError):
            gs1 = {}
        for ai in ("10", "00", "01", "02"):
            if ai in gs1:
                return gs1[ai]
    return "".join(char if char.isprintable() else " " for char in text).strip()


AMBIGUOUS_LOT_MESSAGE = "{lot_no} numarası birden çok malzemede var; lotu listeden seçin."


def resolve_lot(
    code: str,
    *,
    materials: Iterable[int] | None = None,
    restrict: bool = True,
    unique: bool = False,
    ambiguous_message: str = AMBIGUOUS_LOT_MESSAGE,
) -> Lot | None:
    """Üretim, dolum ve sevkiyatta okutulan lotu bulur (ortak çözüm, `decode_scan` ile): lot
    etiketi (`LOT:`), GS1 barkodu ((01)/(02) GTIN + (10) lot, (00) SSCC → paletin lotu; AIM
    öneki, ham veri) ya da düz lot no; büyük/küçük harf fark etmez.

    `materials` verilirse bu malzemelerdeki lot seçilir (birden çoksa en yenisi; `unique` ise
    `ambiguous_lot`, mesajı `ambiguous_message`, {lot_no} yerine lot no). Bunlarda yoksa
    `restrict` iken None, değilse başka malzemedeki lot döner (servis "yanlış malzeme" hatasını
    versin). Lot bulunamazsa None: çağıran kendi `lot_not_found` hatasını verir (kodu mesajda
    `scan_label` ile gösterir). GS1 biçim hataları (`gs1_*`) olduğu gibi yükselir; durum
    kuralları (serbest lot vb.) servislerdedir."""
    try:
        result = decode_scan(code)
    except BusinessRuleError as error:
        if error.code == "scan_not_found":
            return None
        raise
    if result.kind not in ("lot", "pallet"):
        return None
    lots = sorted(result.lots, key=lambda lot: (lot.created_at, lot.pk), reverse=True)
    wanted = None if materials is None else set(materials)
    preferred = [lot for lot in lots if wanted is None or lot.material_id in wanted]
    if unique and len(preferred) > 1:
        raise BusinessRuleError(
            "ambiguous_lot", ambiguous_message.format(lot_no=preferred[0].lot_no)
        )
    if preferred:
        return preferred[0]
    return None if restrict or not lots else lots[0]
