"""Bordro hesap motoru (`personnel.payroll`; docs/DECISIONS.md "Personel bordrosu"): yayımlanmış
2026 örnekleri (ÇSGB asgari ücret maliyeti, GİB ve meslek kuruluşlarının brütten nete örnekleri),
kural sabitleri ve modül sınırları. Veritabanı gerekmez."""

import ast
import calendar
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.personnel import payroll
from apps.personnel.models import AttendanceStatus

D = Decimal
P = payroll.LEGAL_DEFAULTS[2026]
PERSONNEL = Path(payroll.__file__).resolve().parent


def month(
    year: int,
    number: int,
    wage: str | None,
    *,
    start: date | None = None,
    statuses: dict[int, str] | None = None,
    hours: dict[int, Any] | None = None,
    half: tuple[int, ...] = (),
    **extra: Any,
) -> payroll.MonthInput:
    """Ayın işte olunan günleri (varsayılan hepsi Ç), sabit ücretle."""
    last = calendar.monthrange(year, number)[1]
    days = []
    for day_number in range(1, last + 1):
        day = date(year, number, day_number)
        if start and day < start:
            continue
        days.append(
            payroll.Day(
                date=day,
                status=(statuses or {}).get(day_number, payroll.WORKED),
                overtime_hours=D((hours or {}).get(day_number, 0)),
                wage=D(wage) if wage is not None else None,
                half_holiday_worked=day_number in half,
            )
        )
    return payroll.MonthInput(days=tuple(days), days_in_month=last, **extra)


def compute(inp: payroll.MonthInput, params: payroll.Parameters = P) -> payroll.Result:
    return payroll.compute(inp, params)


def test_minimum_wage_full_month_net_and_employer_cost() -> None:
    """Asgari ücret 2026: net 28.075,50 (gelir ve damga vergisi tamamen istisna); işverene maliyet
    imalatta (5 puan) 39.223,13, 2 puanla 40.214,03, teşviksiz 40.874,63 (ÇSGB tablosu)."""
    line = compute(month(2026, 1, "33030"))
    assert line.net_pay == D("28075.50")
    assert (line.income_tax, line.income_tax_exemption) == (D("0.00"), D("4211.33"))
    assert (line.stamp_tax, line.stamp_tax_exemption) == (D("0.00"), D("250.70"))
    assert line.employer_cost == D("39223.13")
    assert (line.employer_sgk_gross, line.incentive, line.employer_unemployment) == (
        D("7184.03"),
        D("1651.50"),
        D("660.60"),
    )
    for points, cost in (("2", "40214.03"), ("0", "40874.63")):
        params = replace(P, incentive_points=D(points))
        assert compute(month(2026, 1, "33030"), params).employer_cost == D(cost)
    assert P.employer_rate == D("18.75") and P.exemption_base == D("28075.50")
    assert (P.daily_floor, P.daily_ceiling) == (D("1101.00"), D("9909.00"))


def test_gross_to_net_january_and_full_year() -> None:
    """50.000 TL Ocak: GV matrahı 42.500, GV 6.375 − 4.211,33, DV 128,80, net 40.207,53; yıl boyu
    kümülatif matrahla net toplamı 466.135,63."""
    line = compute(month(2026, 1, "50000"))
    assert (line.employee_sgk, line.employee_unemployment) == (D("7000.00"), D("500.00"))
    assert (line.tax_base, line.income_tax_computed, line.income_tax) == (
        D("42500.00"),
        D("6375.00"),
        D("2163.67"),
    )
    assert line.stamp_tax == D("128.80") and line.net_pay == D("40207.53")
    assert line.employer_cost == D("59375.00")
    carry, annual = payroll.Carry(), D(0)
    for number in range(1, 13):
        result = compute(replace(month(2026, number, "50000"), carry=carry))
        annual += result.net_pay
        carry = payroll.carry_after(result)
    assert annual == D("466135.63")
    assert carry.tax_base == D("510000.00") and carry.exemption_base == D("336906.00")


