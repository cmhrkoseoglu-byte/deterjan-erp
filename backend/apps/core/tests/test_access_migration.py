"""Bölüm denetimine geçen modüllerde rol denetimi kalmaz (docs/plan/kisi-yetkileri.md §10).

Geçen modüller sistem denetiminin `ENFORCED_APPS` listesidir (E003). Taranan: modülün testler ve
göçler dışındaki bütün Python dosyaları (apps.py, raporlar, serializer'lar ve kayıt türleri dahil).
"""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from apps.core.checks import APPS_DIR, ENFORCED_APPS

# Rol denetimleri: işlevler, veri olarak yazılmış rol listeleri (`write_roles=`, `roles=`) ve
# rollere doğrudan bakan sorgular. Rol sabitlerini yalnız `access.py` (rol paketleri) kullanır.
ROLE_CHECK = re.compile(
    r"\b(HasRole|_require_role|user_has_role|has_role|role_names)\b"
    r"|\b(write_roles|action_roles|roles)\s*="
    r"|groups__name|groups\.filter"
    r"|from apps\.core\.roles import|from apps\.core import roles"
)
# İzin verilen rol denetimleri (plan §10): iki aşamalı doğrulama, bakımda sorumlu birim, görev
# yönlendirme ve yetki hesabının kendi rol denetimleri; rol denetimi olmayan rol adı kullanımları da
# (ör. demo kullanıcısı). Anahtar `<dosya>: <satırın metni>`dir: satır numarası kayınca liste
# bozulmaz, satır değişince yeniden bakılır. Değer nedeni söyler.
DEMO_USER = "demo kullanıcısı rolün adıyla bulunur (`create_demo_users`); rol denetimi değil"
ROLE_LABEL = "rol adları ekranda ve çıktıda etiket olarak; rol denetimi değil"
USER_ROLES = "kullanıcı kaydının rol verisi (Kullanıcılar ekranı, yalnız admin); rol denetimi değil"
ACCESS_CALC = "geçerli yetki hesabı rollerden başlar (plan §5.3, §10 izinli)"
ROLE_SEED = "rolleri ve ilk kullanıcıları kuran komut; rol denetimi değil"
ROLE_PRIMITIVE = (
    "rol ilkeli: is_admin, iki aşamalı doğrulama, son admin kuralı, görev yönlendirme (plan §10)"
)
ROUTING = (
    "görev yönlendirme: kuralın rolü alıcıyı ve görevin birimini seçer (plan §5.7, §10 izinli)"
)
ALLOWED: dict[str, str] = {
    "production/management/commands/seed_demo.py: from apps.core.roles import PLANLAMA": DEMO_USER,
    "filling/management/commands/seed_filling_demo.py: "
    "from apps.core.roles import LABORATUVAR, PLANLAMA": DEMO_USER,
    "quality/management/commands/seed_quality_demo.py: from apps.core.roles import LABORATUVAR": (
        DEMO_USER
    ),
    "sales/management/commands/seed_sales_demo.py: from apps.core.roles import DEPO, SEVKIYAT": (
        DEMO_USER
    ),
    "hse/management/commands/seed_hse_demo.py: "
    "from apps.core.roles import DEPO, LABORATUVAR, YONETIM": DEMO_USER,
    "golive/management/commands/seed_golive_demo.py: from apps.core.roles import DEPO": DEMO_USER,
    "personnel/management/commands/seed_personnel_demo.py: from apps.core.roles import (": (
        DEMO_USER
    ),
    "maintenance/management/commands/seed_maintenance_demo.py: "
    "from apps.core.roles import LABORATUVAR, URETIM": DEMO_USER,
    "costing/management/commands/seed_costing_demo.py: from apps.core.roles import YONETIM": (
        DEMO_USER
    ),
    "golive/selectors.py: from apps.core.roles import ADMIN, ALL_ROLES, ROLE_LABELS": (
        "hazırlık listesi her rolün kullanıcı sayısını gösterir (veri); rol denetimi değil"
    ),
    "maintenance/models.py: from apps.core.roles import DOLUM, LABORATUVAR, PLANLAMA, URETIM, "
    "YONETIM": "bakımda sorumlu birim seçenekleri (iş verisi); rol denetimi değil",
    "maintenance/services.py: from apps.core.roles import DOLUM, LABORATUVAR, URETIM": (
        "bakımda sorumlu birim: varsayılan birim ve temizlik iş emrinin birimi (plan §10)"
    ),
    "maintenance/services.py: return actor.has_role(order.responsible_role)": (
        "bakımda sorumlu birim kuralı (plan §4 satır kuralı, §10 izin listesi)"
    ),
    "core/access_export.py: from apps.core.roles import ROLE_LABELS": ROLE_LABEL,
    "core/admin.py: from apps.core.roles import ROLE_LABELS": ROLE_LABEL,
    "core/api/access.py: from apps.core.roles import ROLE_LABELS": ROLE_LABEL,
    (
        "core/api/filters.py: role = "
        'django_filters.CharFilter(field_name="groups__name", label="Rol")'
    ): USER_ROLES,
    "core/api/serializers.py: from apps.core.roles import ALL_ROLES": USER_ROLES,
    (
        "core/api/serializers.py: roles = "
        "serializers.ListField(child=serializers.CharField(), read_only=True)"
    ): "oturumdaki kullanıcının rolleri (me yanıtı, ön yüzün rol görünümü); rol denetimi değil",
    "core/api/serializers.py: roles = serializers.SerializerMethodField()": USER_ROLES,
    "core/api/serializers.py: roles = serializers.ListField(": USER_ROLES,
    (
        "core/api/serializers.py: roles = "
        "serializers.ListField(child=serializers.ChoiceField(choices=ALL_ROLES), "
        "required=False)"
    ): USER_ROLES,
    "core/effective_access.py: role_names: Iterable[str],": ACCESS_CALC,
    "core/effective_access.py: roles = set(role_names) & set(ROLES)": ACCESS_CALC,
    (
        "core/effective_access.py: return compute_access(user.role_names, "
        "grants=grants, revokes=revokes)"
    ): ACCESS_CALC,
    (
        "core/management/commands/create_demo_users.py: from apps.core.roles "
        "import ADMIN, ALL_ROLES, ROLE_LABELS"
    ): ROLE_SEED,
    "core/management/commands/create_first_admin.py: from apps.core.roles import ADMIN": ROLE_SEED,
    "core/management/commands/seed_roles.py: from apps.core.roles import ALL_ROLES": ROLE_SEED,
    "core/models.py: from apps.core.roles import ADMIN": ROLE_PRIMITIVE,
    "core/models.py: def role_names(self) -> frozenset[str]:": ROLE_PRIMITIVE,
    "core/models.py: return sorted(self.role_names)": ROLE_PRIMITIVE,
    "core/models.py: def has_role(self, *roles: str) -> bool:": ROLE_PRIMITIVE,
    "core/models.py: return bool(self.role_names.intersection(roles))": ROLE_PRIMITIVE,
    "core/models.py: return self.is_superuser or self.has_role(ADMIN)": ROLE_PRIMITIVE,
    'core/models.py: self.__dict__.pop("role_names", None)': ROLE_PRIMITIVE,
    (
        "core/security.py: return user.has_role(*required)"
    ): "iki aşamalı doğrulamanın zorunlu olduğu roller (plan §10 izinli)",
    (
        "core/services.py: from apps.core.roles import ADMIN, ALL_ROLES"
    ): "rol atama ve son admin kuralı (plan §5.10)",
    (
        "core/services.py: .filter(Q(is_superuser=True) | Q(groups__name=ADMIN))"
    ): "son admin kuralı: sistemde en az bir admin kalır (plan §5.10)",
    (
        "core/services.py: if user.has_role(ADMIN) and ADMIN not in wanted:"
    ): "admin kendi admin rolünü kaldıramaz (plan §5.10)",
    (
        "reporting/dashboards.py: from apps.core.roles import ROLE_LABELS"
    ): "gecikmiş görevler kartı role göre gruplar ve rol adını gösterir; rol denetimi değil",
    (
        "reporting/filters.py: from apps.core.roles import ROLE_LABELS"
    ): "görev süreleri raporunun rol süzgecinin etiketleri; rol denetimi değil",
    (
        "reporting/selectors.py: from apps.core.roles import ROLE_LABELS"
    ): "görev süreleri raporunun rol sütunu etiketleri; rol denetimi değil",
    "core/coverage.py: from apps.core.roles import ADMIN, ROLE_LABELS": ROLE_PRIMITIVE,
    "core/user_access.py: from apps.core.roles import ADMIN, ROLE_LABELS": (
        "Yetkiler kaydının planı: admin rol kancası ve uyarılardaki rol adları (plan §5.2, §5.10)"
    ),
    "workflow/rules.py: from apps.core.roles import (": ROUTING,
    "workflow/rules.py: roles=(DEPO, SATIN_ALMA),": ROUTING,
    "workflow/rules.py: roles=(PLANLAMA, LABORATUVAR),": ROUTING,
    "workflow/rules.py: roles=(URETIM, PLANLAMA),": ROUTING,
    "workflow/rules.py: roles=(PLANLAMA, URETIM),": ROUTING,
    "workflow/rules.py: roles=(PLANLAMA, YONETIM),": ROUTING,
    "workflow/rules.py: roles=(SEVKIYAT, PLANLAMA),": ROUTING,
    "workflow/rules.py: roles=(PLANLAMA, DOLUM),": ROUTING,
    "workflow/rules.py: roles=(SEVKIYAT,),": ROUTING,
    "workflow/rules.py: roles=(DEPO, PLANLAMA),": ROUTING,
    "workflow/rules.py: roles=(YONETIM,),": ROUTING,
    "workflow/rules.py: roles=(SATIN_ALMA,),": ROUTING,
    "workflow/rules.py: roles=(DEPO,),": ROUTING,
    "workflow/rules.py: roles=(PLANLAMA,),": ROUTING,
    "workflow/rules.py: roles=(DEPO, YONETIM),": ROUTING,
    "workflow/rules.py: roles=(),": ROUTING,
    "workflow/rules.py: roles=(ADMIN,),": ROUTING,
    (
        "workflow/selectors.py: return task.assigned_role is not None and "
        "user.has_role(task.assigned_role.name)"
    ): ROUTING,
    "workflow/selectors.py: own_roles = Q(assigned_role__name__in=list(user.role_names))": ROUTING,
    (
        "workflow/selectors.py: visible |= Q(assigned_role__isnull=True) | "
        "~Q(assigned_role__name__in=list(user.role_names))"
    ): ROUTING,
    (
        "workflow/services.py: members = User.objects.filter(is_active=True, "
        "groups__name__in=list(roles)).distinct()"
    ): ROUTING,
}


