"""Reçete sürümü durum makinesi.

    DRAFT ─► APPROVED ─► OBSOLETE

Yeni sürüm onaylanınca reçetenin önceki onaylı sürümü otomatik olarak OBSOLETE olur.
Geçişler `recipes.services` içinden yapılır; her geçiş `recipe_version.<durum>` olayı yayınlar.
"""

from apps.core.state import StateMachine


class RecipeVersionStateMachine(StateMachine):
    name = "recipe_version"
    initial = "DRAFT"
    transitions = {
        "DRAFT": ["APPROVED"],
        "APPROVED": ["OBSOLETE"],
        "OBSOLETE": [],
    }
    labels = {"DRAFT": "Taslak", "APPROVED": "Onaylı", "OBSOLETE": "Geçersiz"}


recipe_version_states = RecipeVersionStateMachine()
