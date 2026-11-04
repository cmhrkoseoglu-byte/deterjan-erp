"""Personel demo verisi: demo kullanıcıların kartları, sistemi kullanmayan saha çalışanları,
ayrılmış bir personel, özlük bilgisi ile belgeleri dolu örnek bir kart, geçen ayın puantajı,
örnek brüt ücretler ve (Ekim 2026'dan) ön bordro örneği: yılın parametre seti, zincirin ilk ayına
devirler ve geçen aya birkaç ek ödeme ve kesinti. `seed_demo` sonunda çağrılır; tekrar çalıştırmak
güvenlidir (var olan sicil no, belgesi olan kart, kaydı olan ay, ücreti olan kişi, yılın seti,
devri olan kişi ve kalemi olan ay atlanır; bordrosu onaylı aya yazılmaz). Adlar, telefonlar,
belgeler ve tutarlar örnektir; TC kimlik no girilmez (eğitim ortamına gerçek kişi bilgisi
girilmez)."""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.core.demo import require_demo_allowed
from apps.core.labels import FONT, register_fonts
from apps.core.models import User
from apps.core.roles import (
    DEPO,
    DOLUM,
    LABORATUVAR,
    PLANLAMA,
    SATIN_ALMA,
    SEVKIYAT,
    URETIM,
    YONETIM,
)
from apps.personnel import payroll, selectors, services
from apps.personnel.models import (
    AttendanceEntry,
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeWage,
    PayrollItem,
    PayrollItemCategory,
    PayrollOpeningBalance,
    PayrollParameterSet,
    PayrollRun,
)

# demo kullanıcı (rol kodu): (sicil no, birim, görev, kaç gün önce işe girdi)
USER_CARDS = {
    YONETIM: ("S-0001", "Yönetim", "Fabrika müdürü", 3650),
    PLANLAMA: ("S-0002", "Planlama", "Üretim planlama uzmanı", 1460),
    DEPO: ("S-0003", "Depo", "Depo sorumlusu", 2190),
    URETIM: ("S-0004", "Üretim", "Üretim şefi", 1825),
    LABORATUVAR: ("S-0005", "Kalite kontrol", "Kalite kontrol uzmanı", 1095),
    DOLUM: ("S-0006", "Dolum", "Dolum hattı şefi", 1200),
    SEVKIYAT: ("S-0007", "Sevkiyat", "Sevkiyat sorumlusu", 900),
    SATIN_ALMA: ("S-0008", "Satın alma", "Satın alma uzmanı", 700),
}
# Sistemi kullanmayan saha çalışanları: (sicil no, ad soyad, birim, görev, kaç gün önce)
FIELD_CARDS = [
    ("S-0011", "Demo Forklift Operatörü", "Depo", "Forklift operatörü", 800),
    ("S-0012", "Demo Dolum Operatörü 1", "Dolum", "Dolum operatörü", 600),
    ("S-0013", "Demo Dolum Operatörü 2", "Dolum", "Dolum operatörü", 240),
    ("S-0014", "Demo Karıştırma Operatörü", "Üretim", "Karıştırma operatörü", 1300),
    ("S-0015", "Demo Bakım Teknisyeni", "Bakım", "Bakım teknisyeni", 1000),
]
# Ayrılmış personel: (sicil no, ad soyad, birim, görev, işe giriş ve çıkış kaç gün önce)
LEFT_CARD = ("S-0010", "Demo Eski Operatör", "Üretim", "Karıştırma operatörü", 1500, 90)
# Kimlik, mezuniyet ve belgeleri dolu örnek kart (kılavuzdaki görsel bu karttan).
PROFILE_CARD = "S-0012"
# Geçen ayın puantajında izin, rapor, devamsızlık ve fazla mesaisi olan saha çalışanları.
ATTENDANCE_CARDS = ("S-0011", "S-0012", "S-0013", "S-0014")
# Örnek brüt aylık ücretler (TL; eğitim içindir, gerçek kişi ücreti değildir): sicil no → tutar.
WAGES = {
    "S-0001": "120000",
    "S-0002": "62000",
    "S-0003": "52000",
    "S-0004": "68000",
    "S-0005": "58000",
    "S-0006": "60000",
    "S-0007": "50000",
    "S-0008": "55000",
    "S-0010": "36000",
    "S-0011": "38000",
    "S-0012": "36000",
    "S-0013": "34000",
    "S-0014": "38000",
    "S-0015": "42000",
}
# Zam örneği: geçen ayın ilk gününden geçerli.
RAISE = ("S-0012", "39000")
# Ön bordro örneği: geçen ayın ek ödeme ve kesintileri (sicil no, kategori, tutar).
PAYROLL_ITEMS = (
    ("S-0011", PayrollItemCategory.PREMIUM, "2500"),
    ("S-0014", PayrollItemCategory.MEAL, "1800"),
    ("S-0012", PayrollItemCategory.ADVANCE, "3000"),
)
# Devrin kümülatif GV matrahı tahmini: brüt ücretin SGK ve işsizlik işçi payları (%15) düşülmüşü.
TAX_BASE_SHARE = Decimal("0.85")


