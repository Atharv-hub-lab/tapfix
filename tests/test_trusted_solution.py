from app.catalog import CatalogIndex
from app.llm.solution import SolutionDraft
from app.llm.trusted_solution import build_trusted_solution


def make_catalog(tmp_path):
    catalog_file = tmp_path / "deeplinks.json"

    catalog_file.write_text(
        """
        {
          "deeplinks": [
            {
              "id": "DL-TEST",
              "label": "Wi-Fi",
              "description": "Wi-Fi settings",
              "category": "connectivity",
              "deeplink": "bixby://settings/wifi"
            },
            {
              "id": "DL-DUMMY",
              "label": "Dummy",
              "description": "Dummy positive test entry",
              "category": "test",
              "deeplink": "bixby://dummy_positive"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    return CatalogIndex.from_file(catalog_file)


def make_solution():
    return SolutionDraft(
        goal="Follow these steps to perform this Wi-Fi Troubleshooting",
        title="Wi-Fi settings",
        score=0.95,
        action_name="Enable Wi-Fi",
        description="It will open Wi-Fi settings for you.",
        category="auto",
        steps=(
            "Open Wi-Fi settings.",
            "Turn on Wi-Fi.",
        ),
        catalog_id="DL-TEST",
    )

def test_solution_reaches_trusted_plan(tmp_path):
    catalog = make_catalog(tmp_path)

    result = build_trusted_solution(
        solution=make_solution(),
        catalog=catalog,
    )

    assert result.ok is True
    assert "contexts" in result.response
    assert len(result.response["contexts"]) == 1

    context = result.response["contexts"][0]

    assert context["goal"] == "Follow these steps to perform this Wi-Fi Troubleshooting"
    assert context["title"] == "Wi-Fi settings" 
    assert len(context["actions"]) == 1

    action = context["actions"][0]

    assert action["actionName"] == "Enable Wi-Fi"


def test_unknown_catalog_id_is_rejected(tmp_path):
    catalog = make_catalog(tmp_path)

    solution = SolutionDraft(
        goal="Turn on Wi-Fi",
        title="Wi-Fi",
        score=0.95,
        action_name="Enable Wi-Fi",
        description="This action opens Wi-Fi settings for you.",
        category="auto",
        steps=("Open Wi-Fi settings.",),
        catalog_id="DL-NOT-REAL",
    )

    result = build_trusted_solution(
        solution=solution,
        catalog=catalog,
    )

    assert result.ok is False
    assert result.response == {"contexts": []}