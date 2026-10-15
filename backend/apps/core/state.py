"""Durum makinesi yardımcısı.

Kullanım (belgenin kendi `state.py` dosyasında):

    class ProductionOrderStateMachine(StateMachine):
        name = "production_order"
        transitions = {
            "DRAFT": ["APPROVED", "CANCELLED"],
            "APPROVED": ["IN_PROGRESS", "CANCELLED"],
            "IN_PROGRESS": ["COMPLETED"],
        }
        labels = {"DRAFT": "Taslak", "APPROVED": "Onaylandı", ...}

    production_order_states = ProductionOrderStateMachine()

Geçiş, `core.services.transition_status(...)` ile yapılır; o fonksiyon kontrolü, denetim kaydını
ve olay yayınını birlikte yürütür.
"""

from collections.abc import Iterable, Mapping

from apps.core.exceptions import BusinessRuleError


class StateMachine:
    """İzinli durum geçişleri tablosu."""

    name: str = ""
    transitions: Mapping[str, Iterable[str]] = {}
    labels: Mapping[str, str] = {}
    initial: str | None = None

    def __init__(
        self,
        name: str | None = None,
        transitions: Mapping[str, Iterable[str]] | None = None,
        labels: Mapping[str, str] | None = None,
        initial: str | None = None,
    ) -> None:
        self.name = name if name is not None else self.name
        source = transitions if transitions is not None else self.transitions
        self._transitions: dict[str, frozenset[str]] = {
            state: frozenset(targets) for state, targets in source.items()
        }
        self.labels = dict(labels if labels is not None else self.labels)
        self.initial = initial if initial is not None else self.initial
        if not self.name:
            raise ValueError("Durum makinesinin adı (name) zorunludur.")
        if not self._transitions:
            raise ValueError("Durum makinesinde en az bir geçiş tanımlanmalıdır.")
        if self.initial is None:
            self.initial = next(iter(self._transitions))
        elif self.initial not in self.states:
            raise ValueError(f"Başlangıç durumu tanımlı değil: {self.initial}")

    @property
    def states(self) -> frozenset[str]:
        """Tablodaki tüm durumlar (çıkışı olmayan son durumlar dahil)."""
        targets = (t for ts in self._transitions.values() for t in ts)
        return frozenset(self._transitions).union(targets)

    def label(self, state: str) -> str:
        """Durumun kullanıcıya görünen adı."""
        return self.labels.get(state, state)

    def allowed_transitions(self, from_state: str) -> list[str]:
        """Verilen durumdan gidilebilecek durumlar, alfabetik sıralı."""
        return sorted(self._transitions.get(from_state, ()))

    def can_transition(self, from_state: str, to_state: str) -> bool:
        return to_state in self._transitions.get(from_state, ())

    def assert_can_transition(self, from_state: str, to_state: str) -> None:
        """Geçiş izinli değilse `BusinessRuleError("invalid_transition")` fırlatır."""
        if not self.can_transition(from_state, to_state):
            raise BusinessRuleError(
                "invalid_transition",
                f"“{self.label(from_state)}” durumundan “{self.label(to_state)}” "
                "durumuna geçilemez.",
            )

    def event_name(self, to_state: str) -> str:
        """Geçiş olayının adı: `<makine_adı>.<yeni_durum>` (küçük harf)."""
        return f"{self.name}.{to_state.lower()}"