def test_sgk_ceiling() -> None:
    """400.000 TL: SGK matrahı tavanda (297.270); net 295.253,63; toplam prim 100.328,63."""
    line = compute(month(2026, 1, "400000"))
    assert line.ceiling_applied and line.sgk_base == D("297270.00")
    assert line.net_pay == D("295253.63")
    premiums = (
        line.employee_sgk
        + line.employee_unemployment
        + line.employer_sgk
        + line.employer_unemployment
    )
    assert premiums == D("100328.63")


def test_mid_month_hire_and_following_month() -> None:
    """16.10.2026 işe giriş, 40.000: Ekim brüt 21.333,33, SGK günü 16; istisna hesaplanan vergiyle
    sınırlı (2.720,00), net 18.133,33. Kasım (kümülatif devirle) net 33.058,43."""
    october = compute(month(2026, 10, "40000", start=date(2026, 10, 16)))
    assert (october.gross_total, october.sgk_days) == (D("21333.33"), 16)
    assert october.income_tax_exemption == D("2720.00") and october.income_tax == D("0.00")
    assert october.net_pay == D("18133.33")
    # Kıst ayda da istisna sayacına bütün ay eklenir (GVGT 319 m.6/2, Örnek 7).
    assert october.exemption_base_added == D("28075.50")
    november = compute(replace(month(2026, 11, "40000"), carry=payroll.carry_after(october)))
    assert november.net_pay == D("33058.43")


def test_partial_month_eksik_days_and_daily_limits() -> None:
    """Ay içinde giriş + eksik gün: SGK günü 16 − 2 = 14; alt ve üst sınır gün başına (5510 m.82);
    ay içinde çıkışta alt sınır farkı."""
    unpaid = {20: payroll.UNPAID_LEAVE, 21: payroll.UNPAID_LEAVE}
    line = compute(month(2026, 10, "40000", start=date(2026, 10, 16), statuses=unpaid))
    assert (line.sgk_days, line.paid_days, line.gross_total) == (14, 14, D("18666.67"))
    mw = compute(month(2026, 10, "33030", start=date(2026, 10, 16), statuses=unpaid))
    assert (mw.sgk_base, mw.floor_applied, mw.employer_cost) == (
        D("15414.00"),
        False,
        D("18304.13"),
    )
    high = compute(month(2026, 10, "400000", start=date(2026, 10, 16)))
    assert high.ceiling_applied and high.sgk_base == D("158544.00")  # 16 × 9.909
    assert (high.employee_sgk, high.net_pay, high.employer_cost) == (
        D("22196.16"),
        D("163961.80"),
        D("243060.33"),
    )
    september = month(2026, 9, "30000")
    leaver = compute(replace(september, days=september.days[:20]))  # 1–20 Eylül
    assert (leaver.sgk_days, leaver.sgk_base, leaver.floor_gap, leaver.employer_cost) == (
        20,
        D("22020.00"),
        D("303.00"),
        D("24431.75"),
    )


def test_bes_is_three_percent_of_the_sgk_base() -> None:
    """BES kesintisi brütün değil SGK matrahının %3'üdür: alt sınırda matrah, tavanda tavan."""
    floor = compute(month(2026, 10, "33030", statuses={5: payroll.UNPAID_LEAVE}, bes=True))
    assert (floor.gross_total, floor.bes_deduction, floor.payable) == (
        D("31929.00"),
        D("990.90"),  # brütten 957,87 değil
        D("26148.75"),
    )
    assert compute(month(2026, 1, "400000", bes=True)).bes_deduction == D("8918.10")  # 12.000 değil


