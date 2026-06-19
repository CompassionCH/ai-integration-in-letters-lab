"""Alert-verdict and missed-issue aggregation.

``aggregate_alert_verdicts``: per-category Correct/Incorrect/Mixed tallies (plus
an overall) of how volunteers judged the AI's emitted alerts — precision-style.
"Mixed" is kept as its own bucket, never folded into the correct/incorrect split.

``aggregate_missed_issues``: per-category counts of "yes, the AI missed an issue"
answers — indicative (qualitative) recall on this small corpus.

Both are PURE functions over caller-supplied rows (dict / sqlite3.Row) already
joined to ``ai_responses`` for the filter dimensions; neither reads the database.
The caller resolves the active prompt_version and passes it via ``filters``.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis._common import get_value, passes_filters

# Verdict label -> slot in the (correct, incorrect, mixed) accumulator.
_VERDICT_INDEX = {"Correct": 0, "Incorrect": 1, "Mixed": 2}


@dataclass(frozen=True)
class VerdictCounts:
    correct: int = 0
    incorrect: int = 0
    mixed: int = 0

    @property
    def total(self) -> int:
        return self.correct + self.incorrect + self.mixed


@dataclass(frozen=True)
class AlertVerdictReport:
    # category id (the AI's emitted alert_category) -> VerdictCounts
    per_category: dict[str, VerdictCounts]
    # tally across every category that passed the filters
    overall: VerdictCounts


@dataclass(frozen=True)
class MissedIssueReport:
    # missed-issue category id (what the volunteer flagged) -> count of "yes"
    per_category: dict[str, int]
    # total "yes, the AI missed something" answers
    total: int


def aggregate_alert_verdicts(alert_evals, filters=None) -> AlertVerdictReport:
    """Tally Correct/Incorrect/Mixed verdicts per alert category (the AI-emitted
    ``alert_category``), plus an overall. ``alert_evals`` is any iterable of
    mappings carrying ``verdict`` and the filter dimensions; a row whose
    ``verdict`` is unrecognized/None is skipped."""
    filters = filters or {}
    per_cat: dict[str, list[int]] = {}
    overall = [0, 0, 0]
    for row in alert_evals:
        if not passes_filters(row, filters):
            continue
        slot = _VERDICT_INDEX.get(get_value(row, "verdict"))
        if slot is None:
            continue  # no/unknown verdict -> nothing to tally
        counts = per_cat.setdefault(get_value(row, "alert_category"), [0, 0, 0])
        counts[slot] += 1
        overall[slot] += 1
    per_category = {
        cat: VerdictCounts(c, inc, mix) for cat, (c, inc, mix) in per_cat.items()
    }
    return AlertVerdictReport(per_category=per_category, overall=VerdictCounts(*overall))


def aggregate_missed_issues(missed, filters=None) -> MissedIssueReport:
    """Count "yes" missed-issue answers per missed category. ``category`` is the
    issue the volunteer flagged as missed — distinct from the AI-emitted
    ``alert_category`` used only for filtering. ``missed`` is any iterable of
    mappings carrying ``missed_yes_no`` (1 = yes, the DB form), ``category`` and
    the filter dimensions; "no" rows are skipped."""
    filters = filters or {}
    per_category: dict[str, int] = {}
    total = 0
    for row in missed:
        if not passes_filters(row, filters):
            continue
        if get_value(row, "missed_yes_no") not in (1, "yes"):
            continue  # "no" / absent -> not a missed-issue report
        category = get_value(row, "category")
        per_category[category] = per_category.get(category, 0) + 1
        total += 1
    return MissedIssueReport(per_category=per_category, total=total)
