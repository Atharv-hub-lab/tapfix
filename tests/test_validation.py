import copy
import math

import pytest

from app.catalog import DUMMY_URI
from app.config import ValidationConfig
from app.plan import ActionDraft, StepGroupDraft, build_goal_dict
from app.validation import (
    BAD_ACTION_NAME, BAD_DESCRIPTION, BAD_GOAL, BAD_SCORE, BAD_STEP, BAD_TITLE, CRITICAL_NOT_LAST,
    DEEPLINK_MISMATCH, DUMMY_DEEPLINK, EMPTY_PLAN, EXTERNAL_URL, INVALID_CATEGORY, MALFORMED,
    MANUAL_WITH_DEEPLINK, MISSING_FIELD, ORPHAN_VALIDATION, UNKNOWN_DEEPLINK, UNKNOWN_VALIDATION_DEEPLINK,
    UNSUPPORTED_FIELD, URL_LEAK, VALIDATION_MISMATCH, validate_goal, validate_no_match, validate_response,
)

GOAL_TEXT = "Follow these steps to perform this Screen Damage Troubleshooting"


def entry_named(catalog, message):
    return next(e for e in catalog.real_entries if e.message == message)


def good_goal(catalog):
    """A fully valid goal, built from real catalog entries."""
    backup = entry_named(catalog, "Enable Back up data (Samsung Cloud)")
    drafts = [
        ActionDraft("Back Up Phone Data", "It will back up your data", "auto",
                    [StepGroupDraft(["Navigate to and open Settings.", "Tap on Accounts and backup.", "Select Back up data."], backup.id)]),
        ActionDraft("Visit Service Center", "It will help you find repair", "manual",
                    [StepGroupDraft(["Visit an authorized Samsung Service Center."])]),
        ActionDraft("Reset Device Settings", "It will restore default device settings", "critical",
                    [StepGroupDraft(["Open Settings.", "Tap on Reset."])]),
    ]
    return build_goal_dict(GOAL_TEXT, "Screen display damage", 0.9, drafts, catalog)


def broken(catalog, change):
    goal = copy.deepcopy(good_goal(catalog))
    change(goal)
    return goal


def codes(catalog, change, config=None):
    return validate_goal(broken(catalog, change), catalog, config).codes


def auto_group(goal):
    return goal["actions"][0]["stepGroups"][0]


# ---------------- a valid plan ----------------
def test_valid_plan_is_accepted_and_returned_as_a_trusted_goal(catalog):
    result = validate_goal(good_goal(catalog), catalog)
    assert result.ok and result.issues == ()
    goal = result.goals[0]
    assert goal.title == "Screen display damage" and [a.category.value for a in goal.actions] == ["auto", "manual", "critical"]


def test_rejected_plan_returns_no_trusted_goal(catalog):
    result = validate_goal(broken(catalog, lambda g: g.pop("title")), catalog)
    assert not result.ok and result.goals == ()


def test_all_problems_are_reported_not_just_the_first(catalog):
    def wreck(g):
        g["title"] = "x"
        g["score"] = 5
        g["actions"][0]["category"] = "standard"
    assert {BAD_TITLE, BAD_SCORE, INVALID_CATEGORY} <= codes(catalog, wreck)


# ---------------- required fields and malformed input ----------------
@pytest.mark.parametrize("field", ["goal", "title", "actions", "score"])
def test_missing_goal_field(catalog, field):
    assert MISSING_FIELD in codes(catalog, lambda g: g.pop(field))


@pytest.mark.parametrize("field", ["actionName", "description", "stepGroups", "category"])
def test_missing_action_field(catalog, field):
    assert MISSING_FIELD in codes(catalog, lambda g: g["actions"][0].pop(field))


def test_missing_steps(catalog):
    assert MISSING_FIELD in codes(catalog, lambda g: auto_group(g).pop("steps"))


@pytest.mark.parametrize("junk", ["nope", None, [], 5, 3.5, True])
def test_goal_that_is_not_an_object_is_rejected(catalog, junk):
    result = validate_goal(junk, catalog)
    assert not result.ok and MALFORMED in result.codes


