import pytest

from app.catalog import CatalogIndex
from app.llm.solution import SolutionDraft
from app.llm.solution_to_plan import solution_to_action_draft


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


def test_solution_is_converted_using_catalog_entry(tmp_path):
    catalog = make_catalog(tmp_path)

    solution = SolutionDraft(
        goal="Turn on Wi-Fi",
        title="Wi-Fi",
        score=0.95,
        action_name="Enable Wi-Fi",
        description="Enable Wi-Fi from Settings.",
        category="auto",
        steps=("Open Wi-Fi settings.",),
        catalog_id="DL-TEST",
    )

    result = solution_to_action_draft(
        solution,
        catalog,
    )

    assert result.action_name == "Enable Wi-Fi"
    assert result.description == "Enable Wi-Fi from Settings."
    assert result.category == "auto"

    assert len(result.step_groups) == 1
    assert result.step_groups[0].catalog_id == "DL-TEST"


def test_unknown_catalog_id_is_rejected(tmp_path):
    catalog = make_catalog(tmp_path)

    solution = SolutionDraft(
        goal="Turn on Wi-Fi",
        title="Wi-Fi",
        score=0.95,
        action_name="Enable Wi-Fi",
        description="Enable Wi-Fi from Settings.",
        category="auto",
        steps=("Open Wi-Fi settings.",),
        catalog_id="DL-NOT-REAL",
    )

    with pytest.raises(ValueError, match="unknown catalog ID"):
        solution_to_action_draft(
            solution,
            catalog,
        )


def test_missing_catalog_id_is_rejected(tmp_path):
    catalog = make_catalog(tmp_path)

    solution = SolutionDraft(
        goal="Troubleshoot Wi-Fi",
        title="Wi-Fi",
        score=0.5,
        action_name="Check Wi-Fi",
        description="Check Wi-Fi settings.",
        category="manual",
        steps=("Open Wi-Fi settings.",),
        catalog_id=None,
    )

    with pytest.raises(ValueError, match="catalog_id"):
        solution_to_action_draft(
            solution,
            catalog,
        )