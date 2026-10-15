import pytest

from apps.core.exceptions import BusinessRuleError
from apps.core.state import StateMachine
from apps.core.tests.testapp.state import sample_document_states as machine

ALLOWED = [
    ("DRAFT", "APPROVED"),
    ("DRAFT", "CANCELLED"),
    ("APPROVED", "DONE"),
    ("APPROVED", "CANCELLED"),
]


@pytest.mark.parametrize(("from_state", "to_state"), ALLOWED)
def test_allowed_transitions(from_state, to_state):
    assert machine.can_transition(from_state, to_state)
    machine.assert_can_transition(from_state, to_state)


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [("DRAFT", "DONE"), ("DONE", "DRAFT"), ("CANCELLED", "DRAFT"), ("DRAFT", "DRAFT")],
)
def test_forbidden_transition_raises_business_rule_error(from_state, to_state):
    assert not machine.can_transition(from_state, to_state)
    with pytest.raises(BusinessRuleError) as exc_info:
        machine.assert_can_transition(from_state, to_state)

    assert exc_info.value.code == "invalid_transition"
    assert "durumundan" in exc_info.value.message


def test_error_message_uses_turkish_labels():
    with pytest.raises(BusinessRuleError) as exc_info:
        machine.assert_can_transition("DONE", "DRAFT")

    assert "Tamamlandı" in exc_info.value.message
    assert "Taslak" in exc_info.value.message


def test_states_include_terminal_states():
    assert machine.states == {"DRAFT", "APPROVED", "DONE", "CANCELLED"}
    assert machine.initial == "DRAFT"
    assert machine.allowed_transitions("DRAFT") == ["APPROVED", "CANCELLED"]
    assert machine.allowed_transitions("CANCELLED") == []


def test_event_name():
    assert machine.event_name("APPROVED") == "sample_document.approved"


def test_machine_can_be_built_without_subclass():
    m = StateMachine(name="x", transitions={"A": ["B"]})

    assert m.can_transition("A", "B")
    assert not m.can_transition("B", "A")


def test_invalid_definitions_rejected():
    with pytest.raises(ValueError):
        StateMachine(transitions={"A": ["B"]})
    with pytest.raises(ValueError):
        StateMachine(name="x", transitions={})
    with pytest.raises(ValueError):
        StateMachine(name="x", transitions={"A": ["B"]}, initial="Z")