def test_result_round_trips_through_json() -> None:
    """Onaylı ayın saklanan satırı: JSON'a yazılıp okunan satır aynıdır (tutarlar Decimal kalır,
    kalemler, boş ücret ve işaretler korunur)."""
    extras = (payroll.Item("PREMIUM", "Prim", D("5000")),)
    deductions = (payroll.Item("ADVANCE", "Avans", D("1000.00")),)
    full = month(2026, 10, "50000", hours={5: "2.5"}, bes=True)
    for result in (
        compute(replace(full, extras=extras, deductions=deductions)),
        compute(month(2026, 10, None)),  # ücret eksik
    ):
        stored = json.loads(json.dumps(payroll.result_to_dict(result)))
        assert payroll.result_from_dict(stored) == result
    assert payroll.result_to_dict(result)["monthly_wage"] is None


# Motorun 2026.2 sürümünün saklanan satırı: Ekim 2026, tam ay 50.000 TL + 5.000 TL prim, kümülatif
# sıfırdan (onaylı bordro yasal kayıttır; motor değişse de eski satırlar okunmalı).
STORED_2026_2 = {
    "employed_days": 31,
    "worked_days": 31,
    "paid_days": 30,
    "unpaid_days": 0,
    "sick_days": 0,
    "unpaid_leave_days": 0,
    "absent_days": 0,
    "sgk_days": 30,
    "monthly_wage": "50000",
    "missing_wage": False,
    "salary": "50000.00",
    "overtime_worked_hours": "0",
    "overtime_worked_pay": "0.00",
    "overtime_rest_hours": "0",
    "overtime_rest_pay": "0.00",
    "holiday_days": 0,
    "holiday_half_days": 0,
    "holiday_hours": "0",
    "holiday_extra_hours": "0",
    "holiday_pay": "0.00",
    "extras": [{"kind": "PREMIUM", "label": "Prim", "amount": "5000"}],
    "extras_total": "5000",
    "gross_total": "55000.00",
    "meal_exemption": "0.00",
    "sgk_gross": "55000.00",
    "sgk_base": "55000.00",
    "floor_applied": False,
    "ceiling_applied": False,
    "employee_sgk": "7700.00",
    "employee_unemployment": "550.00",
    "tax_base": "46750.00",
    "cumulative_tax_base_before": "0",
    "cumulative_tax_base_after": "46750.00",
    "income_tax_computed": "7012.50",
    "income_tax_exemption": "4211.33",
    "income_tax": "2801.17",
    "exemption_base_before": "0",
    "exemption_base_added": "28075.50",
    "stamp_tax_computed": "417.45",
    "stamp_tax_exemption": "250.70",
    "stamp_tax": "166.75",
    "net_pay": "43782.08",
    "bes_deduction": "0",
    "deductions": [],
    "deductions_total": "0",
    "payable": "43782.08",
    "employer_sgk_gross": "11962.50",
    "incentive": "2750.00",
    "employer_sgk": "9212.50",
    "employer_unemployment": "1100.00",
    "floor_gap": "0",
    "employer_cost": "65312.50",
}


def test_stored_line_of_an_older_engine_is_read() -> None:
    """Saklanan satır sürümden bağımsız okunur: bilinmeyen anahtar atlanır, eksik alan boş değerini
    alır (gün 0, işaret hayır, kalem yok, tutar 0, aylık ücret boş)."""
    line = payroll.result_from_dict(STORED_2026_2)
    extras = (payroll.Item("PREMIUM", "Prim", D("5000")),)
    assert line == compute(replace(month(2026, 10, "50000"), extras=extras))
    assert (line.gross_total, line.payable, line.employer_cost) == (
        D("55000.00"),
        D("43782.08"),
        D("65312.50"),
    )
    assert line.extras == (payroll.Item("PREMIUM", "Prim", D("5000")),)
    trimmed = {key: value for key, value in STORED_2026_2.items() if key != "meal_exemption"}
    trimmed["future_field"] = "1"
    older = payroll.result_from_dict(trimmed)
    assert older.meal_exemption == D(0)
    assert older.payable == line.payable
    empty = payroll.result_from_dict({})
    assert (empty.sgk_days, empty.missing_wage, empty.extras, empty.monthly_wage) == (
        0,
        False,
        (),
        None,
    )
    assert empty.gross_total == D(0)


