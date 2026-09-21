"""Plan assembly: from structured drafts to a TRUSTED plan (or a safe refusal).

The future LLM stage will produce `ActionDraft`s: names, descriptions, categories, steps
and, for a step group that should open a Settings screen, a catalog ENTRY ID (a candidate
id, never a URI). This module:

  candidate id -> Python catalog lookup -> copy the catalog entry's deeplink VERBATIM
  -> sequence the actions -> strict validation -> trusted plan

The LLM is never the authority for a URI: the only source is the catalog.
It does not repair anything. If anything is wrong the result is NOT ok and the response
is Samsung's no_match shape ({"contexts": []}); a broken plan is never returned.

Open question (Samsung's guide does not say): where the `"fallback": "no_match"` marker
sits in the response envelope (`meta`? `response`?). This module only provides the
constant and the empty-contexts shape; the API layer decides placement later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.catalog import CatalogIndex
from app.config import ValidationConfig
from app.schema import Goal
from app.sequencing import SequencingError, sequence_actions
from app.validation import Issue, validate_goal

NO_MATCH_FALLBACK = "no_match"
BUILD_ERROR = "build_error"
SEQUENCING_ERROR = "sequencing_error"


def no_match_response() -> Dict[str, Any]:
    """Samsung's no_match shape: an EMPTY contexts list."""
    return {"contexts": []}


class PlanBuildError(ValueError):
    """A draft refers to a catalog id that does not exist, or to the dummy entry."""


@dataclass(frozen=True)
class StepGroupDraft:
    steps: Sequence[str]
    catalog_id: Optional[str] = None  # the candidate the selector/LLM chose; None = no deeplink


@dataclass(frozen=True)
class ActionDraft:
    action_name: str
    description: str
    category: str
    step_groups: Sequence[StepGroupDraft]


@dataclass(frozen=True)
class AssembledPlan:
    ok: bool
    response: Dict[str, Any]  # {"contexts": [goal]} if ok, else the no_match shape
    goal: Optional[Goal] = None  # Samsung's parsed model, only when ok
    issues: Tuple[Issue, ...] = ()


def build_goal_dict(
    goal: str,
    title: str,
    score: float,
    drafts: Sequence[ActionDraft],
    catalog: CatalogIndex,
) -> Dict[str, Any]:
    """Build a Samsung-shaped goal. Deeplink objects are copied from the catalog by entry id."""
    actions: List[Dict[str, Any]] = []
    for draft in drafts:
        groups: List[Dict[str, Any]] = []
        for group in draft.step_groups:
            actionable = validation = None
            if group.catalog_id is not None:
                entry = catalog.get_by_id(group.catalog_id)
                if entry is None:
                    raise PlanBuildError(f"unknown catalog id: {group.catalog_id!r}")
                if entry.is_dummy:
                    raise PlanBuildError("the dummy entry cannot be used as an action")
                actionable = catalog.to_deeplink(entry).model_dump(mode="json", exclude_none=True)
                validation_model = catalog.to_validation_deeplink(entry)
                if validation_model is not None:
                    validation = validation_model.model_dump(mode="json", exclude_none=True)
            groups.append(
                {"steps": list(group.steps), "validationDeeplink": validation, "actionableDeeplink": actionable}
            )
        actions.append(
            {
                "actionName": draft.action_name,
                "description": draft.description,
                "stepGroups": groups,
                "category": draft.category,
            }
        )
    return {"goal": goal, "title": title, "actions": actions, "score": score}


def assemble_trusted_plan(
    goal: str,
    title: str,
    score: float,
    drafts: Sequence[ActionDraft],
    catalog: CatalogIndex,
    config: Optional[ValidationConfig] = None,
) -> AssembledPlan:
    """build -> sequence -> validate. Any failure returns ok=False and the no_match shape."""

    def refuse(code: str, message: str) -> AssembledPlan:
        return AssembledPlan(False, no_match_response(), None, (Issue(code, "plan", message),))

    try:
        goal_dict = build_goal_dict(goal, title, score, drafts, catalog)
    except PlanBuildError as exc:
        return refuse(BUILD_ERROR, str(exc))
    try:
        goal_dict["actions"] = sequence_actions(goal_dict["actions"])
    except SequencingError as exc:
        return refuse(SEQUENCING_ERROR, str(exc))

    result = validate_goal(goal_dict, catalog, config)
    if not result.ok:
        return AssembledPlan(False, no_match_response(), None, result.issues)
    return AssembledPlan(True, {"contexts": [goal_dict]}, result.goals[0], ())
