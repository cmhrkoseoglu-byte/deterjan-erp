"""Kişiye özel ayarla sistem uçları (docs/plan/kisi-yetkileri.md §4, §10 6. adım): kullanıcılar,
saha tableti ve kodlama sistematiği yalnız admindir, hiçbir bölüm açmaz; kod önerisi türün yazma
yetkisini izler (kişiye özel ekleme ve kaldırma çalışır), yazma yetkisi olmayan tür yalnız admine.
"""

from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.core import access
from apps.core.access import CHANGE, READ
from apps.core.coding import services as coding
from apps.core.models import AccessOverride, User
from apps.core.permissions import DEFAULT_MESSAGE
from apps.core.roles import ADMIN, DEPO, PLANLAMA
from apps.masterdata.access import CARDS

pytestmark = pytest.mark.django_db

SUGGEST_DENIED = "Bu kayıt türünü yazma yetkiniz yok."


def override(user: User, key: str, level: str, effect: str = "revoke") -> User:
    AccessOverride.objects.create(user=user, key=key, level=level, effect=effect, note="deneme")
    user.refresh_access()
    return user


def grant_everything(user: User) -> User:
    """Katalogdaki her bölümün her düzeyi kişiye eklenir (açık kayıt okuması zaten açıktır)."""
    for section in access.sections():
        for level in section.levels:
            if level == READ:  # okuma kapsamı yalnız kaldırılır
                continue
            AccessOverride.objects.create(
                user=user, key=section.key, level=level, effect="grant", note="deneme"
            )
    user.refresh_access()
    return user


def api(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _admin_only_requests(target: User) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        ("get", "/api/v1/users/", {}),
        ("get", f"/api/v1/users/{target.pk}/", {}),
        ("post", "/api/v1/auth/field-device/", {"enabled": True}),
        ("get", "/api/v1/coding/types/", {}),
        ("get", "/api/v1/coding/revisions/", {}),
        ("get", "/api/v1/coding/runs/", {}),
        ("get", "/api/v1/coding/outputs/", {}),
    ]


def test_every_section_granted_does_not_open_admin_only_endpoints(
    make_user: Callable[..., User],
) -> None:
    """Her bölüm eklenmiş planlamacı yalnız admin uçlarında 403 alır (eksik yetki listesi yok);
    admin geçer. Karşılanmayan metotta da sıra bugünkü gibidir: önce yetki (403), admine 405."""
    target = make_user(DEPO)
    everything = api(grant_everything(make_user(PLANLAMA)))
    admin = api(make_user(ADMIN))

    for method, path, body in _admin_only_requests(target):
        refused = getattr(everything, method)(path, body, format="json")
        assert refused.status_code == 403, path
        assert refused.json()["detail"] == DEFAULT_MESSAGE, path
        assert "required" not in refused.json(), path
        assert getattr(admin, method)(path, body, format="json").status_code == 200, path

    assert everything.delete(f"/api/v1/users/{target.pk}/").status_code == 403
    assert admin.delete(f"/api/v1/users/{target.pk}/").status_code == 405
    assert everything.get("/api/v1/auth/field-device/").status_code == 403
    assert admin.get("/api/v1/auth/field-device/").status_code == 405


def test_every_section_granted_does_not_open_coding_services(
    make_user: Callable[..., User],
) -> None:
    """Kodlama servisleri de yalnız admindir (mesaj aynı); kayıt kodunu değiştirme de."""
    everything = grant_everything(make_user(PLANLAMA))

    with pytest.raises(PermissionDenied, match="yalnızca sistem yöneticisi değiştirir"):
        coding.update_scheme(everything, "document.TD", width=4, note="deneme")
    assert not coding.can_change_code(everything)
    with pytest.raises(PermissionDenied, match="yalnızca sistem yöneticisi değiştirebilir"):
        coding.ensure_can_change_code(everything)
    admin = make_user(ADMIN)
    coding.update_scheme(admin, "document.TD", width=4, note="deneme")
    assert coding.can_change_code(admin)


def test_suggestion_without_write_access_is_admin_only(make_user: Callable[..., User]) -> None:
    """Yazma yetkisi tanımlanmamış tür (belge numarası): her bölümü olan da 403 alır."""
    everything = api(grant_everything(make_user(PLANLAMA)))

    refused = everything.get("/api/v1/coding/suggest/document.TD/")
    assert refused.status_code == 403
    assert refused.json()["detail"] == SUGGEST_DENIED
    assert "required" not in refused.json()
    assert api(make_user(ADMIN)).get("/api/v1/coding/suggest/document.TD/").status_code == 200


def test_suggestion_follows_write_access_override(make_user: Callable[..., User]) -> None:
    """Malzeme kodu önerisi "Ana veri kartları: Değiştirir" ile açılır: depoya eklenince açılır,
    planlamadan kaldırılınca eksik yetkiyi söyleyen 403 döner."""
    path = "/api/v1/coding/suggest/masterdata.material/"
    depo = make_user(DEPO)
    assert api(depo).get(path).status_code == 403
    assert api(override(depo, CARDS.key, CHANGE, "grant")).get(path).status_code == 200

    planner = make_user(PLANLAMA)
    assert api(planner).get(path).status_code == 200
    refused = api(override(planner, CARDS.key, CHANGE)).get(path)
    assert refused.status_code == 403
    assert refused.json()["detail"] == SUGGEST_DENIED
    assert refused.json()["required"] == [{"key": CARDS.key, "level": CHANGE}]
