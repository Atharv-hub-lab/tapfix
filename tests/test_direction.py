import pytest

from app.direction import (
    Direction,
    direction_twin_key,
    directions_conflict,
    entry_direction,
    explain_direction,
    resolve_direction,
    strip_direction_words,
)
from tests.helpers import by_message, make_catalog


# ---------------- resolving text ----------------
@pytest.mark.parametrize(
    "text",
    ["enable X", "Enable this", "turn on X", "Turn ON the setting", "activate it", "switch on wifi",
     "switch this on", "turn adaptive brightness on", "Please enable the toggle"],
)
def test_on_phrases_resolve_to_on(text):
    assert resolve_direction(text) == Direction.ON


@pytest.mark.parametrize(
    "text",
    ["disable X", "Disable this", "turn off X", "Turn OFF the setting", "deactivate it", "switch off wifi",
     "switch this off", "turn the phone off", "Please disable the toggle"],
)
def test_off_phrases_resolve_to_off(text):
    assert resolve_direction(text) == Direction.OFF


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        None,
        42,
        "Tap on Display.",
        "Select Back up data to secure your personal files.",
        "Switch to the Display tab on the left",  # "switch ... on" across a preposition is not a direction
    ],
)
def test_no_clear_direction_is_unknown_never_a_guess(text):
    assert resolve_direction(text) == Direction.UNKNOWN


@pytest.mark.parametrize(
    "text",
    ["do not turn on battery saver", "never disable it", "don't enable this", "without turning off wifi"],
)
def test_negated_direction_is_unknown(text):
    assert resolve_direction(text) == Direction.UNKNOWN


@pytest.mark.parametrize(
    "text",
    ["enable or disable Dwell action", "turn it off and on again", "turn off then back on",
     "turn off wifi and turn on airplane mode"],
)
def test_conflicting_directions_are_unknown(text):
    assert resolve_direction(text) == Direction.UNKNOWN


def test_direction_after_to_is_ignored_because_it_may_be_part_of_a_setting_name():
    # "Double tap to turn off screen" is a setting NAME, not a request to turn something off.
    assert resolve_direction("Double tap to turn off screen") == Direction.UNKNOWN
    assert resolve_direction("Disable Double tap to turn off screen") == Direction.OFF


def test_explain_direction_gives_evidence():
    signal = explain_direction("Turn on Adaptive brightness")
    assert signal.direction == Direction.ON and signal.evidence == ("turn on",)
    assert explain_direction("hello").note == "no direction words"


def test_strip_direction_words_keeps_the_topic():
    assert strip_direction_words("turn off touch sensitivity") == "touch sensitivity"
    assert strip_direction_words("Enable Adaptive brightness") == "adaptive brightness"
    assert strip_direction_words("Tap on Display.") == "tap on display"
    assert strip_direction_words(None) == ""
    # a phrase after "to" is treated as part of the name and stays
    assert "turn off" in strip_direction_words("Double tap to turn off screen")


# ---------------- direction of catalog entries ----------------
def test_entry_direction_uses_catalog_metadata():
    catalog = make_catalog()
    assert entry_direction(by_message(catalog, "Enable Bluetooth")) == Direction.ON
    assert entry_direction(by_message(catalog, "Disable Bluetooth")) == Direction.OFF
    assert entry_direction(by_message(catalog, "View Display")) == Direction.UNKNOWN  # onClickURL
    assert entry_direction(by_message(catalog, "Adjust Brightness")) == Direction.UNKNOWN  # updateURL


def test_real_catalog_directions_follow_original_type(catalog):
    for entry in catalog.real_entries:
        if entry.original_type == "onURL":
            assert entry_direction(entry) == Direction.ON
        elif entry.original_type == "offURL":
            assert entry_direction(entry) == Direction.OFF
        elif entry.original_type in ("onClickURL", "updateURL"):
            assert entry_direction(entry) == Direction.UNKNOWN


def test_two_catalog_quirk_entries_use_their_validation_key(catalog):
    # DL-0294 / DL-0295 have originalType null but a validation key of exactly offURL / onURL.
    assert entry_direction(catalog.get_by_id("DL-0294")) == Direction.OFF
    assert entry_direction(catalog.get_by_id("DL-0295")) == Direction.ON


@pytest.mark.parametrize(
    "wanted, entry_dir, conflict",
    [
        (Direction.ON, Direction.OFF, True),
        (Direction.OFF, Direction.ON, True),
        (Direction.ON, Direction.ON, False),
        (Direction.OFF, Direction.OFF, False),
        (Direction.UNKNOWN, Direction.ON, False),
        (Direction.ON, Direction.UNKNOWN, False),
        (Direction.UNKNOWN, Direction.UNKNOWN, False),
    ],
)
def test_conflict_only_when_both_known_and_opposite(wanted, entry_dir, conflict):
    assert directions_conflict(wanted, entry_dir) is conflict


def test_twin_key_pairs_enable_and_disable_versions_only():
    catalog = make_catalog()
    on, off = by_message(catalog, "Enable Bluetooth"), by_message(catalog, "Disable Bluetooth")
    assert direction_twin_key(on) == direction_twin_key(off)
    assert direction_twin_key(on) != direction_twin_key(by_message(catalog, "Enable Touch sensitivity"))


def test_real_dwell_action_pair_are_twins(catalog):
    on = next(e for e in catalog.real_entries if e.message == "Enable Dwell Action")
    off = next(e for e in catalog.real_entries if e.message == "Disable Dwell Action")
    assert direction_twin_key(on) == direction_twin_key(off)