def _role_lines(apps_dir: Path, apps: Iterable[str]) -> list[tuple[str, str]]:
    """Rol denetimi satırları: (`<dosya>: <metin>` anahtarı, `<dosya>:<satır>: <metin>`)."""
    lines: list[tuple[str, str]] = []
    for app in sorted(apps):
        for path in sorted((apps_dir / app).rglob("*.py")):
            relative = path.relative_to(apps_dir)
            # Atlanan: testler, göçler ve modülün kök katalog dosyası (`<modül>/access.py`, yalnız
            # veri). Aynı adı taşıyan alt dosyalar (ör. `core/api/access.py`, bir görünüm) taranır.
            if relative.parts[1] in ("tests", "migrations") or relative.parts[1:] == ("access.py",):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if ROLE_CHECK.search(line):
                    name, text = relative.as_posix(), line.strip()
                    lines.append((f"{name}: {text}", f"{name}:{number}: {text}"))
    return lines


def role_checks(
    apps_dir: Path, apps: frozenset[str], allowed: Mapping[str, str] = ALLOWED
) -> list[str]:
    """Modüllerde kalan rol denetimleri (izin listesi dışında): `<dosya>:<satır>: <metin>`."""
    return [where for key, where in _role_lines(apps_dir, apps) if key not in allowed]


