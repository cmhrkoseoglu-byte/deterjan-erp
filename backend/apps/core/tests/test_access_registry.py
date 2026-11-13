"""Yetki kataloğu kaydı: tanım hataları, katalog çıktısı ve bütünlük denetimi."""

from collections.abc import Iterator

import pytest

from apps.core import access
from apps.core.access import (
    ALL,
    ANY_ROLE,
    APPROVE,
    CHANGE,
    EVERYONE,
    READ,
    VIEW,
    Kind,
    ReadScope,
    grant,
    register_field_openers,
    register_module,
    register_open_records,
    register_readers,
    register_section,
    temporary_catalog,
)
from apps.core.roles import DEPO, PLANLAMA, YONETIM


@pytest.fixture
def demo() -> Iterator[None]:
    with temporary_catalog():
        register_module("demo", "Deneme", order=999)
        yield


def test_section_kind_and_scope_defaults(demo: None) -> None:
    orders = register_section("demo.orders", "Emirler", levels=(VIEW, CHANGE))
    block = register_section("demo.block", "Bloke", levels=(APPROVE,))

    assert orders.kind is Kind.SECTION
    assert orders.read is ReadScope.VIEW
    assert orders.module == "demo"
    assert block.kind is Kind.ACTION
    assert access.section("demo.orders") is orders
    assert [item.key for item in access.sections("demo")] == ["demo.orders", "demo.block"]