def _phone(number: int) -> str:
    return f"0500 000 {number // 100:02d} {number % 100:02d}"


def _demo_pdf(name: str, title: str) -> SimpleUploadedFile:
    """Tek sayfalık örnek belge."""
    register_fonts()
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    page.setFont(FONT, 16)
    page.drawString(72, 760, title)
    page.setFont(FONT, 11)
    page.drawString(72, 736, "Eğitim ortamı için örnek belgedir; gerçek kişi bilgisi içermez.")
    page.showPage()
    page.save()
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/pdf")


def _profile(actor: User, card: Employee, today: date) -> None:
    """Örnek kartın kimlik ve mezuniyet bilgileri ile belgeleri; belgesi olan kart atlanır."""
    if card.documents.exists():
        return
    values = {
        "birth_date": date(today.year - 31, 4, 12),
        "birth_place": "İzmir",
        "education_level": Employee.EducationLevel.HIGH_SCHOOL,
        "school": "Demo Mesleki ve Teknik Anadolu Lisesi",
        "field_of_study": "Kimya teknolojisi",
        "graduation_year": today.year - 13,
    }
    services.update_employee(actor, card, values)
    kind = EmployeeDocument.Kind
    services.add_document(
        actor, card, kind=kind.ID_COPY, file=_demo_pdf("kimlik.pdf", "Kimlik fotokopisi (örnek)")
    )
    services.add_document(
        actor,
        card,
        kind=kind.CONTRACT,
        file=_demo_pdf("is-sozlesmesi.pdf", "İş sözleşmesi (örnek)"),
        valid_from=card.hire_date,
    )
    period = today.replace(day=1)
    for _ in range(2):
        period = (period - timedelta(days=1)).replace(day=1)
        services.add_document(
            actor,
            card,
            kind=kind.PAYROLL,
            file=_demo_pdf(f"bordro-{period:%Y-%m}.pdf", f"Bordro {period:%m.%Y} (örnek)"),
            period=period,
        )
    services.add_document(
        actor, card, kind=kind.DIPLOMA, file=_demo_pdf("diploma.pdf", "Lise diploması (örnek)")
    )


