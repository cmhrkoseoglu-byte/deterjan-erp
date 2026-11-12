"""Bölüm denetimine geçen modüllerde rol denetimi kalmaz (docs/plan/kisi-yetkileri.md §10).

Geçen modüller sistem denetiminin `ENFORCED_APPS` listesidir (E003). Taranan: modülün testler ve
göçler dışındaki bütün Python dosyaları (apps.py, raporlar, serializer'lar ve kayıt türleri dahil).
"""

import re
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
# yönlendirme ve yetki hesabının kendi rol denetimleri. Geçen modüllerde bugün yok.
ALLOWED: frozenset[str] = frozenset()


def role_checks(apps_dir: Path, apps: frozenset[str]) -> list[str]:
    """Modüllerde kalan rol denetimleri: `<dosya>:<satır>: <metin>`."""
    found: list[str] = []
    for app in sorted(apps):
        for path in sorted((apps_dir / app).rglob("*.py")):
            relative = path.relative_to(apps_dir)
            if relative.parts[1] in ("tests", "migrations") or relative.name == "access.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                where = f"{relative.as_posix()}:{number}"
                if ROLE_CHECK.search(line) and where not in ALLOWED:
                    found.append(f"{where}: {line.strip()}")
    return found


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
    (app / "tests" / "test_x.py").write_text("HasRole\n", encoding="utf-8")

    assert role_checks(tmp_path, frozenset({"demo"})) == [
        "demo/api/views.py:1: x = HasRole(DEPO)",
        "demo/apps.py:1: register_record_type('demo.x', roles=READERS)",
        "demo/apps.py:2: register_master_code('k', write_roles=W)",
        "demo/selectors.py:1: from apps.core.roles import DEPO",
        "demo/selectors.py:2: User.objects.filter(groups__name=DEPO)",
        "demo/services.py:1: if user.has_role('depo'):",
    ]
