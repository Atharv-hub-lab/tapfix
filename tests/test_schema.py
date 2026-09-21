from app.schema import ContextDeeplinkResponse, actionCategory


def test_samsung_sample_output_validates_against_schema(sample_output):
    parsed = ContextDeeplinkResponse.model_validate(sample_output["response"])
    goal = parsed.contexts[0]
    assert goal.goal.startswith("Follow these steps to perform this")
    assert [a.category.value for a in goal.actions] == ["auto", "manual"]


def test_manual_action_in_sample_has_no_deeplink(sample_output):
    parsed = ContextDeeplinkResponse.model_validate(sample_output["response"])
    manual = [a for a in parsed.contexts[0].actions if a.category == actionCategory.manual][0]
    assert all(sg.actionableDeeplink is None for sg in manual.stepGroups)


def test_category_values_are_exactly_the_three_official_ones():
    assert {c.value for c in actionCategory} == {"auto", "manual", "critical"}


def test_empty_response_is_the_no_match_shape():
    # The no_match behaviour returns an EMPTY contexts list.
    assert ContextDeeplinkResponse().contexts == []
