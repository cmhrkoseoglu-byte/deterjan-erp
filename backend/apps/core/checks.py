"""Yetki kataloğunun sistem denetimleri (`manage.py check`, CI; docs/plan/kisi-yetkileri.md §5.1).

- `access.E001`: kataloğun bütünlüğü (tanımsız ön koşul, döngü, açık kayıtlar satırı...).
- `access.E002`: bir modül, bağlı olmadığı bir modülün bölümlerini kullanıyor (CLAUDE.md §3).
- `access.E003`: yetki denetimine geçen modülde bölüm denetimi ya da açık işaret (`SignedIn`)
  taşımayan API uç noktası. Geçiş boyunca (2-7. adımlar) yalnız `ENFORCED_APPS`'teki modüllere
  uygulanır; 7. adımın sonunda bütün modüllere.
"""

import ast
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from django.apps import AppConfig
from django.core import checks

from apps.core import access

APPS_DIR = Path(__file__).resolve().parent.parent

# Yetki denetimine geçmiş modüller (her adım kendi modüllerini ekler).
ENFORCED_APPS: frozenset[str] = frozenset()

# Her modülün bölümüne bakabilen modüller: workflow herkesi dinler (CLAUDE.md §3).
DEPENDENCY_EXEMPT: frozenset[str] = frozenset({"workflow"})

# Katalog modülü → modülü kaydeden uygulama (çoğunda aynı ad).
MODULE_OWNERS: dict[str, str] = {"sensitive": "core", "system": "core"}
_SECTION_KEY = re.compile(r"^[a-z][a-z_]*\.[a-z][a-z_]*$")


@checks.register("access")
def check_access(app_configs: Sequence[AppConfig] | None = None, **kwargs: Any) -> list[Any]:
    messages: list[Any] = [checks.Error(text, id="access.E001") for text in access.validate()]
    messages.extend(checks.Error(text, id="access.E002") for text in dependency_errors(APPS_DIR))
    messages.extend(checks.Error(text, id="access.E003") for text in endpoint_errors(ENFORCED_APPS))
    return messages


def _imported_apps(path: Path) -> tuple[set[str], set[str]]:
    """Bir dosyanın import ettiği uygulamalar: (access dışı importlar, access importları)."""
    plain: set[str] = set()
    access_imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets: list[str]
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            # `from apps.x import access` access importudur; `from apps.x import y` bağlılıktır.
            targets = (
                [f"{node.module}.{alias.name}" for alias in node.names]
                if len(parts) == 2
                else [node.module]
            )
        elif isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        else:
            continue
        for name in targets:
            parts = name.split(".")
            if len(parts) < 2 or parts[0] != "apps":
                continue
            if len(parts) >= 3 and parts[2] == "access":
                access_imports.add(parts[1])
            else:
                plain.add(parts[1])
    # Bölüm anahtarı yazıyla da verilebilir (`HasAccess("quality.samples")`): kayıtlı anahtar
    # taşıyan her metin, sahibi olan uygulamanın bölüm kullanımıdır.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _SECTION_KEY.match(node.value)
            and access.has_section(node.value)
        ):
            module = node.value.split(".", 1)[0]
            access_imports.add(MODULE_OWNERS.get(module, module))
    return plain, access_imports


def dependency_errors(apps_dir: Path) -> list[str]:
    """Bir modül, başka bir modülün bölümlerini ancak o modüle zaten bağlıysa kullanır.

    Bağlılık, modülün access dışındaki importlarından çıkarılır (testler ve göçler hariç).
    """
    errors: list[str] = []
    for app_dir in sorted(item for item in apps_dir.iterdir() if (item / "__init__.py").exists()):
        app = app_dir.name
        depends: set[str] = set()
        uses: set[str] = set()
        for path in app_dir.rglob("*.py"):
            relative = path.relative_to(app_dir).parts
            if relative[0] in ("tests", "migrations"):
                continue
            plain, access_imports = _imported_apps(path)
            depends |= plain
            uses |= access_imports
        if app in DEPENDENCY_EXEMPT:
            continue
        for other in sorted(uses - depends - {app, "core"}):
            errors.append(
                f"{app} modülü {other} modülünün yetki bölümlerini kullanıyor ama {other} "
                "modülüne bağlı değil (CLAUDE.md §3)."
            )
    return errors


def endpoint_errors(enforced: Iterable[str]) -> list[str]:
    """Geçen modüllerde her API uç noktasının izni bölüm denetimi ya da açık işaret olmalıdır."""
    enforced = set(enforced)
    if not enforced:
        return []
    from rest_framework.schemas.generators import EndpointEnumerator
    from rest_framework.test import APIRequestFactory

    factory = APIRequestFactory()
    errors: list[str] = []
    for path, method, callback in EndpointEnumerator().get_api_endpoints():
        cls = getattr(callback, "cls", None)
        if cls is None:
            continue
        module_parts = cls.__module__.split(".")
        if len(module_parts) < 2 or module_parts[0] != "apps" or module_parts[1] not in enforced:
            continue
        view = cls(**getattr(callback, "initkwargs", {}))
        actions = getattr(callback, "actions", None) or {}
        view.action = actions.get(method.lower())
        view.request = factory.generic(method, path)
        view.kwargs = {}
        for permission in view.get_permissions():
            if not _is_access_permission(permission):
                errors.append(
                    f"{method} {path}: izin bölüm denetimi ya da açık işaret değil "
                    f"({type(permission).__name__})."
                )
    return errors


def _is_access_permission(permission: Any) -> bool:
    from apps.core.permissions import AccessPermission

    if isinstance(permission, AccessPermission):
        return True
    # DRF'nin `A | B`, `A & B` ve `~A` birleşimleri.
    operands = [getattr(permission, name, None) for name in ("op1", "op2")]
    present = [operand for operand in operands if operand is not None]
    return bool(present) and all(_is_access_permission(operand) for operand in present)