def test_parameters_round_trip_through_json() -> None:
    """Onayda saklanan parametreler aynı değerlerle okunur; eski kayıtta olmayan değer 0'dır."""
    params = payroll.LEGAL_DEFAULTS[2026]
    stored = json.loads(json.dumps(payroll.parameters_to_dict(params)))
    assert payroll.parameters_from_dict(stored) == params
    del stored["meal_exemption_daily"]
    assert payroll.parameters_from_dict(stored).meal_exemption_daily == D(0)


def test_floor_gap_is_borne_by_the_employer() -> None:
    """Asgari ücret, Ekim (31 gün), 1 gün ücretsiz izin, Ocak–Eylül asgari ücret devri: brüt
    31.929,00, SGK günü 30, matrah alt sınırda 33.030,00; işçi payları ücretten, farkın işçi payını
    (165,15) işveren öder (5510 m.82). Net 27.139,65, maliyet 38.287,28."""
    carry = payroll.Carry(tax_base=D("252679.50"), exemption_base=D("252679.50"))
    line = compute(
        replace(
            month(2026, 10, "33030", statuses={5: payroll.UNPAID_LEAVE}),
            carry=carry,
        )
    )
    assert (line.gross_total, line.sgk_days, line.sgk_base) == (
        D("31929.00"),
        30,
        D("33030.00"),
    )
    assert line.floor_applied and not line.ceiling_applied
    assert (line.employee_sgk, line.employee_unemployment) == (D("4470.06"), D("319.29"))
    assert line.floor_gap == D("165.15")
    assert line.net_pay == D("27139.65") and line.employer_cost == D("38287.28")


def test_opening_balance_continues_the_series() -> None:
    """Eylül sonu devri (kümülatif matrah 382.500, 9 ay asgari ücret matrahı 252.679,50) ile Ekim
    50.000: dilim 400.000'i geçer; net 37.736,30 (kesintisiz yıl hesabıyla aynı)."""
    carry = payroll.Carry(tax_base=D("382500.00"), exemption_base=D("252679.50"))
    line = compute(replace(month(2026, 10, "50000"), carry=carry))
    assert line.income_tax_computed == D("10250.00")
    assert line.income_tax_exemption == D("5615.10")
    assert line.net_pay == D("37736.30")


def test_minimum_wage_exemption_through_the_year() -> None:
    """Asgari ücret istisnası: Ocak–Haziran 4.211,33, Temmuz 4.537,75 (dilim geçişi), Ağustos–
    Aralık 5.615,10; yıllık 57.881,23."""
    carry, exemptions = payroll.Carry(), []
    for number in range(1, 13):
        result = compute(replace(month(2026, number, "33030"), carry=carry))
        exemptions.append(result.income_tax_exemption)
        carry = payroll.carry_after(result)
    assert exemptions[:6] == [D("4211.33")] * 6
    assert exemptions[6] == D("4537.75")
    assert exemptions[7:] == [D("5615.10")] * 5
    assert sum(exemptions, D(0)) == D("57881.23")


def test_public_holiday_work_pays_a_day() -> None:
    """Resmi tatilde çalışana bir günlük ilave ücret (kısa çalışsa da); 7,5 saati aşan saatler
    1,5 kat. Yarım gün tatilde öğleden sonra çalışana yarım gün. Çalışılmayan tatil ödenmez."""
    holiday = {29: payroll.PUBLIC_HOLIDAY}
    assert compute(month(2026, 10, "50000", statuses=holiday, hours={29: 4})).holiday_pay == D(
        "1666.67"
    )
    line = compute(month(2026, 10, "50000", statuses=holiday, hours={29: 10}))
    assert line.holiday_pay == D("2500.00")
    assert (line.holiday_days, line.holiday_hours, line.holiday_extra_hours) == (
        1,
        D(10),
        D("2.5"),
    )
    half = compute(month(2026, 10, "33030", half=(28,)))
    assert (half.holiday_pay, half.holiday_half_days) == (D("550.50"), 1)
    assert compute(month(2026, 10, "50000", statuses=holiday)).holiday_pay == D("0.00")


