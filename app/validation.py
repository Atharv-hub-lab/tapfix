"""Strict plan validation. It FAILS CLOSED: if something cannot be verified, it is rejected.

A plan is untrusted input (later: JSON produced by an LLM). Nothing in it is believed:
every deeplink is checked against the Samsung catalog by EXACT match, and the deeplink
object must be a verbatim copy of ONE catalog entry (no mixing an entry's URI with another
entry's text). Only a plan with zero issues is returned as a trusted `Goal`.

What is checked
  structure   required fields, no unsupported fields, correct types, no empty plan
  text rules  goal syntax, title (2-3 words), score 0..1, actionName Title Case,
              description (It will + 5-7 words), non-empty steps (limits: ValidationConfig)
  no URLs     web links, markdown links, bare domains or any "scheme://" in ANY text
  deeplinks   actionableDeeplink == an existing catalog entry, exactly; the dummy
              placeholder is rejected; validationDeeplink must belong to the same entry
  categories  auto / manual / critical only; manual carries no deeplink; critical is last
  schema      finally, Samsung's own Pydantic `Goal` model must accept it

What is NOT checked (cannot be verified deterministically): whether the steps are correct
or "one interaction per step", or whether the plan is the best answer.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.catalog import DUMMY_URI, CatalogEntry, CatalogIndex
from app.config import ValidationConfig
from app.schema import Goal
from app.sequencing import VALID_CATEGORIES, is_sequenced

# ---- issue codes (stable strings; tests and later observability rely on them) ----
MALFORMED = "malformed"
MISSING_FIELD = "missing_field"
UNSUPPORTED_FIELD = "unsupported_field"
EMPTY_PLAN = "empty_plan"
BAD_GOAL = "bad_goal"
BAD_TITLE = "bad_title"
BAD_SCORE = "bad_score"
BAD_ACTION_NAME = "bad_action_name"
BAD_DESCRIPTION = "bad_description"
BAD_STEP = "bad_step"
URL_LEAK = "url_leak"
EXTERNAL_URL = "external_url"
UNKNOWN_DEEPLINK = "unknown_deeplink"
DUMMY_DEEPLINK = "dummy_deeplink"
DEEPLINK_MISMATCH = "deeplink_mismatch"
ORPHAN_VALIDATION = "orphan_validation_deeplink"
UNKNOWN_VALIDATION_DEEPLINK = "unknown_validation_deeplink"
VALIDATION_MISMATCH = "validation_deeplink_mismatch"
INVALID_CATEGORY = "invalid_category"
MANUAL_WITH_DEEPLINK = "manual_with_deeplink"
CRITICAL_NOT_LAST = "critical_not_last"
SCHEMA_VIOLATION = "schema_violation"

_GOAL_KEYS = {"goal", "title", "actions", "score"}
_ACTION_KEYS = {"actionName", "description", "stepGroups", "category"}
_STEP_GROUP_KEYS = {"steps", "validationDeeplink", "actionableDeeplink"}
_DEEPLINK_KEYS = {"deeplink", "description", "message", "classes", "originalType"}
_VALIDATION_KEYS = {"deeplink", "key", "resultType", "condition", "value"}

_GOAL_RE = re.compile(r"Follow these steps to perform this (?P<topic>\S.*?) (?:Troubleshooting|Configuration)")
# web links, markdown links, bare domains, and ANY scheme:// (this also catches bixby:// in prose)
_URL_RE = re.compile(
    r"(?:[a-z][a-z0-9+.\-]*://)|(?:\bwww\.)|(?:\]\()|(?:\b[a-z0-9\-]+\.(?:com|net|org|io|gov|edu|app|dev)\b)",
    re.IGNORECASE,
)
_WEB_URI_RE = re.compile(r"\s*(?:https?://|www\.)", re.IGNORECASE)
_MINOR_WORDS = frozenset("a an and as at but by for in of on or the to via vs".split())


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    issues: Tuple[Issue, ...] = ()
    goals: Tuple[Goal, ...] = ()  # populated ONLY when ok is True

    @property
    def codes(self) -> set:
        return {issue.code for issue in self.issues}


class _Ctx:
    def __init__(self, catalog: CatalogIndex, config: ValidationConfig) -> None:
        self.catalog = catalog
        self.config = config
        self.issues: List[Issue] = []

    def add(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue(code, path, message))


# ------------------------------------------------------------------ helpers
def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_title_case(text: str) -> bool:
    words = text.split()
    if not words:
        return False
    for i, word in enumerate(words):
        core = word.strip("()[]{}.,:;!?\"'")
        if not core:
            continue
        if core in _MINOR_WORDS and 0 < i < len(words) - 1:
            continue  # small joining words may stay lower-case in the middle
        first_letter = next((ch for ch in core if ch.isalpha()), None)
        if first_letter is not None and not first_letter.isupper():
            return False
    return True


def _check_keys(obj: Dict[str, Any], allowed: set, required: set, path: str, ctx: _Ctx) -> None:
    for key in sorted(required - set(obj)):
        ctx.add(MISSING_FIELD, path, f"missing required field '{key}'")
    for key in sorted(set(obj) - allowed):
        ctx.add(UNSUPPORTED_FIELD, path, f"unsupported field '{key}'")


def _scan_urls(node: Any, path: str, ctx: _Ctx) -> None:
    """Zero-URL-leak rule, applied to EVERY string in the plan except deeplink URIs."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "deeplink":
                continue  # URIs are validated separately, by exact catalog match
            _scan_urls(value, f"{path}.{key}", ctx)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _scan_urls(value, f"{path}[{i}]", ctx)
    elif isinstance(node, str) and _URL_RE.search(node):
        ctx.add(URL_LEAK, path, "text contains a URL or link")


