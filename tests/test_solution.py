from app.llm.solution import SolutionDraft


def test_solution_draft_can_be_created():
    draft = SolutionDraft(
        goal="Turn on Wi-Fi",
        title="Wi-Fi",
        score=0.95,
        action_name="Enable Wi-Fi",
        description="It will enable Wi-Fi.",
        category="auto",
        steps=("Open Wi-Fi settings.",),
        catalog_id="DL-TEST",
    )

    assert draft.goal == "Turn on Wi-Fi"
    assert draft.title == "Wi-Fi"
    assert draft.score == 0.95
    assert draft.action_name == "Enable Wi-Fi"
    assert draft.catalog_id == "DL-TEST"


def test_solution_draft_allows_no_catalog_id():
    draft = SolutionDraft(
        goal="Troubleshoot Wi-Fi",
        title="Wi-Fi",
        score=0.5,
        action_name="Check Wi-Fi",
        description="It will check Wi-Fi.",
        category="manual",
        steps=("Open Wi-Fi settings.",),
        catalog_id=None,
    )

    assert draft.catalog_id is None