def test_overtime_and_february_rules() -> None:
    """22.500 (saat 100): iş günü 2 sa → 300, hafta tatili 4 sa → 600. Şubat, 5 gün ücretsiz: SGK
    günü 28 − 5 = 23, ücret 40.000 × 25/30."""
    line = compute(month(2026, 9, "22500", statuses={6: payroll.WEEKLY_REST}, hours={1: 2, 6: 4}))
    assert (line.overtime_worked_pay, line.overtime_rest_pay) == (D("300.00"), D("600.00"))
    unpaid = dict.fromkeys(range(2, 7), payroll.UNPAID_LEAVE)
    february = compute(month(2026, 2, "40000", statuses=unpaid))
    assert (february.sgk_days, february.salary, february.paid_days) == (23, D("33333.33"), 25)
    assert compute(month(2026, 2, "40000")).sgk_days == 30


def test_rounding_pins() -> None:
    """Kalem kalem yarım yukarı yuvarlama: damga vergisi 33.030,66'da 0,01; işveren SGK'sı iki
    yuvarlanmış kalemin farkı (33.030,05'te 5.532,54; net oranla 5.532,53 çıkardı)."""
    assert compute(month(2026, 1, "33030.66")).stamp_tax == D("0.01")
    assert compute(month(2026, 1, "33030.05")).employer_sgk == D("5532.54")
    assert payroll.money(D("4211.325")) == D("4211.33")


def test_bes_and_net_deductions() -> None:
    """BES SGK matrahının %3'ü, avans gibi kesintiler netten düşer; ek ödeme brüte girer."""
    inp = month(
        2026,
        1,
        "50000",
        bes=True,
        deductions=(payroll.Item("ADVANCE", "Avans", D("1000")),),
    )
    line = compute(inp)
    assert (line.bes_deduction, line.deductions_total) == (D("1500.00"), D("1000.00"))
    assert line.payable == D("37707.53")
    bonus = compute(month(2026, 1, "50000", extras=(payroll.Item("BONUS", "Prim", D("5000")),)))
    assert (bonus.extras_total, bonus.gross_total) == (D("5000"), D("55000.00"))


def test_cash_meal_sgk_exemption() -> None:
    """Nakit yemek: fiilen çalışılan gün × günlük sınıra kadarki kısmı SGK matrahına girmez; gelir
    ve damga vergisine tabi kalır. Sınır 0'sa (varsayılan) istisna yok. Ekim 2026: 4 hafta tatili,
    biri 4 saat fazla mesaili → fiilen 28 gün; yemek 5.000, sınır 158 → istisna 4.424."""
    meal = (payroll.Item(payroll.MEAL, "Yemek", D("5000")),)
    rest = dict.fromkeys((4, 11, 18, 25), payroll.WEEKLY_REST)
    inp = month(2026, 10, "33030", statuses=rest, hours={11: 4}, extras=meal)
    plain = compute(inp)
    assert plain.meal_exemption == D(0) and plain.sgk_gross == plain.gross_total
    line = compute(inp, replace(P, meal_exemption_daily=D("158.00")))
    assert (line.worked_days, line.meal_exemption) == (28, D("4424.00"))
    assert line.gross_total == plain.gross_total == D("38910.80")
    assert (line.sgk_gross, line.sgk_base) == (D("34486.80"), D("34486.80"))
    assert (line.employee_sgk, line.employee_unemployment) == (D("4828.15"), D("344.87"))
    # GV matrahı brütün tamamından (yemek dahil) SGK ve işsizlik payı düşülerek; damga brütten.
    assert (line.tax_base, line.income_tax, line.stamp_tax) == (
        D("33737.78"),
        D("849.34"),
        D("44.64"),
    )
    assert (line.net_pay, line.employer_cost) == (D("32843.80"), D("45377.08"))
    # İstisna yemek tutarını aşamaz; matrah alt sınırın altına inerse alt sınır uygulanır.
    small = compute(
        month(2026, 10, "33030", extras=(payroll.Item(payroll.MEAL, "Yemek", D("2000")),)),
        replace(P, meal_exemption_daily=D("158.00")),
    )
    assert (small.meal_exemption, small.sgk_gross, small.floor_applied) == (
        D("2000.00"),
        D("33030.00"),
        False,
    )
    # Yemek dışındaki ek ödeme istisnadan yararlanmaz.
    bonus = compute(
        month(2026, 10, "33030", extras=(payroll.Item("PREMIUM", "Prim", D("5000")),)),
        replace(P, meal_exemption_daily=D("158.00")),
    )
    assert bonus.meal_exemption == D(0) and bonus.sgk_gross == bonus.gross_total