def seed(write: Any = print) -> None:
    actor = User.objects.get(username=YONETIM)
    today = timezone.localdate()
    created = 0

    def add(employee_no: str, values: dict[str, Any], days_ago: int, index: int) -> Employee:
        nonlocal created
        existing = Employee.objects.filter(employee_no=employee_no).first()
        if existing is not None:
            return existing
        created += 1
        return services.create_employee(
            actor,
            {
                "employee_no": employee_no,
                "hire_date": today - timedelta(days=days_ago),
                "phone": _phone(index),
                "emergency_contact_name": "Demo Yakını",
                "emergency_contact_phone": _phone(100 + index),
                **values,
            },
        )

    for index, (role, (employee_no, department, title, days_ago)) in enumerate(
        USER_CARDS.items(), start=1
    ):
        user = User.objects.filter(username=role).first()
        if user is None:
            continue
        linked = Employee.objects.filter(user=user).exists()
        values = {"full_name": user.full_name, "department": department, "title": title}
        add(employee_no, values if linked else {**values, "user": user}, days_ago, index)

    for index, (employee_no, full_name, department, title, days_ago) in enumerate(
        FIELD_CARDS, start=11
    ):
        values = {"full_name": full_name, "department": department, "title": title}
        add(employee_no, values, days_ago, index)

    employee_no, full_name, department, title, hired, left = LEFT_CARD
    former = add(
        employee_no, {"full_name": full_name, "department": department, "title": title}, hired, 10
    )
    if former.is_active:
        services.terminate_employee(actor, former, today - timedelta(days=left))
    profile = Employee.objects.filter(employee_no=PROFILE_CARD).first()
    if profile is not None:
        _profile(actor, profile, today)
    _attendance(actor, today)
    wages = _wages(actor, today)
    sets, openings, items = _payroll(actor, today)
    write(
        f"Personel demo verisi: {created} yeni kart, {wages} personel ücreti, {sets} parametre "
        f"seti, {openings} devir, {items} bordro kalemi."
    )


def _wages(actor: User, today: date) -> int:
    """Örnek ücretler: yılbaşından (geçen ayın yılı) ya da işe girişten geçerli; bir kişiye geçen
    ayın başından zam. Ücreti olan kişi atlanır. Eklenen kişi sayısını döner."""
    previous = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    added = 0
    for employee_no, amount in WAGES.items():
        person = Employee.objects.filter(employee_no=employee_no).first()
        if person is None or EmployeeWage.objects.filter(employee=person).exists():
            continue
        start = max(date(previous.year, 1, 1), person.hire_date or date.min)
        values = {"employee": person, "gross_monthly": Decimal(amount), "note": "Demo"}
        services.add_wage(actor, {**values, "valid_from": start})
        added += 1
        if employee_no == RAISE[0] and previous > start:
            raised = {**values, "gross_monthly": Decimal(RAISE[1]), "note": "Demo zam"}
            services.add_wage(actor, {**raised, "valid_from": previous})
    return added


def _approved(year: int, month: int) -> bool:
    return PayrollRun.objects.filter(
        year=year, month=month, status=PayrollRun.Status.APPROVED
    ).exists()


def _legal_values(params: payroll.Parameters) -> dict[str, Any]:
    """Yasal değerler, parametre seti alanları olarak."""
    names = (
        "minimum_wage",
        "ceiling_multiplier",
        "employee_sgk_rate",
        "employee_unemployment_rate",
        "employer_sgk_rate",
        "employer_unemployment_rate",
        "incentive_points",
        "stamp_tax_per_mille",
        "bes_rate",
        "meal_exemption_daily",
    )
    values: dict[str, Any] = {name: getattr(params, name) for name in names}
    for index, limit in enumerate(params.tax_brackets, start=1):
        values[f"tax_bracket_{index}"] = limit
    for index, rate in enumerate(params.tax_rates, start=1):
        values[f"tax_rate_{index}"] = rate
    return values