# ------------------------------------------------------------------ deeplinks
def _check_actionable(obj: Any, path: str, ctx: _Ctx) -> Optional[CatalogEntry]:
    """Return the catalog entry the deeplink object is a verbatim copy of, else None."""
    if not isinstance(obj, dict):
        ctx.add(MALFORMED, path, "actionableDeeplink must be an object or null")
        return None
    for key in sorted(set(obj) - _DEEPLINK_KEYS):
        ctx.add(UNSUPPORTED_FIELD, path, f"unsupported field '{key}'")
    uri = obj.get("deeplink")
    if not _is_str(uri):
        ctx.add(MALFORMED, f"{path}.deeplink", "deeplink must be a string")
        return None
    if uri == DUMMY_URI:
        ctx.add(DUMMY_DEEPLINK, f"{path}.deeplink", "the dummy placeholder is never allowed in a plan")
        return None
    entry = ctx.catalog.get(uri)  # EXACT match only
    if entry is None:
        code = EXTERNAL_URL if _WEB_URI_RE.match(uri) else UNKNOWN_DEEPLINK
        ctx.add(code, f"{path}.deeplink", "deeplink is not in the Samsung catalog")
        return None
    expected = ctx.catalog.to_deeplink(entry).model_dump(mode="json", exclude_none=True)
    actual = {k: v for k, v in obj.items() if v is not None}
    if actual != expected:
        ctx.add(DEEPLINK_MISMATCH, path, "deeplink object is not a verbatim copy of its catalog entry")
        return None
    return entry


def _check_validation(obj: Any, entry: Optional[CatalogEntry], path: str, ctx: _Ctx) -> None:
    if obj is None:
        return
    if entry is None:
        ctx.add(ORPHAN_VALIDATION, path, "validationDeeplink needs a verified actionableDeeplink in the same group")
        return
    if not isinstance(obj, dict):
        ctx.add(MALFORMED, path, "validationDeeplink must be an object or null")
        return
    for key in sorted(set(obj) - _VALIDATION_KEYS):
        ctx.add(UNSUPPORTED_FIELD, path, f"unsupported field '{key}'")
    uri = obj.get("deeplink")
    if not _is_str(uri) or not ctx.catalog.is_real_validation_uri(uri):
        ctx.add(UNKNOWN_VALIDATION_DEEPLINK, f"{path}.deeplink", "validation deeplink is not in the catalog")
        return
    expected_model = ctx.catalog.to_validation_deeplink(entry)
    expected = expected_model.model_dump(mode="json", exclude_none=True) if expected_model else None
    actual = {k: v for k, v in obj.items() if v is not None}
    if expected != actual:
        ctx.add(VALIDATION_MISMATCH, path, "validationDeeplink does not belong to this actionableDeeplink's entry")