def test_missing_wage_skips_the_floor() -> None:
    """Ücreti girilmemiş gün varsa alt sınır uygulanmaz (ücretsiz görünen kişiye prim yazılmaz)."""
    line = compute(month(2026, 10, None))
    assert line.missing_wage and line.gross_total == D(0)
    assert (line.sgk_base, line.employer_cost, line.floor_gap) == (D(0), D(0), D(0))
    assert line.exemption_base_added == D(0)  # ücret yokken istisna sayacı ilerlemez


def test_whole_month_unpaid_has_no_sgk_days() -> None:
    unpaid = dict.fromkeys(range(1, 32), payroll.UNPAID_LEAVE)
    line = compute(month(2026, 8, "45000", statuses=unpaid))
    assert (line.sgk_days, line.sgk_base, line.employer_cost) == (0, D(0), D("0.00"))


def test_engine_constants_match_attendance_statuses() -> None:
    assert payroll.WORKED == AttendanceStatus.WORKED
    assert payroll.WEEKLY_REST == AttendanceStatus.WEEKLY_REST
    assert payroll.PUBLIC_HOLIDAY == AttendanceStatus.PUBLIC_HOLIDAY
    unpaid = {
        AttendanceStatus.UNPAID_LEAVE,
        AttendanceStatus.SICK_LEAVE,
        AttendanceStatus.ABSENT,
    }
    assert unpaid == payroll.UNPAID_STATUSES


def test_legal_defaults_and_nearest_year() -> None:
    assert payroll.legal_parameters(2026) is P and payroll.legal_parameters(2031) is None
    assert payroll.nearest_legal_year(2031) == 2026 and payroll.nearest_legal_year(2025) == 2026
    assert payroll.LEGAL_SOURCES[2026]
    assert P.tariff(D("190000")) == D("28500") and P.tariff(D("400000")) == D("70500")
    assert P.tariff(D("1500000")) == D("367500") and P.tariff(D("5300000")) == D("1697500")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_engine_uses_only_the_standard_library() -> None:
    """Motor Django'suz ve uygulama modülsüz kalır (saf hesap; testler veritabanı istemez)."""
    allowed = {"collections.abc", "dataclasses", "datetime", "decimal", "typing"}
    assert _imports(PERSONNEL / "payroll.py") <= allowed


@pytest.mark.parametrize(
    "path",
    sorted(path for path in PERSONNEL.rglob("*.py") if "migrations" not in path.parts),
    ids=lambda path: str(path.relative_to(PERSONNEL)),
)
def test_personnel_imports_only_core_and_masterdata(path: Path) -> None:
    """CLAUDE.md §3: personnel yalnızca core ve masterdata'ya bağlıdır; maliyeti bilmez."""
    apps = {name.split(".")[1] for name in _imports(path) if name.startswith("apps.")}
    assert apps <= {"core", "masterdata", "personnel"}, apps
