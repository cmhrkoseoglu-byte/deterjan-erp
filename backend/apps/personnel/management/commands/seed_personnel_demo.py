"""Personel demo verisi: demo kullanıcıların kartları, sistemi kullanmayan saha çalışanları,
ayrılmış bir personel ve özlük bilgisi ile belgeleri dolu örnek bir kart. `seed_demo` sonunda
çağrılır; tekrar çalıştırmak güvenlidir (var olan sicil no ve belgesi olan kart atlanır). Adlar,
telefonlar ve belgeler örnektir; TC kimlik no girilmez (eğitim ortamına gerçek kişi bilgisi
girilmez)."""

from datetime import date, timedelta
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
from apps.personnel import services
from apps.personnel.models import Employee, EmployeeDocument

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
    write(f"Personel demo verisi: {created} yeni kart.")


class Command(BaseCommand):
    help = "Personel demo verisi (yalnızca geliştirme ya da eğitim ortamında)."

    def handle(self, *args: Any, **options: Any) -> None:
        require_demo_allowed()
        with transaction.atomic():
            seed(self.stdout.write)
