"""Reçeteler: yetki bölümleri ve rol paketleri (docs/plan/kisi-yetkileri.md §3.2)."""

from apps.core.access import (
    APPROVE,
    CHANGE,
    VIEW,
    ReadScope,
    grant,
    register_module,
    register_open_records,
    register_section,
)
from apps.core.roles import LABORATUVAR, PLANLAMA

register_module("recipes", "Reçeteler", order=20)

RECIPES = register_section(
    "recipes.recipes",
    "Reçeteler ve sürümler",
    levels=(VIEW, CHANGE, APPROVE),
    help={
        VIEW: "Reçete kartı, sürümler, satırlar, adımlar ve ölçekleme.",
        CHANGE: "Reçete ve sürüm taslağı açar ve düzenler, Excel'den taslak alır, pasife alır.",
        APPROVE: "Reçete sürümünü onaylar.",
    },
    read=ReadScope.OPEN,
)
OPEN_RECORDS = register_open_records("recipes")

for role in (PLANLAMA, LABORATUVAR):
    grant(role, RECIPES, VIEW, CHANGE, APPROVE)