@pytest.mark.parametrize(
    ("key", "options", "message"),
    [
        ("demo", {"levels": (VIEW,)}, "Geçersiz bölüm anahtarı"),
        ("other.orders", {"levels": (VIEW,)}, "modül kayıtlı değil"),
        ("demo.orders", {"levels": ()}, "geçersiz düzeyler"),
        ("demo.orders", {"levels": (VIEW, VIEW)}, "tekrarlandı"),
        ("demo.orders", {"levels": ("edit",)}, "geçersiz düzeyler"),
        ("demo.orders", {"levels": (VIEW,), "help": {CHANGE: "x"}}, "açıklaması verilen düzey"),
        ("demo.orders", {"levels": (VIEW,), "requires": {CHANGE: []}}, "ön koşul verilen düzey"),
        (
            "demo.orders",
            {"levels": (VIEW,), "requires": {ALL: [("demo.orders", VIEW)]}},
            "kendisinin ön koşulu",
        ),
        ("demo.orders", {"levels": (VIEW,), "restricted_to_role": "admin"}, "tanımsız rol"),
        ("demo.orders", {"levels": (VIEW,), "admin_only": (CHANGE,)}, "admin_only düzeyi"),
        (
            "demo.orders",
            {"levels": (VIEW,), "admin_only": (VIEW,), "locked": (VIEW,)},
            "hem yalnız admin hem kilitli",
        ),
        ("demo.block", {"levels": (APPROVE,), "read": ReadScope.OPEN}, "okuma kapsamı"),
        ("demo.price", {"levels": (VIEW, CHANGE), "kind": Kind.SENSITIVE}, "tek düzeyi Görür"),
        ("demo.screen", {"levels": (CHANGE,), "kind": Kind.SECTION}, "Görür düzeyi olmalıdır"),
    ],
)
def test_invalid_section_definitions_are_rejected(
    demo: None, key: str, options: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        register_section(key, "Deneme", **options)  # type: ignore[arg-type]


def test_duplicate_section_and_module_are_rejected(demo: None) -> None:
    register_section("demo.orders", "Emirler", levels=(VIEW,))
    with pytest.raises(ValueError, match="iki kez"):
        register_section("demo.orders", "Emirler", levels=(VIEW,))
    with pytest.raises(ValueError, match="iki kez"):
        register_module("demo", "Deneme", order=1)


def test_grant_rules(demo: None) -> None:
    orders = register_section("demo.orders", "Emirler", levels=(VIEW, CHANGE), admin_only=(CHANGE,))
    secret = register_section("demo.secret", "Gizli", levels=(VIEW,), restricted_to_role=YONETIM)
    records = register_open_records("demo")

    grant(DEPO, orders, VIEW)
    grant(YONETIM, secret, VIEW)
    assert ("demo.orders", VIEW) in access.package(DEPO)
    assert (records.key, READ) in access.package(EVERYONE)

    with pytest.raises(ValueError, match="Tanımsız paket sahibi"):
        grant("admin", orders, VIEW)
    with pytest.raises(ValueError, match="yalnız sistem yöneticisine"):
        grant(DEPO, orders, CHANGE)
    with pytest.raises(ValueError, match="düzey bölümde yok"):
        grant(DEPO, orders, APPROVE)
    with pytest.raises(ValueError, match="KVKK"):
        grant(PLANLAMA, secret, VIEW)
    with pytest.raises(ValueError, match="pakete yazılmaz"):
        grant(EVERYONE, records, READ)
    with pytest.raises(ValueError, match="en az bir düzey"):
        grant(ANY_ROLE, orders)


def test_open_records_row(demo: None) -> None:
    records = register_open_records("demo")

    assert records.key == "demo.open_records"
    assert records.kind is Kind.OPEN_RECORDS
    assert records.levels == (READ,)
    assert access.open_records_section("demo") is records


def test_readers_accumulate_without_duplicates(demo: None) -> None:
    orders = register_section("demo.orders", "Emirler", levels=(VIEW,))
    prep = register_section("demo.prep", "Hazırlama", levels=(VIEW,))

    register_readers("demo.order", orders)
    register_readers("demo.order", prep, orders)

    assert access.readers("demo.order") == (orders, prep)
    with pytest.raises(ValueError, match="en az bir bölüm"):
        register_readers("demo.empty")


def test_field_openers(demo: None) -> None:
    orders = register_section("demo.orders", "Emirler", levels=(VIEW,))
    prep = register_section("demo.prep", "Hazırlama", levels=(VIEW,))
    register_open_records("demo")

    register_field_openers("demo.customer.contact", orders)
    register_field_openers("demo.customer.contact", prep, orders)

    group = "demo.customer.contact"
    assert access.field_openers(group) == (orders, prep)
    assert access.has_field_group(group)
    assert group in access.field_opener_names()
    assert access.readers(group) == ()
    assert access.catalog()["field_openers"][group] == ["demo.orders", "demo.prep"]
    assert not [error for error in access.validate() if group in error]
    with pytest.raises(ValueError, match="en az bir bölüm"):
        register_field_openers("demo.empty")


def test_registration_order_does_not_change_output_or_hash(demo: None) -> None:
    orders = register_section("demo.orders", "Emirler", levels=(VIEW,))
    prep = register_section("demo.prep", "Hazırlama", levels=(VIEW,))

    with temporary_catalog():
        register_readers("demo.order", orders)
        register_readers("demo.order", prep)
        register_field_openers("demo.customer.contact", orders, prep)
        forward = access.catalog_hash()
    with temporary_catalog():
        register_readers("demo.order", prep)
        register_readers("demo.order", orders)
        register_field_openers("demo.customer.contact", prep)
        register_field_openers("demo.customer.contact", orders)
        assert access.readers("demo.order") == (orders, prep)
        assert access.field_openers("demo.customer.contact") == (orders, prep)
        assert access.catalog()["readers"]["demo.order"] == ["demo.orders", "demo.prep"]
        backward = access.catalog_hash()

    assert forward == backward


def test_requirements_per_level(demo: None) -> None:
    prices = register_section("demo.prices", "Fiyat", levels=(VIEW,), kind=Kind.SENSITIVE)
    orders = register_section(
        "demo.orders",
        "Emirler",
        levels=(VIEW, CHANGE, APPROVE),
        requires={CHANGE: [(prices, VIEW)], ALL: [("demo.prices", VIEW)]},
    )

    assert orders.requirements(VIEW) == (("demo.prices", VIEW),)
    assert orders.requirements(CHANGE) == (("demo.prices", VIEW), ("demo.prices", VIEW))


def test_catalog_output_and_hash_follow_packages(demo: None) -> None:
    orders = register_section(
        "demo.orders", "Emirler", levels=(VIEW, CHANGE), help={CHANGE: "Değiştirir"}
    )
    grant(DEPO, orders, VIEW)
    before = access.catalog_hash()
    data = access.catalog()

    module = next(item for item in data["modules"] if item["key"] == "demo")
    assert module["sections"][0]["help"] == {CHANGE: "Değiştirir"}
    assert data["packages"][DEPO]["demo.orders"] == "v"

    grant(DEPO, orders, CHANGE)
    assert access.catalog()["packages"][DEPO]["demo.orders"] == "vc"
    assert access.catalog_hash() != before


def test_validate_reports_integrity_errors(demo: None) -> None:
    register_section("demo.open", "Açık", levels=(VIEW,), read=ReadScope.OPEN)
    register_section(
        "demo.needs", "İster", levels=(VIEW,), requires={ALL: [("demo.missing", VIEW)]}
    )
    register_section("demo.first", "Bir", levels=(VIEW,), requires={ALL: [("demo.second", VIEW)]})
    register_section("demo.second", "İki", levels=(VIEW,), requires={ALL: [("demo.first", VIEW)]})
    register_module("empty", "Boş", order=998)
    register_readers("demo.record", "demo.unknown")

    errors = access.validate()

    assert any("demo.open: açık okumalı bölümün modülünde" in error for error in errors)
    assert any("demo.needs: ön koşul tanımsız bölüm (demo.missing)" in error for error in errors)
    assert any(error.startswith("Döngülü ön koşul") for error in errors)
    assert "empty: modülde bölüm yok." in errors
    assert "demo.record: okuyan bölüm tanımsız (demo.unknown)." in errors


def test_validate_reports_field_opener_errors(demo: None) -> None:
    register_section("demo.block", "Bloke", levels=(APPROVE,))
    register_field_openers("demo.customer.contact", "demo.block", "demo.unknown")

    errors = access.validate()

    assert "demo.customer.contact: alan grubunun modülünde Açık kayıtlar satırı yok." in errors
    assert "demo.customer.contact: alanları açan bölüm tanımsız (demo.unknown)." in errors
    assert "demo.customer.contact: alanları açan bölümün Görür düzeyi yok (demo.block)." in errors


def test_real_catalog_is_valid() -> None:
    assert access.validate() == []


def test_temporary_catalog_restores_state() -> None:
    before = access.catalog_hash()
    with temporary_catalog():
        register_module("demo", "Deneme", order=999)
        grant(DEPO, register_section("demo.orders", "Emirler", levels=(VIEW,)), VIEW)
        assert access.has_section("demo.orders")

    assert not access.has_section("demo.orders")
    assert access.catalog_hash() == before


def test_unknown_section_lookup_raises() -> None:
    with pytest.raises(KeyError, match="Tanımsız yetki bölümü"):
        access.section("nope.nothing")
