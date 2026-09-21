import pytest

from app.sequencing import SequencingError, is_sequenced, sequence_actions
from app.schema import actionCategory


def act(name, category):
    return {"actionName": name, "category": category}


def names(actions):
    return [a["actionName"] for a in actions]


def test_critical_actions_go_last():
    plan = [act("Reset", "critical"), act("Toggle", "auto"), act("Clean", "manual")]
    assert names(sequence_actions(plan)) == ["Toggle", "Clean", "Reset"]


def test_source_order_is_preserved_inside_each_group():
    plan = [act("C1", "critical"), act("A1", "auto"), act("M1", "manual"), act("C2", "critical"), act("A2", "auto")]
    assert names(sequence_actions(plan)) == ["A1", "M1", "A2", "C1", "C2"]


def test_already_ordered_plan_is_unchanged():
    plan = [act("A", "auto"), act("M", "manual"), act("C", "critical")]
    assert names(sequence_actions(plan)) == ["A", "M", "C"]


def test_repeated_calls_give_identical_results():
    plan = [act("C", "critical"), act("A", "auto"), act("B", "auto")]
    first = names(sequence_actions(plan))
    assert names(sequence_actions(plan)) == first
    assert names(sequence_actions(list(sequence_actions(plan)))) == first  # idempotent


def test_input_is_not_modified():
    plan = [act("C", "critical"), act("A", "auto")]
    sequence_actions(plan)
    assert names(plan) == ["C", "A"]


def test_empty_plan_is_fine():
    assert sequence_actions([]) == []


@pytest.mark.parametrize("bad", ["reset", "AUTO", None, "", 5])
def test_unknown_or_missing_category_fails_closed(bad):
    with pytest.raises(SequencingError):
        sequence_actions([act("A", "auto"), act("X", bad)])


def test_missing_category_key_fails_closed():
    with pytest.raises(SequencingError):
        sequence_actions([{"actionName": "no category"}])


def test_schema_enum_categories_are_accepted():
    plan = [act("C", actionCategory.critical), act("A", actionCategory.auto)]
    assert names(sequence_actions(plan)) == ["A", "C"]


@pytest.mark.parametrize(
    "categories, expected",
    [
        (["auto", "manual", "critical"], True),
        (["auto", "critical", "critical"], True),
        (["critical", "auto"], False),
        (["auto", "critical", "manual"], False),
        ([], True),
        (["auto", "bogus"], False),
    ],
)
def test_is_sequenced(categories, expected):
    assert is_sequenced(categories) is expected
