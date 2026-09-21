# Differentiators log

Each entry is filled in as the feature is built and measured. Numbers come ONLY from
`scripts/run_eval.py` (not built yet). Empty means not measured yet.

## A. Closed-world deeplink safety (foundation built in Step 1)
- **Problem:** LLMs invent plausible-looking URIs and URLs.
- **Approach:** a URI is valid only on an EXACT match with a catalog entry. The LLM will only ever
  point at catalog entries; Python copies the real values (description, message, validation).
  The dummy placeholder's text can never be copied into a plan.
- **Why it matters:** Samsung's hard rules are "catalog integrity" and "zero URL leaks", and both are automated gates.
- **Implemented in:** `app/catalog.py` (`is_real_uri`, `is_allowed_uri`, `is_real_validation_uri`, `to_deeplink`).
- **Tested by:** `tests/test_catalog.py` (invented URLs, altered URIs, dummy misuse, reproduces Samsung's sample exactly).
- **Measured result:** (pending) invalid-URI count from the eval run.

## B. Retrieval engine (BM25 built in Step 2; embeddings + fusion come next)
- **Problem:** map each troubleshooting step to one of 577 Settings screens (later 10,000+) by meaning, not hard-coded rules.
- **Approach:** a small `Retriever` interface plus an inverted-index BM25 over catalog text only (never the masked URI).
  Embeddings and score fusion will plug in behind the same interface, so nothing else changes.
- **Why it matters:** it scales by data and indexing, and any retrieval method can be swapped or compared (ablation).
- **Implemented in:** `app/retrieval.py`. Pure Python, deterministic (ties broken by catalog order).
- **Tested by:** `tests/test_retrieval.py` (ranking, ties, empty queries, URI never searchable, 12,000-entry scale smoke test, real-catalog checks).
- **Findings on the real catalog so far** (these motivate the next differentiators):
  - Samsung's own sample deeplink comes back at rank 2, behind its "Disable" twin: the right setting, the wrong direction.
  - "turn on X" ranks the Disable entry first, because the catalog says "Enables/Disables", not "on/off". This is why the on/off resolver (D) is needed.
  - 5 groups (10 entries) have identical text, so text alone can never separate them.
  - A query about something not in the catalog (e.g. "safe mode") still returns weak matches, so `no_match` needs a margin/coverage rule, not just a score cut-off (C).
- **Measured result:** (pending) recall and latency from the eval run.

## C. Safe no_match: the relevance gate (Step 3; confidence system comes later)
- **Problem:** BM25 always returns something, even for unrelated queries. "Top result = answer" would confidently return a wrong Settings screen.
- **Approach:** a deterministic gate that must pass ALL of: score floor, at least 2 shared words, query coverage,
  rarity-weighted label coverage, and a margin over the best DIFFERENT setting (ON/OFF twins and identical duplicates are not rivals).
  Every threshold is in `RelevanceConfig` and overridable via `TAPFIX_REL_*`. They are initial engineering values, NOT calibrated.
- **Implemented in:** `app/relevance.py`, `app/matching.py`.
- **Tested by:** `tests/test_relevance.py`, `tests/test_matching.py` (unrelated, low-overlap, empty, weak, near-tie, unsupported topics).
- **Measured (my sandbox, Samsung starter data; NOT an accuracy score against Samsung's ground truth):**
  - Each of the 577 real entries queried by its own label: 539 matched, 28 no_match, 10 ambiguous-direction; 0 matched the opposite direction.
  - Of the 539 matches, 406 selected the same entry (or an identical duplicate) and 133 a different entry: 119 of those share the same topic words
    (e.g. "View X" vs "Adjust X" for one setting) and 14 have a different but similar label (e.g. "Fast charging" -> "Fast wireless charging",
    "View Timeout Settings" -> "Check Screen Timeout").
  - The 20 raw complaints in input.txt: 19 no_match, 1 ambiguous-direction (a false topical match on generic words).
  - Known false positive: "the display shows green lines" matches "View When to show", because that label reduces to one generic word ("show").
    Needs calibration on an evaluation set (Step 6).

## D. Direction intelligence (Step 3)
- **Problem:** the catalog has separate Enable/Disable entries; "turn on X" retrieved "Disable X" first.
- **Approach:** a deterministic ON/OFF/UNKNOWN resolver (enable, turn on, activate, switch on ... with negation, conflict and "to turn off" name handling),
  entry direction read from catalog metadata (originalType), wrong-direction candidates rejected, direction words stripped from the retrieval query,
  and an explicit AMBIGUOUS_DIRECTION outcome instead of guessing.
- **Implemented in:** `app/direction.py`, `app/matching.py`.
- **Tested by:** `tests/test_direction.py`, `tests/test_matching.py` (including an all-toggle-entries invariant: never the opposite direction).
- **Measured:** 0 opposite-direction results across the 577 self-label queries (see C).

## F. Validation layer (Step 3)
- **Problem:** anything an LLM produces must be assumed wrong until proven right.
- **Approach:** fail-closed validator: required and unsupported fields, all Samsung field rules, no URLs anywhere, deeplink = verbatim copy of ONE catalog entry,
  validation deeplink belongs to the same entry, dummy placeholder rejected, manual has no deeplink, critical is last, then Samsung's own Pydantic model.
  The builder (`app/plan.py`) copies deeplinks from the catalog by entry id; a draft has no field where a URI could be supplied.
- **Implemented in:** `app/validation.py`, `app/plan.py`, `app/sequencing.py`.
- **Tested by:** `tests/test_validation.py`, `tests/test_plan.py`, `tests/test_sequencing.py`, `tests/test_security.py` (prompt-injection and hostile-catalog cases).
- **Test strength check (sandbox):** 16 deliberate bugs injected one at a time (dummy accepted, direction ignored, URL scan skipped, ordering removed, whitespace-tolerant URI ...); the test-suite failed on all 16.

## Planned (not started)
B2. Embeddings + hybrid fusion | C2. Confidence scores feeding retry/re-rank | E. Safe semantic cache |
G. Paraphrase-robustness eval | H. Observability | I. Automated evaluation engine | J. Ablation study | K. Debug endpoint |
L2. Full failure-first suite through the API