@pytest.mark.parametrize("junk", [None, "x", 5, {}])
def test_actions_that_are_not_a_list_are_malformed(catalog, junk):
    assert MALFORMED in codes(catalog, lambda g: g.update(actions=junk))


def test_empty_plans_are_rejected(catalog):
    assert EMPTY_PLAN in codes(catalog, lambda g: g.update(actions=[]))
    assert EMPTY_PLAN in codes(catalog, lambda g: g["actions"][0].update(stepGroups=[]))
    assert EMPTY_PLAN in codes(catalog, lambda g: auto_group(g).update(steps=[]))


@pytest.mark.parametrize("junk", ["text", None, 7, ["x"]])
def test_action_and_step_group_must_be_objects(catalog, junk):
    assert MALFORMED in codes(catalog, lambda g: g["actions"].__setitem__(0, junk))
    assert MALFORMED in codes(catalog, lambda g: g["actions"][0]["stepGroups"].__setitem__(0, junk))


@pytest.mark.parametrize("steps", [[""], ["  "], [5], [None], ["ok", ""]])
def test_invalid_steps_are_rejected(catalog, steps):
    assert BAD_STEP in codes(catalog, lambda g: auto_group(g).update(steps=steps))


# ---------------- unsupported fields ----------------
def test_unsupported_fields_are_rejected_at_every_level(catalog):
    assert UNSUPPORTED_FIELD in codes(catalog, lambda g: g.update(extra="x"))
    assert UNSUPPORTED_FIELD in codes(catalog, lambda g: g["actions"][0].update(extra="x"))
    assert UNSUPPORTED_FIELD in codes(catalog, lambda g: auto_group(g).update(extra="x"))
    assert UNSUPPORTED_FIELD in codes(catalog, lambda g: auto_group(g)["actionableDeeplink"].update(extra="x"))
    assert UNSUPPORTED_FIELD in codes(catalog, lambda g: auto_group(g)["validationDeeplink"].update(extra="x"))


# ---------------- text rules ----------------
@pytest.mark.parametrize("text", [
    "Follow these steps", "Follow these steps to perform this Troubleshooting", "follow these steps to perform this Screen Troubleshooting",
    GOAL_TEXT + ".", " " + GOAL_TEXT, "Follow these steps to perform this Screen Repair", 5, None,
])
def test_bad_goal_text(catalog, text):
    assert BAD_GOAL in codes(catalog, lambda g: g.update(goal=text))


def test_goal_may_end_in_configuration(catalog):
    goal = broken(catalog, lambda g: g.update(goal="Follow these steps to perform this Display Configuration"))
    assert validate_goal(goal, catalog).ok


@pytest.mark.parametrize("title", ["Screen", "Screen display damage today", "screen display damage", "", 5, None])
def test_bad_title(catalog, title):
    assert BAD_TITLE in codes(catalog, lambda g: g.update(title=title))


@pytest.mark.parametrize("score", [1.5, -0.1, True, False, math.nan, math.inf, "0.9", None, [0.9]])
def test_bad_score(catalog, score):
    assert BAD_SCORE in codes(catalog, lambda g: g.update(score=score))


@pytest.mark.parametrize("score", [0, 0.0, 1, 1.0, 0.5])
def test_score_boundaries_are_accepted(catalog, score):
    assert validate_goal(broken(catalog, lambda g: g.update(score=score)), catalog).ok


@pytest.mark.parametrize("name", ["back up phone data", "", "   ", 5, None, "Back up Phone Data"])
def test_bad_action_name(catalog, name):
    assert BAD_ACTION_NAME in codes(catalog, lambda g: g["actions"][0].update(actionName=name))


def test_title_case_allows_small_joining_words_in_the_middle(catalog):
    goal = broken(catalog, lambda g: g["actions"][0].update(actionName="Turn On Bluetooth and Wi-Fi in Settings"))
    assert validate_goal(goal, catalog).ok


