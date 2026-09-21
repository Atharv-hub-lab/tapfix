from __future__ import annotations

from app.catalog import CatalogIndex
from app.llm.solution import SolutionDraft
from app.plan import ActionDraft, StepGroupDraft


def solution_to_action_draft(
    solution: SolutionDraft,
    catalog: CatalogIndex,
) -> ActionDraft:
    """
    Convert an untrusted SolutionDraft into an ActionDraft.

    The LLM is never allowed to provide the deeplink.
    The catalog is the only source of truth for catalog metadata.
    """

    if not solution.catalog_id:
        raise ValueError("Solution does not contain a catalog_id")

    entry = catalog.get_by_id(solution.catalog_id)

    if entry is None:
        raise ValueError(
            f"Solution references unknown catalog ID: {solution.catalog_id}"
        )

    return ActionDraft(
        action_name=solution.action_name,
        description=solution.description,
        category=solution.category,
        step_groups=(
            StepGroupDraft(
                steps=solution.steps,
                catalog_id=entry.id,
            ),
        ),
    )