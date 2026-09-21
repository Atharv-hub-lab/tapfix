import pytest

from app.config import ValidationConfig
from app.plan import (
    BUILD_ERROR,
    NO_MATCH_FALLBACK,
    SEQUENCING_ERROR,
    ActionDraft,
    PlanBuildError,
    StepGroupDraft,
    assemble_trusted_plan,
    build_goal_dict,
    no_match_response,
)
from app.validation import DEEPLINK_MISMATCH, BAD_DESCRIPTION, MANUAL_WITH_DEEPLINK, validate_no_match

GOAL_TEXT = "Follow these steps to perform this Screen Damage Troubleshooting"


def backup_entry(catalog):
    return next(e for e in catalog.real_entries if e.message == "Enable Back up data (Samsung Cloud)")


def drafts(catalog):
    return [
        ActionDraft("Reset Device Settings", "It will restore default device settings", "critical", [StepGroupDraft(["Open Settings.", "Tap on Reset."])]),
        ActionDraft("Back Up Phone Data", "It will back up your data", "auto", [StepGroupDraft(["Open Settings.", "Select Back up data."], backup_entry(catalog).id)]),
        ActionDraft("Visit Service Center", "It will help you find repair", "manual", [StepGroupDraft(["Visit an authorized Samsung Service Center."])]),
    ]


def assemble(catalog, drafts_=None, **overrides):
    args = dict(goal=GOAL_TEXT, title="Screen display damage", score=0.9)
    args.update(overrides)
    return assemble_trusted_plan(drafts=drafts_ if drafts_ is not None else drafts(catalog), catalog=catalog, **args)


def test_happy_path_returns_a_trusted_plan(catalog):
    plan = assemble(catalog)
    assert plan.ok and plan.issues == () and plan.goal is not None
    assert list(plan.response) == ["contexts"] and len(plan.response["contexts"]) == 1


def test_critical_action_is_moved_last_and_source_order_is_kept(catalog):
    plan = assemble(catalog)
    assert [a["actionName"] for a in plan.response["contexts"][0]["actions"]] == ["Back Up Phone Data", "Visit Service Center", "Reset Device Settings"]


def test_deeplinks_are_copied_from_the_catalog_not_supplied_by_the_caller(catalog):
    plan = assemble(catalog)
    group = plan.response["contexts"][0]["actions"][0]["stepGroups"][0]
    entry = backup_entry(catalog)
    assert group["actionableDeeplink"] == catalog.to_deeplink(entry).model_dump(mode="json", exclude_none=True)
    assert group["validationDeeplink"] == catalog.to_validation_deeplink(entry).model_dump(mode="json", exclude_none=True)


def test_a_draft_has_no_place_to_put_a_uri():
    with pytest.raises(TypeError):
        StepGroupDraft(steps=["Open Settings."], deeplink="https://evil.example")
    with pytest.raises(TypeError):
        StepGroupDraft(steps=["Open Settings."], actionableDeeplink={"deeplink": "bixby://masked/act/x"})
    with pytest.raises(TypeError):
        ActionDraft("Name", "It will do a thing now", "auto", [], deeplink="bixby://masked/act/x")


def test_unknown_candidate_id_is_refused(catalog):
    bad = [ActionDraft("Back Up Phone Data", "It will back up your data", "auto", [StepGroupDraft(["Open Settings."], "DL-9999")])]
    plan = assemble(catalog, bad)
    assert not plan.ok and plan.goal is None and {i.code for i in plan.issues} == {BUILD_ERROR}
    assert plan.response == {"contexts": []}


def test_dummy_candidate_id_is_refused(catalog):
    bad = [ActionDraft("Back Up Phone Data", "It will back up your data", "auto", [StepGroupDraft(["Open Settings."], catalog.dummy.id)])]
    plan = assemble(catalog, bad)
    assert not plan.ok and {i.code for i in plan.issues} == {BUILD_ERROR} and plan.response == {"contexts": []}
    with pytest.raises(PlanBuildError):
        build_goal_dict(GOAL_TEXT, "Screen display damage", 0.9, bad, catalog)


def test_manual_action_with_a_candidate_is_refused_not_silently_fixed(catalog):
    bad = [ActionDraft("Visit Service Center", "It will help you find repair", "manual", [StepGroupDraft(["Visit a center."], backup_entry(catalog).id)])]
    plan = assemble(catalog, bad)
    assert not plan.ok and MANUAL_WITH_DEEPLINK in {i.code for i in plan.issues}


def test_unknown_category_is_refused(catalog):
    bad = [ActionDraft("Back Up Phone Data", "It will back up your data", "standard", [StepGroupDraft(["Open Settings."])])]
    plan = assemble(catalog, bad)
    assert not plan.ok and {i.code for i in plan.issues} == {SEQUENCING_ERROR}


def test_rule_violations_are_refused_and_never_repaired(catalog):
    plan = assemble(catalog, title="x")
    assert not plan.ok and plan.response == {"contexts": []}
    long_description = [ActionDraft("Back Up Phone Data", "It will back up all of your personal data safely", "auto", [StepGroupDraft(["Open Settings."])])]
    assert BAD_DESCRIPTION in {i.code for i in assemble(catalog, long_description).issues}


def test_a_failed_assembly_is_exactly_the_no_match_shape(catalog):
    plan = assemble(catalog, score=7)
    assert not plan.ok and validate_no_match(plan.response)


def test_relaxed_config_is_passed_through_to_validation(catalog):
    long_description = [ActionDraft("Back Up Phone Data", "It will back up all of your personal data safely", "auto", [StepGroupDraft(["Open Settings."])])]
    assert assemble_trusted_plan(GOAL_TEXT, "Screen display damage", 0.9, long_description, catalog, ValidationConfig(description_max_words=12)).ok


def test_assembly_is_deterministic(catalog):
    assert assemble(catalog).response == assemble(catalog).response


def test_no_match_response_is_the_empty_contexts_shape_and_safe_to_mutate():
    first, second = no_match_response(), no_match_response()
    assert first == {"contexts": []} and validate_no_match(first)
    first["contexts"].append("x")
    assert second == {"contexts": []}
    assert NO_MATCH_FALLBACK == "no_match"


def test_tampered_build_output_is_still_caught_by_validation(catalog):
    goal = build_goal_dict(GOAL_TEXT, "Screen display damage", 0.9, drafts(catalog), catalog)
    goal["actions"][1]["stepGroups"][0]["actionableDeeplink"]["description"] = "tampered"
    from app.validation import validate_goal
    assert DEEPLINK_MISMATCH in validate_goal(goal, catalog).codes