# ------------------------------------------------------------------ structure
def _check_step_group(group: Any, path: str, ctx: _Ctx) -> bool:
    """Returns True if the group carries an actionable or validation deeplink."""
    if not isinstance(group, dict):
        ctx.add(MALFORMED, path, "stepGroup must be an object")
        return False
    _check_keys(group, _STEP_GROUP_KEYS, {"steps"}, path, ctx)

    steps = group.get("steps")
    if "steps" in group:
        if not isinstance(steps, list) or not steps:
            ctx.add(EMPTY_PLAN if isinstance(steps, list) else MALFORMED, f"{path}.steps", "steps must be a non-empty list")
        else:
            for i, step in enumerate(steps):
                if not _is_str(step) or not step.strip():
                    ctx.add(BAD_STEP, f"{path}.steps[{i}]", "each step must be a non-empty string")

    entry = None
    if group.get("actionableDeeplink") is not None:
        entry = _check_actionable(group["actionableDeeplink"], f"{path}.actionableDeeplink", ctx)
    _check_validation(group.get("validationDeeplink"), entry, f"{path}.validationDeeplink", ctx)
    return group.get("actionableDeeplink") is not None or group.get("validationDeeplink") is not None


def _check_action(action: Any, path: str, ctx: _Ctx) -> Optional[str]:
    """Returns the action's category if it is valid, else None."""
    if not isinstance(action, dict):
        ctx.add(MALFORMED, path, "action must be an object")
        return None
    _check_keys(action, _ACTION_KEYS, _ACTION_KEYS, path, ctx)
    cfg = ctx.config

    if "actionName" in action:
        name = action["actionName"]
        if not _is_str(name) or not name.strip() or not _is_title_case(name):
            ctx.add(BAD_ACTION_NAME, f"{path}.actionName", "actionName must be non-empty Title Case")

    if "description" in action:
        text = action["description"]
        if not _is_str(text):
            ctx.add(BAD_DESCRIPTION, f"{path}.description", "description must be a string")
        else:
            n_words = len(text.split())
            if not (cfg.description_min_words <= n_words <= cfg.description_max_words):
                ctx.add(
                    BAD_DESCRIPTION,
                    f"{path}.description",
                    f"description must have {cfg.description_min_words}-{cfg.description_max_words} words (has {n_words})",
                )
            if not text.startswith(cfg.description_prefix):
                ctx.add(BAD_DESCRIPTION, f"{path}.description", f"description must start with '{cfg.description_prefix}'")

    category = action.get("category")
    valid_category = _is_str(category) and category in VALID_CATEGORIES
    if "category" in action and not valid_category:
        ctx.add(INVALID_CATEGORY, f"{path}.category", "category must be exactly auto, manual or critical")

    groups = action.get("stepGroups")
    if "stepGroups" in action:
        if not isinstance(groups, list) or not groups:
            ctx.add(EMPTY_PLAN if isinstance(groups, list) else MALFORMED, f"{path}.stepGroups", "stepGroups must be a non-empty list")
        else:
            has_deeplink = [_check_step_group(g, f"{path}.stepGroups[{i}]", ctx) for i, g in enumerate(groups)]
            if valid_category and category == "manual" and any(has_deeplink):
                ctx.add(MANUAL_WITH_DEEPLINK, path, "a manual action must not carry any deeplink")
    return category if valid_category else None