@pytest.mark.parametrize("text", [
    "It will help", "It will help you back up all your data now", "Helps you back up data today please",
    "it will back up your data", "It would back up your data", 5, None, "",
])
def test_bad_description(catalog, text):
    assert BAD_DESCRIPTION in codes(catalog, lambda g: g["actions"][0].update(description=text))


@pytest.mark.parametrize("text", ["It will back up data", "It will back up your data now"])  # 5 and 7 words
def test_description_boundaries_are_accepted(catalog, text):
    assert validate_goal(broken(catalog, lambda g: g["actions"][0].update(description=text)), catalog).ok


def test_word_limits_are_configurable(catalog):
    long_text = "It will back up all of your personal data safely"  # 10 words
    goal = broken(catalog, lambda g: g["actions"][0].update(description=long_text))
    assert BAD_DESCRIPTION in validate_goal(goal, catalog).codes
    assert validate_goal(goal, catalog, ValidationConfig(description_max_words=12)).ok


# ---------------- categories and ordering ----------------
@pytest.mark.parametrize("category", ["standard", "AUTO", "Critical", "", None, 1, ["auto"]])
def test_invalid_category(catalog, category):
    assert INVALID_CATEGORY in codes(catalog, lambda g: g["actions"][0].update(category=category))


def test_manual_action_must_not_carry_a_deeplink(catalog):
    assert MANUAL_WITH_DEEPLINK in codes(catalog, lambda g: g["actions"][0].update(category="manual"))


def test_critical_action_must_be_last(catalog):
    def reorder(g):
        g["actions"] = [g["actions"][2], g["actions"][0], g["actions"][1]]
    assert CRITICAL_NOT_LAST in codes(catalog, reorder)


def test_sequenced_plans_are_accepted(catalog):
    assert CRITICAL_NOT_LAST not in codes(catalog, lambda g: None)


# ---------------- no URLs anywhere ----------------
@pytest.mark.parametrize("text", [
    "Visit https://www.samsung.com/support", "Go to http://example.com", "Open www.samsung.com", "Visit samsung.com/support",
    "see [click here](x)", "Use bixby://masked/act/abcdef", "Try ftp://files.example", "Email help at support.org",
])
def test_urls_in_any_text_field_are_rejected(catalog, text):
    assert URL_LEAK in codes(catalog, lambda g: auto_group(g)["steps"].append(text))
    assert URL_LEAK in codes(catalog, lambda g: g["actions"][0].update(description="It will " + text))
    assert URL_LEAK in codes(catalog, lambda g: g["actions"][0].update(actionName="Open " + text))
    assert URL_LEAK in codes(catalog, lambda g: g.update(title=text))
    assert URL_LEAK in codes(catalog, lambda g: g.update(goal=GOAL_TEXT.replace("Screen Damage", text)))


def test_ordinary_text_with_dots_is_not_a_url(catalog):
    goal = broken(catalog, lambda g: auto_group(g)["steps"].append("Tap Settings. Then tap Display, e.g. the top item."))
    assert URL_LEAK not in validate_goal(goal, catalog).codes


# ---------------- closed-world deeplinks ----------------
def with_uri(uri):
    return lambda g: auto_group(g)["actionableDeeplink"].update(deeplink=uri)


def test_exact_catalog_uri_is_accepted(catalog):
    assert validate_goal(good_goal(catalog), catalog).ok


def test_uri_with_one_character_changed_is_rejected(catalog):
    real = auto_group(good_goal(catalog))["actionableDeeplink"]["deeplink"]
    changed = real[:-1] + ("0" if real[-1] != "0" else "1")
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri(changed))


def test_uri_with_different_casing_is_rejected(catalog):
    real = auto_group(good_goal(catalog))["actionableDeeplink"]["deeplink"]
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri(real.upper()))
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri(real.replace("bixby", "Bixby")))


def test_uri_with_leading_or_trailing_whitespace_is_rejected(catalog):
    real = auto_group(good_goal(catalog))["actionableDeeplink"]["deeplink"]
    for padded in (real + " ", " " + real, real + "\n", "\t" + real):
        assert UNKNOWN_DEEPLINK in codes(catalog, with_uri(padded))