def _payroll(actor: User, today: date) -> tuple[int, int, int]:
    """Ön bordro örneği (geçen ay başlangıç ayı ya da sonrasıysa): geçen ayın yılının parametre
    seti (yasal değerler, Ocak'tan; o yıl set yoksa), zincirin ilk ayına (başlangıç yılında Ekim)
    o aydan önce bu yıl çalışan kişilerin devri (ücretten tahmini) ve geçen aya birkaç ek ödeme ve
    kesinti. Bordro onaylanmaz (eğitimde onaylansın); bordrosu onaylı aya yazılmaz. (set, devir,
    kalem) sayılarını döner."""
    previous = today.replace(day=1) - timedelta(days=1)
    year, month = previous.year, previous.month
    if not selectors.net_available(year, month):
        return 0, 0, 0
    sets = openings = items = 0
    legal = payroll.legal_parameters(year)
    saved = PayrollParameterSet.objects.filter(is_active=True, valid_from__year=year)
    if legal is not None and not saved.exists():
        values = {
            **_legal_values(legal),
            "valid_from": date(year, 1, 1),
            "source": "Demo: yılın yasal değerleri (mali müşavirle teyit edilmedi)",
            "note": "Demo",
        }
        services.create_parameter_set(actor, values)
        sets = 1
    start = selectors.chain_start(year)
    if start is not None and start > 1 and not _approved(year, start):
        first, last = selectors.month_bounds(year, start)
        for person in selectors.employees_between(first, last).filter(payroll_external=False):
            months = selectors.months_employed_before(person, year, start)
            existing = PayrollOpeningBalance.objects.filter(
                employee=person, year=year, month=start, is_active=True
            )
            if not months or existing.exists():
                continue
            wages = list(person.wages.filter(is_active=True).order_by("valid_from", "id"))
            wage = selectors.wage_on(wages, first)
            if wage is None:
                continue
            services.set_opening_balance(
                actor,
                person,
                year,
                start,
                tax_base=(wage * TAX_BASE_SHARE * months).quantize(Decimal("0.01")),
                exemption_months=months,
                note="Demo devri (ücretten tahmini)",
            )
            openings += 1
    month_items = PayrollItem.objects.filter(year=year, month=month, is_active=True)
    if not _approved(year, month) and not month_items.exists():
        first, last = selectors.month_bounds(year, month)
        working = selectors.employees_between(first, last).filter(payroll_external=False)
        for employee_no, category, amount in PAYROLL_ITEMS:
            card = working.filter(employee_no=employee_no).first()
            if card is None:
                continue
            services.add_payroll_item(
                actor,
                {
                    "employee": card,
                    "year": year,
                    "month": month,
                    "category": category,
                    "description": "",
                    "amount": Decimal(amount),
                },
            )
            items += 1
    return sets, openings, items


def _attendance(actor: User, today: date) -> None:
    """Bu yılın ve geçen ayın yılının sabit tatilleri; geçen ayın puantajında birkaç izin, rapor,
    devamsızlık ve fazla mesai. Ay açık bırakılır (eğitimde onaylanabilsin). Geçen ayda kayıt
    varsa puantaja dokunulmaz."""
    last = today.replace(day=1) - timedelta(days=1)
    first = last.replace(day=1)
    for year in sorted({last.year, today.year}):
        services.add_fixed_holidays(actor, year)
    if AttendanceEntry.objects.filter(date__range=(first, last)).exists():
        return
    holidays = selectors.holidays_between(first, last)
    rest = selectors.rest_weekdays()
    workdays = [
        day
        for day in selectors.days_between(first, last)
        if selectors.default_status(day, holidays.get(day), rest) == AttendanceStatus.WORKED
    ]
    people = {
        person.employee_no: person
        for person in Employee.objects.filter(employee_no__in=ATTENDANCE_CARDS)
        if all(selectors.employed_on(person, day) for day in (first, last))
    }
    status = AttendanceStatus
    if "S-0012" in people:
        services.set_attendance_range(
            actor,
            start=workdays[4],
            end=workdays[6],
            status=status.ANNUAL_LEAVE,
            employee=people["S-0012"],
        )
    if "S-0013" in people:
        services.set_attendance_range(
            actor,
            start=workdays[10],
            end=workdays[11],
            status=status.SICK_LEAVE,
            employee=people["S-0013"],
        )
    if "S-0011" in people:
        for day in workdays[1:4]:
            services.set_attendance_day(
                actor,
                people["S-0011"],
                day,
                status=status.WORKED,
                overtime_hours=Decimal(2),
                note="Sipariş yüklemesi",
            )
    if "S-0014" in people:
        services.set_attendance_day(actor, people["S-0014"], workdays[15], status=status.ABSENT)


class Command(BaseCommand):
    help = "Personel demo verisi (yalnızca geliştirme ya da eğitim ortamında)."

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        with transaction.atomic():
            seed(self.stdout.write)