def _check_goal(goal: Any, path: str, ctx: _Ctx) -> None:
    if not isinstance(goal, dict):
        ctx.add(MALFORMED, path or "goal", "goal must be an object")
        return
    _check_keys(goal, _GOAL_KEYS, _GOAL_KEYS, path, ctx)
    cfg = ctx.config

    if "goal" in goal:
        text = goal["goal"]
        match = _GOAL_RE.fullmatch(text) if _is_str(text) else None
        if match is None:
            ctx.add(BAD_GOAL, f"{path}.goal", "goal must be 'Follow these steps to perform this <Topic> Troubleshooting' (or Configuration)")

    if "title" in goal:
        title = goal["title"]
        words = title.split() if _is_str(title) else []
        if not (cfg.title_min_words <= len(words) <= cfg.title_max_words) or not words[0][0].isupper():
            ctx.add(BAD_TITLE, f"{path}.title", f"title must be {cfg.title_min_words}-{cfg.title_max_words} words in sentence case")

    if "score" in goal:
        score = goal["score"]
        is_number = isinstance(score, (int, float)) and not isinstance(score, bool)
        if not is_number or not math.isfinite(score) or not 0.0 <= score <= 1.0:
            ctx.add(BAD_SCORE, f"{path}.score", "score must be a number between 0.0 and 1.0")

    actions = goal.get("actions")
    if "actions" in goal:
        if not isinstance(actions, list) or not actions:
            ctx.add(EMPTY_PLAN if isinstance(actions, list) else MALFORMED, f"{path}.actions", "actions must be a non-empty list")
        else:
            categories = [_check_action(a, f"{path}.actions[{i}]", ctx) for i, a in enumerate(actions)]
            if all(c is not None for c in categories) and not is_sequenced(categories):
                ctx.add(CRITICAL_NOT_LAST, f"{path}.actions", "critical actions must come last")

    _scan_urls(goal, path or "goal", ctx)


def _finish(ctx: _Ctx, goals_raw: List[Any]) -> ValidationResult:
    """Last step: Samsung's own Pydantic schema must accept every goal (only tried if no issues so far)."""
    if ctx.issues:
        return ValidationResult(False, tuple(ctx.issues))
    parsed: List[Goal] = []
    for i, raw in enumerate(goals_raw):
        try:
            parsed.append(Goal.model_validate(raw))
        except ValidationError as exc:
            ctx.add(SCHEMA_VIOLATION, f"contexts[{i}]", str(exc).splitlines()[0] if str(exc) else "schema violation")
    if ctx.issues:
        return ValidationResult(False, tuple(ctx.issues))
    return ValidationResult(True, (), tuple(parsed))


# ------------------------------------------------------------------ public API
def validate_goal(goal: Any, catalog: CatalogIndex, config: Optional[ValidationConfig] = None) -> ValidationResult:
    """Validate ONE goal (a plan). ok=True only if every rule passes."""
    ctx = _Ctx(catalog, config or ValidationConfig())
    _check_goal(goal, "goal", ctx)
    return _finish(ctx, [goal])


def validate_response(response: Any, catalog: CatalogIndex, config: Optional[ValidationConfig] = None) -> ValidationResult:
    """Validate a `response` object: {"contexts": [goal, ...]} with at least one goal."""
    ctx = _Ctx(catalog, config or ValidationConfig())
    if not isinstance(response, dict):
        ctx.add(MALFORMED, "response", "response must be an object")
        return ValidationResult(False, tuple(ctx.issues))
    _check_keys(response, {"contexts"}, {"contexts"}, "response", ctx)
    contexts = response.get("contexts")
    if "contexts" in response:
        if not isinstance(contexts, list):
            ctx.add(MALFORMED, "response.contexts", "contexts must be a list")
        elif not contexts:
            ctx.add(EMPTY_PLAN, "response.contexts", "a plan needs at least one goal (use validate_no_match for no_match)")
        else:
            for i, goal in enumerate(contexts):
                _check_goal(goal, f"contexts[{i}]", ctx)
    return _finish(ctx, contexts if isinstance(contexts, list) else [])


def validate_no_match(response: Any) -> bool:
    """True only for Samsung's no_match shape: exactly {"contexts": []}."""
    return isinstance(response, dict) and set(response) == {"contexts"} and response["contexts"] == []
