"""Yetki kataloğunun sistem denetimleri (`manage.py check`)."""

from pathlib import Path

from apps.core import checks
from apps.core.permissions import HasAccess, HasRole, ReadRule, SignedIn
from apps.production.access import ORDERS, PREP


def test_real_project_passes_all_checks() -> None:
    assert checks.check_access() == []


def _app(root: Path, name: str, files: dict[str, str]) -> None:
    app = root / name
    app.mkdir()
    (app / "__init__.py").write_text("", encoding="utf-8")
    for relative, text in files.items():
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_dependency_check(tmp_path: Path) -> None:
    _app(tmp_path, "alpha", {"views.py": "from apps.beta.access import ORDERS\n"})
    _app(
        tmp_path,
        "gamma",
        {"views.py": "from apps.beta import selectors\nfrom apps.beta.access import X\n"},
    )
    _app(tmp_path, "delta", {"views.py": "from apps.beta import access\n"})
    _app(tmp_path, "workflow", {"rules.py": "from apps.beta.access import ORDERS\n"})
    _app(tmp_path, "epsilon", {"tests/test_x.py": "from apps.beta.access import ORDERS\n"})
    _app(tmp_path, "zeta", {"views.py": "from apps.core.access import PRICES\n"})
    _app(tmp_path, "beta", {"access.py": "X = 1\n"})

    errors = checks.dependency_errors(tmp_path)

    assert errors == [
        "alpha modülü beta modülünün yetki bölümlerini kullanıyor ama beta modülüne bağlı değil "
        "(CLAUDE.md §3).",
        "delta modülü beta modülünün yetki bölümlerini kullanıyor ama beta modülüne bağlı değil "
        "(CLAUDE.md §3).",
    ]


def test_endpoint_check_only_for_enforced_apps() -> None:
    assert checks.endpoint_errors(set()) == []

    errors = checks.endpoint_errors({"core"})

    assert errors
    assert any(
        "/api/v1/audit-log/" in error and "HasRole(admin, yonetim)" in error for error in errors
    )
    assert not any("/api/v1/access/catalog/" in error for error in errors)


def test_access_permission_recognition() -> None:
    assert checks._is_access_permission(HasAccess(ORDERS)())
    assert checks._is_access_permission(SignedIn("deneme")())
    assert checks._is_access_permission((HasAccess(ORDERS) | ReadRule(PREP))())
    assert not checks._is_access_permission(HasRole("depo")())
    assert not checks._is_access_permission((HasAccess(ORDERS) | HasRole("depo"))())