def test_uri_not_in_the_catalog_is_rejected(catalog):
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri("bixby://masked/act/0000000000"))
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri("bixby://masked/val/" + "a" * 10))
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri(""))


@pytest.mark.parametrize("url", ["http://evil.example/pwn", "https://evil.example/pwn", "https://www.samsung.com/support", "www.samsung.com"])
def test_external_urls_are_rejected(catalog, url):
    assert EXTERNAL_URL in codes(catalog, with_uri(url))


@pytest.mark.parametrize("fake", ["bixby://masked/act/deadbeef00", "settings://display", "bixby://generated/act/1234567890"])
def test_generated_fake_uris_are_rejected(catalog, fake):
    assert UNKNOWN_DEEPLINK in codes(catalog, with_uri(fake))


@pytest.mark.parametrize("junk", [None, 5, ["x"], {"a": 1}])
def test_deeplink_that_is_not_a_string_is_malformed(catalog, junk):
    assert MALFORMED in codes(catalog, with_uri(junk))


def test_dummy_placeholder_is_never_allowed(catalog):
    assert DUMMY_DEEPLINK in codes(catalog, with_uri(DUMMY_URI))
    dummy_group = lambda g: g["actions"][0]["stepGroups"][0].update(
        actionableDeeplink={"deeplink": DUMMY_URI, "description": "Open display settings page", "message": "Choose display settings"},
        validationDeeplink=None)
    assert DUMMY_DEEPLINK in codes(catalog, dummy_group)


def test_deeplink_object_must_be_a_verbatim_copy_of_one_catalog_entry(catalog):
    other = entry_named(catalog, "Enable Dwell Action")
    assert DEEPLINK_MISMATCH in codes(catalog, lambda g: auto_group(g)["actionableDeeplink"].update(description="Opens something else"))
    assert DEEPLINK_MISMATCH in codes(catalog, lambda g: auto_group(g)["actionableDeeplink"].update(message="Other message"))
    assert DEEPLINK_MISMATCH in codes(catalog, lambda g: auto_group(g)["actionableDeeplink"].update(originalType="offURL"))
    assert DEEPLINK_MISMATCH in codes(catalog, lambda g: auto_group(g)["actionableDeeplink"].update(classes={"a": "b"}))
    assert DEEPLINK_MISMATCH in codes(catalog, lambda g: auto_group(g)["actionableDeeplink"].pop("message"))
    # URI of one entry glued to the text of another entry
    assert DEEPLINK_MISMATCH in codes(catalog, with_uri(other.uri))


def test_actionable_deeplink_must_be_an_object_or_null(catalog):
    assert MALFORMED in codes(catalog, lambda g: auto_group(g).update(actionableDeeplink="bixby://masked/act/x"))


# ---------------- validation deeplinks ----------------
def test_validation_deeplink_must_exist_in_the_catalog(catalog):
    assert UNKNOWN_VALIDATION_DEEPLINK in codes(catalog, lambda g: auto_group(g)["validationDeeplink"].update(deeplink="bixby://masked/val/0000000000"))
    assert UNKNOWN_VALIDATION_DEEPLINK in codes(catalog, lambda g: auto_group(g)["validationDeeplink"].update(deeplink="https://evil.example"))


def test_validation_deeplink_must_belong_to_the_same_entry(catalog):
    other = catalog.to_validation_deeplink(entry_named(catalog, "Enable Dwell Action")).model_dump(mode="json", exclude_none=True)
    assert VALIDATION_MISMATCH in codes(catalog, lambda g: auto_group(g).update(validationDeeplink=other))
    assert VALIDATION_MISMATCH in codes(catalog, lambda g: auto_group(g)["validationDeeplink"].update(value="False"))
    assert VALIDATION_MISMATCH in codes(catalog, lambda g: auto_group(g)["validationDeeplink"].pop("condition"))


def test_validation_deeplink_without_an_actionable_deeplink_is_rejected(catalog):
    assert ORPHAN_VALIDATION in codes(catalog, lambda g: auto_group(g).update(actionableDeeplink=None))