def test_converted_modules_have_no_role_checks() -> None:
    assert ENFORCED_APPS, "Henüz geçen modül yok."
    missing = sorted(app for app in ENFORCED_APPS if not (APPS_DIR / app / "__init__.py").exists())
    assert not missing, f"ENFORCED_APPS'te olmayan modül: {missing}"
    found = role_checks(APPS_DIR, ENFORCED_APPS)
    assert not found, "Bölüm denetimine geçen modülde rol denetimi kaldı:\n" + "\n".join(found)


def test_scanner_finds_role_checks(tmp_path: Path) -> None:
    app = tmp_path / "demo"
    (app / "tests").mkdir(parents=True)
    (app / "api").mkdir()
    (app / "api" / "views.py").write_text("x = HasRole(DEPO)\n", encoding="utf-8")
    (app / "services.py").write_text("if user.has_role('depo'):\n    pass\n", encoding="utf-8")
    (app / "apps.py").write_text(
        "register_record_type('demo.x', roles=READERS)\nregister_master_code('k', write_roles=W)\n",
        encoding="utf-8",
    )
    (app / "selectors.py").write_text(
        "from apps.core.roles import DEPO\nUser.objects.filter(groups__name=DEPO)\n",
        encoding="utf-8",
    )
    (app / "access.py").write_text("from apps.core.roles import DEPO\n", encoding="utf-8")
    (app / "api" / "access.py").write_text("x = HasRole(DEPO)\n", encoding="utf-8")
    (app / "tests" / "test_x.py").write_text("HasRole\n", encoding="utf-8")

    assert role_checks(tmp_path, frozenset({"demo"})) == [
        "demo/api/access.py:1: x = HasRole(DEPO)",
        "demo/api/views.py:1: x = HasRole(DEPO)",
        "demo/apps.py:1: register_record_type('demo.x', roles=READERS)",
        "demo/apps.py:2: register_master_code('k', write_roles=W)",
        "demo/selectors.py:1: from apps.core.roles import DEPO",
        "demo/selectors.py:2: User.objects.filter(groups__name=DEPO)",
        "demo/services.py:1: if user.has_role('depo'):",
    ]
    allowed = {"demo/services.py: if user.has_role('depo'):": "deneme"}
    assert "demo/services.py:1: if user.has_role('depo'):" not in role_checks(
        tmp_path, frozenset({"demo"}), allowed
    )


def test_allowed_role_lines_still_exist() -> None:
    """İzin listesindeki her satır hâlâ koddadır: kaldırılan ya da değişen satırın izni de
    kaldırılır."""
    apps = {key.split("/", 1)[0] for key in ALLOWED}
    present = {key for key, _ in _role_lines(APPS_DIR, apps)}
    assert not set(ALLOWED) - present
