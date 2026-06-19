"""Tests for analysis.alerts — alert-verdict + missed-issue aggregation (pure)."""
from analysis.alerts import (
    VerdictCounts,
    aggregate_alert_verdicts,
    aggregate_missed_issues,
)


def _eval(verdict, *, alert_category="health", prompt_version="v1",
          translator_id=1, letter_id=1):
    return {
        "verdict": verdict,
        "alert_category": alert_category,
        "prompt_version": prompt_version,
        "translator_id": translator_id,
        "letter_id": letter_id,
    }


def _missed(missed_yes_no, *, category=None, alert_category="health",
            prompt_version="v1", translator_id=1, letter_id=1):
    return {
        "missed_yes_no": missed_yes_no,
        "category": category,
        "alert_category": alert_category,
        "prompt_version": prompt_version,
        "translator_id": translator_id,
        "letter_id": letter_id,
    }


# ---- aggregate_alert_verdicts ----

def test_verdicts_empty_input():
    r = aggregate_alert_verdicts([])
    assert r.per_category == {}
    assert r.overall == VerdictCounts(0, 0, 0)
    assert r.overall.total == 0


def test_verdicts_single_category():
    evals = [_eval("Correct"), _eval("Correct"), _eval("Incorrect"), _eval("Mixed")]
    r = aggregate_alert_verdicts(evals)
    assert r.per_category == {"health": VerdictCounts(2, 1, 1)}
    assert r.overall == VerdictCounts(2, 1, 1)
    assert r.per_category["health"].total == 4


def test_verdicts_multi_category_overall_is_sum():
    evals = [
        _eval("Correct", alert_category="health"),
        _eval("Incorrect", alert_category="health"),
        _eval("Mixed", alert_category="abuse"),
        _eval("Correct", alert_category="abuse"),
    ]
    r = aggregate_alert_verdicts(evals)
    assert r.per_category["health"] == VerdictCounts(1, 1, 0)
    assert r.per_category["abuse"] == VerdictCounts(1, 0, 1)
    assert r.overall == VerdictCounts(2, 1, 1)  # summed across categories


def test_verdicts_mixed_only():
    r = aggregate_alert_verdicts([_eval("Mixed"), _eval("Mixed")])
    assert r.overall == VerdictCounts(0, 0, 2)
    assert r.per_category["health"] == VerdictCounts(0, 0, 2)


def test_verdicts_unknown_or_missing_verdict_skipped():
    r = aggregate_alert_verdicts([_eval("Correct"), _eval(None), _eval("bogus")])
    assert r.overall == VerdictCounts(1, 0, 0)


def test_verdicts_filter_by_prompt_version_and_all_sentinel():
    evals = [_eval("Correct", prompt_version="v1"), _eval("Incorrect", prompt_version="v2")]
    assert aggregate_alert_verdicts(evals, {"prompt_version": "v1"}).overall == VerdictCounts(1, 0, 0)
    assert aggregate_alert_verdicts(evals, {"prompt_version": "v2"}).overall == VerdictCounts(0, 1, 0)
    assert aggregate_alert_verdicts(evals, {"prompt_version": "__all__"}).overall == VerdictCounts(1, 1, 0)
    assert aggregate_alert_verdicts(evals, {}).overall == VerdictCounts(1, 1, 0)


def test_verdicts_filter_by_category_and_translator():
    evals = [
        _eval("Correct", alert_category="health", translator_id=1),
        _eval("Incorrect", alert_category="abuse", translator_id=1),
        _eval("Mixed", alert_category="health", translator_id=2),
    ]
    r = aggregate_alert_verdicts(evals, {"alert_category": "health"})
    assert set(r.per_category) == {"health"}
    assert r.overall == VerdictCounts(1, 0, 1)
    assert aggregate_alert_verdicts(evals, {"translator_id": 2}).overall == VerdictCounts(0, 0, 1)


# ---- aggregate_missed_issues ----

def test_missed_empty_input():
    r = aggregate_missed_issues([])
    assert r.per_category == {}
    assert r.total == 0


def test_missed_counts_yes_per_category_excludes_no():
    missed = [
        _missed(1, category="abuse"),
        _missed(1, category="abuse"),
        _missed(1, category="health"),
        _missed(0, category=None),  # "no" -> excluded
    ]
    r = aggregate_missed_issues(missed)
    assert r.per_category == {"abuse": 2, "health": 1}
    assert r.total == 3


def test_missed_groups_by_missed_category_not_alert_category():
    # Grouping key is `category` (what was missed); `alert_category` is the
    # AI-emitted category and only a filter dimension — the two must not conflate.
    missed = [
        _missed(1, category="abuse", alert_category="health"),
        _missed(1, category="abuse", alert_category="no_alert"),
    ]
    assert aggregate_missed_issues(missed).per_category == {"abuse": 2}
    r = aggregate_missed_issues(missed, {"alert_category": "health"})
    assert r.per_category == {"abuse": 1}
    assert r.total == 1


def test_missed_filter_by_prompt_version_and_all_sentinel():
    missed = [
        _missed(1, category="abuse", prompt_version="v1"),
        _missed(1, category="health", prompt_version="v2"),
    ]
    assert aggregate_missed_issues(missed, {"prompt_version": "v1"}).per_category == {"abuse": 1}
    assert aggregate_missed_issues(missed, {"prompt_version": "__all__"}).total == 2
    assert aggregate_missed_issues(missed, {}).total == 2
