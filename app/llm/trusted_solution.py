from __future__ import annotations

from app.catalog import CatalogIndex
from app.llm.solution import SolutionDraft
from app.llm.solution_to_plan import solution_to_action_draft
from app.plan import ActionDraft, AssembledPlan, StepGroupDraft, assemble_trusted_plan


def build_trusted_solution(
    solution: SolutionDraft,
    catalog: CatalogIndex,
) -> AssembledPlan:
    """
    Convert an untrusted Stage-2 SolutionDraft into the final
    validated TapFix response.

    A real catalog_id is resolved through the catalog.

    A solution with catalog_id=None is treated as a manual troubleshooting
    action and carries no deeplink.
    """

    if solution.catalog_id is None:
        action_draft = ActionDraft(
            action_name=solution.action_name,
            description=solution.description,
            category="manual",
            step_groups=(
                StepGroupDraft(
                    steps=solution.steps,
                    catalog_id=None,
                ),
            ),
        )

        return assemble_trusted_plan(
            goal=solution.goal,
            title=solution.title,
            score=solution.score,
            drafts=(action_draft,),
            catalog=catalog,
        )

    try:
        action_draft = solution_to_action_draft(
            solution,
            catalog,
        )
    except ValueError:
        return AssembledPlan(
            ok=False,
            response={"contexts": []},
            goal=None,
            issues=(),
        )

    result = assemble_trusted_plan(
            goal=solution.goal,
            title=solution.title,
            score=solution.score,
            drafts=(action_draft,),
            catalog=catalog,
        )

    if not result.ok:
            print(f"[WARN] Manual trusted plan rejected: {result.issues}")

    return result