def test_validation_deeplink_of_the_wrong_type_is_malformed(catalog):
    assert MALFORMED in codes(catalog, lambda g: auto_group(g).update(validationDeeplink="x"))


def test_validation_deeplink_may_be_null(catalog):
    assert validate_goal(broken(catalog, lambda g: auto_group(g).update(validationDeeplink=None)), catalog).ok


# ---------------- whole responses and the no_match shape ----------------
def test_valid_response_is_accepted(catalog):
    result = validate_response({"contexts": [good_goal(catalog)]}, catalog)
    assert result.ok and len(result.goals) == 1


@pytest.mark.parametrize("response", [{"contexts": []}, {}, {"contexts": None}, {"contexts": "x"}, [], None, "x"])
def test_invalid_or_empty_responses_are_not_valid_plans(catalog, response):
    assert not validate_response(response, catalog).ok


def test_response_with_extra_fields_is_rejected(catalog):
    assert UNSUPPORTED_FIELD in validate_response({"contexts": [good_goal(catalog)], "fallback": "no_match"}, catalog).codes


def test_response_reports_the_failing_goal_position(catalog):
    bad = broken(catalog, lambda g: g.pop("title"))
    result = validate_response({"contexts": [good_goal(catalog), bad]}, catalog)
    assert any(issue.path.startswith("contexts[1]") for issue in result.issues)


@pytest.mark.parametrize("value, expected", [
    ({"contexts": []}, True), ({"contexts": [], "fallback": "no_match"}, False), ({"contexts": [{}]}, False),
    ({}, False), ([], False), (None, False), ({"contexts": None}, False),
])
def test_no_match_shape_is_exactly_empty_contexts(value, expected):
    assert validate_no_match(value) is expected


# ---------------- Samsung's own sample ----------------
def test_samsung_sample_fails_only_the_description_length_rule(catalog, sample_output):
    # AMBIGUITY IN SAMSUNG'S DATA: the guide says descriptions are 5-7 words, but the sample's are 9 and 12.
    # We follow the guide by default and record the conflict here instead of inventing a rule.
    result = validate_goal(sample_output["response"]["contexts"][0], catalog)
    assert not result.ok
    assert result.codes == {BAD_DESCRIPTION}
    assert [issue.path for issue in result.issues] == ["goal.actions[0].description", "goal.actions[1].description"]


def test_samsung_sample_passes_every_other_rule_when_the_length_limit_is_relaxed(catalog, sample_output):
    relaxed = ValidationConfig(description_max_words=12)
    assert validate_goal(sample_output["response"]["contexts"][0], catalog, relaxed).ok
    assert validate_response(sample_output["response"], catalog, relaxed).ok


# ---------------- robustness: garbage never crashes, always rejects ----------------
JUNK = [None, 0, -1, 3.14, True, "", "   ", "x" * 10000, [], {}, [[]], {"a": {"b": 1}}, math.nan, b"bytes"]


def test_garbage_in_every_position_is_rejected_without_crashing(catalog):
    setters = [
        lambda g, v: g.update(goal=v), lambda g, v: g.update(title=v), lambda g, v: g.update(score=v), lambda g, v: g.update(actions=v),
        lambda g, v: g["actions"][0].update(actionName=v), lambda g, v: g["actions"][0].update(description=v),
        lambda g, v: g["actions"][0].update(category=v), lambda g, v: g["actions"][0].update(stepGroups=v),
        lambda g, v: auto_group(g).update(steps=v), lambda g, v: auto_group(g).update(actionableDeeplink=v),
        lambda g, v: auto_group(g).update(validationDeeplink=v), lambda g, v: auto_group(g)["actionableDeeplink"].update(deeplink=v),
        lambda g, v: auto_group(g)["validationDeeplink"].update(deeplink=v),
    ]
    for setter in setters:
        for value in JUNK:
            goal = copy.deepcopy(good_goal(catalog))
            setter(goal, value)
            result = validate_goal(goal, catalog)  # must not raise
            if result.ok:  # only harmless replacements (e.g. an unchanged-equivalent value) may pass
                assert result.goals and goal["title"] and isinstance(goal["score"], (int, float))
