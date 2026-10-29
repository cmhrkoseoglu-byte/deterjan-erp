"""Personel okuma sorguları."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q, QuerySet

from apps.core.models import AuditLog, User
from apps.personnel.models import Employee, EmployeeDocument


def fold(text: str) -> str:
    """Türkçe büyük/küçük harf duyarsız karşılaştırma anahtarı ("İDARİ" = "idari", "I" = "ı")."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def departments() -> list[str]:
    """Kayıtlı birimler (ayrılan personelinkiler dahil), alfabetik."""
    names = Employee.objects.values_list("department", flat=True).distinct()
    return sorted(set(names), key=fold)


def canonical_department(name: str) -> str:
    """Birim daha önce farklı büyük/küçük harfle yazıldıysa o yazımı döner."""
    key = fold(name)
    return next((existing for existing in departments() if fold(existing) == key), name)


def employee_history(employee: Employee) -> QuerySet[AuditLog]:
    """Kartın denetim geçmişi (en yenisi önce)."""
    content_type = ContentType.objects.get_for_model(Employee)
    return (
        AuditLog.objects.filter(content_type=content_type, object_id=employee.pk)
        .select_related("actor")
        .order_by("-timestamp", "-id")
    )


def employee_documents(employee: Employee) -> QuerySet[EmployeeDocument]:
    """Kartın kaldırılmamış belgeleri: bordrolar dönemine, sözleşmeler başlangıcına, diğerleri
    eklenme zamanına göre en yenisi önce."""
    return (
        employee.documents.filter(is_active=True)
        .select_related("created_by")
        .order_by(
            F("period").desc(nulls_last=True),
            F("valid_from").desc(nulls_last=True),
            "-created_at",
            "-id",
        )
    )


def linkable_users(employee: Employee | None = None) -> QuerySet[User]:
    """Karta bağlanabilecek kullanıcılar: aktif ve başka bir karta bağlı olmayanlar. Düzenlenen
    kartın bağlı kullanıcısı (pasif olsa da) listede kalır."""
    condition = Q(is_active=True, employee__isnull=True)
    if employee is not None:
        condition |= Q(employee=employee)
    return User.objects.filter(condition).order_by("full_name", "username")
