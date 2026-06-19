"""Ground-truth alert scorecard: the AI's *actual* alert detection vs the corpus
labels, independent of translator votes (the verdict aggregation measures the
*perceived* precision instead).

Every synthetic / harvested issue letter carries a ground-truth expected category
(including FP-traps labelled "no_alert"); this module joins those labels to the
AI's emitted alert per letter and classifies each outcome. Real clean letters
carry no ground truth and are skipped.

PURE function over caller-supplied rows (dict / sqlite3.Row); it never reads the
database. The caller fetches the corpus letters + the ai_responses and resolves
the active prompt_version via ``filters``.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis._common import get_value, passes_filters

# Canonical "no alert" token. The emitted side may arrive as SQL NULL or the
# literal string; both normalize to this so classification is convention-agnostic.
NO_ALERT = "no_alert"


def _norm(category: str | None) -> str:
    """Map a missing/empty alert category to the canonical no-alert token."""
    return category if category else NO_ALERT


@dataclass(frozen=True)
class CategoryScore:
    tp: int = 0
    fn: int = 0
    wrong_category: int = 0


@dataclass(frozen=True)
class FpTrap:
    passed: int = 0
    failed: int = 0


@dataclass(frozen=True)
class LetterOutcome:
    letter_id: int
    expected: str
    emitted: str
    prompt_version: str | None


@dataclass(frozen=True)
class GroundTruthReport:
    # expected issue category -> {tp, fn, wrong_category} (FP-traps are NOT here)
    per_category: dict[str, CategoryScore]
    # FP-trap letters (expected no_alert): correctly silent vs falsely alerted
    fp_trap: FpTrap
    # one entry per scored (letter, response) — the per-letter audit detail
    per_letter_detail: list[LetterOutcome]


def score_ground_truth(letters, ai_responses, filters=None) -> GroundTruthReport:
    """Classify each ground-truth letter's emitted alert against its expected
    category. ``letters`` supplies the labels (only those with a non-null
    ``ground_truth_category`` are in scope); ``ai_responses`` (filtered by
    ``prompt_version``) supplies the emissions. A letter with no emission in the
    selected version is not scored. ``filters`` honors ``prompt_version`` only
    (``"__all__"`` or an absent key disables it)."""
    filters = filters or {}
    expected_by_letter = {}
    for letter in letters:
        gt = get_value(letter, "ground_truth_category")
        if gt is None:
            continue  # real clean letter -> out of scope
        expected_by_letter[get_value(letter, "id")] = _norm(gt)

    per_cat: dict[str, list[int]] = {}
    trap_passed = trap_failed = 0
    detail: list[LetterOutcome] = []
    for resp in ai_responses:
        if not passes_filters(resp, filters, keys=("prompt_version",)):
            continue
        letter_id = get_value(resp, "letter_id")
        if letter_id not in expected_by_letter:
            continue  # response for a letter with no ground truth -> skip
        expected = expected_by_letter[letter_id]
        emitted = _norm(get_value(resp, "alert_category"))
        if expected == NO_ALERT:
            if emitted == NO_ALERT:
                trap_passed += 1
            else:
                trap_failed += 1  # false positive on a trap letter
        else:
            acc = per_cat.setdefault(expected, [0, 0, 0])
            if emitted == expected:
                acc[0] += 1  # true positive
            elif emitted == NO_ALERT:
                acc[1] += 1  # false negative (missed the issue)
            else:
                acc[2] += 1  # wrong category (alerted, but not the expected one)
        detail.append(
            LetterOutcome(
                letter_id=letter_id,
                expected=expected,
                emitted=emitted,
                prompt_version=get_value(resp, "prompt_version"),
            )
        )

    per_category = {cat: CategoryScore(tp, fn, wc) for cat, (tp, fn, wc) in per_cat.items()}
    return GroundTruthReport(
        per_category=per_category,
        fp_trap=FpTrap(passed=trap_passed, failed=trap_failed),
        per_letter_detail=detail,
    )
