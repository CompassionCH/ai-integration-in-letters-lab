"""Tests for analysis.preference — AI-vs-human acceptability + strict preference.

Pure-function tests over in-memory fixture rows (plain dicts); no DB.
"""
import math

from analysis.preference import PreferenceReport, aggregate_preference


def _vote(preference, a_is_ai=None, *, prompt_version="v1", alert_category=None,
          translator_id=1, letter_id=1):
    """A single vote row as the caller's join would produce it."""
    return {
        "preference": preference,
        "a_is_ai": a_is_ai,
        "prompt_version": prompt_version,
        "alert_category": alert_category,
        "translator_id": translator_id,
        "letter_id": letter_id,
    }


def _balanced(n):
    """n decisive, tie-free votes split 50/50 AI/human (p = 0.5 for both rates).
    Both picked column A; a_is_ai=1 -> AI chosen, a_is_ai=0 -> human chosen."""
    half = n // 2
    return [_vote("A", 1)] * half + [_vote("A", 0)] * half


def test_maps_all_four_ab_combinations_and_equivalent():
    votes = [
        _vote("A", 1),  # A picked, A is AI    -> AI win
        _vote("A", 0),  # A picked, A is human -> human win
        _vote("B", 1),  # B picked, A is AI    -> B is human -> human win
        _vote("B", 0),  # B picked, A is human -> B is AI    -> AI win
        _vote("Equivalent"),
    ]
    r = aggregate_preference(votes)
    assert (r.ai_wins, r.human_wins, r.equivalent, r.total) == (2, 2, 1, 5)


def test_synthetic_votes_excluded():
    r = aggregate_preference([_vote("A", 1), _vote(None), _vote(None)])
    assert r.total == 1
    assert r.ai_wins == 1


def test_unmappable_decisive_row_skipped():
    # preference set but a_is_ai missing -> cannot map a side -> skip, don't miscount.
    r = aggregate_preference([_vote("A", None), _vote("A", 1)])
    assert r.total == 1
    assert r.ai_wins == 1


def test_empty_input_is_all_zeros():
    r = aggregate_preference([])
    assert r == PreferenceReport(0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_ties_count_for_acceptability_not_strict_preference():
    # 3 AI wins, 1 human win, 6 ties.
    votes = [_vote("A", 1)] * 3 + [_vote("B", 1)] * 1 + [_vote("Equivalent")] * 6
    r = aggregate_preference(votes)
    assert (r.ai_wins, r.human_wins, r.equivalent, r.total) == (3, 1, 6, 10)
    # Strict preference excludes ties: 3 / (3 + 1).
    assert math.isclose(r.ai_preferred_pct, 0.75)
    # Acceptability counts ties as AI: (3 + 6) / 10.
    assert math.isclose(r.ai_acceptable_pct, 0.90)


def test_all_equivalent_strict_is_zero_acceptable_is_full():
    r = aggregate_preference([_vote("Equivalent")] * 5)
    assert (r.ai_wins, r.human_wins, r.equivalent, r.total) == (0, 0, 5, 5)
    # No decisive votes -> strict preference undefined -> reported as zeros.
    assert r.ai_preferred_pct == 0.0
    assert r.preferred_ci_low == 0.0 and r.preferred_ci_high == 0.0
    # Every letter was "at least as good" -> acceptability 1.0 (margin collapses).
    assert math.isclose(r.ai_acceptable_pct, 1.0)
    assert r.acceptable_ci_low == 1.0 and r.acceptable_ci_high == 1.0


def test_confidence_interval_narrows_as_n_grows():
    widths = []
    for n in (10, 100, 1000):
        r = aggregate_preference(_balanced(n))
        assert r.total == n
        assert math.isclose(r.ai_acceptable_pct, 0.5)
        assert math.isclose(r.ai_preferred_pct, 0.5)
        widths.append(r.acceptable_ci_high - r.acceptable_ci_low)
    assert widths[0] > widths[1] > widths[2]


def test_confidence_interval_formula_value():
    # p = 0.5, n = 100 -> 0.5 ± 1.96·sqrt(0.25/100) = 0.5 ± 0.098.
    r = aggregate_preference(_balanced(100))
    assert math.isclose(r.acceptable_ci_low, 0.402, abs_tol=1e-3)
    assert math.isclose(r.acceptable_ci_high, 0.598, abs_tol=1e-3)


def test_confidence_interval_clamped_to_unit_interval():
    # High proportion: 9 AI / 1 human -> 0.9, upper bound would exceed 1.0.
    high = [_vote("A", 1)] * 9 + [_vote("A", 0)] * 1
    r = aggregate_preference(high)
    assert math.isclose(r.ai_acceptable_pct, 0.9)
    assert r.acceptable_ci_high == 1.0  # clamped
    assert 0.7 < r.acceptable_ci_low < 0.9
    # Low proportion: 1 AI / 9 human -> 0.1, lower bound would go negative.
    low = [_vote("A", 1)] * 1 + [_vote("A", 0)] * 9
    r = aggregate_preference(low)
    assert math.isclose(r.ai_acceptable_pct, 0.1)
    assert r.acceptable_ci_low == 0.0  # clamped
    assert 0.1 < r.acceptable_ci_high < 0.3


def test_filter_by_prompt_version_and_all_sentinel():
    votes = [
        _vote("A", 1, prompt_version="v1"),
        _vote("A", 1, prompt_version="v2"),
        _vote("B", 1, prompt_version="v2"),  # human win
    ]
    assert aggregate_preference(votes, {"prompt_version": "v1"}).total == 1
    r_v2 = aggregate_preference(votes, {"prompt_version": "v2"})
    assert (r_v2.ai_wins, r_v2.human_wins, r_v2.total) == (1, 1, 2)
    assert aggregate_preference(votes, {"prompt_version": "__all__"}).total == 3
    assert aggregate_preference(votes, {}).total == 3  # absent key -> no filter


def test_filter_multi_dimension_is_and():
    votes = [
        _vote("A", 1, prompt_version="v1", alert_category="health"),
        _vote("A", 1, prompt_version="v1", alert_category="abuse"),
        _vote("A", 1, prompt_version="v2", alert_category="health"),
    ]
    r = aggregate_preference(votes, {"prompt_version": "v1", "alert_category": "health"})
    assert r.total == 1  # only the row matching BOTH


def test_filter_by_translator_and_letter():
    votes = [
        _vote("A", 1, translator_id=1, letter_id=10),
        _vote("A", 1, translator_id=2, letter_id=10),
        _vote("A", 1, translator_id=1, letter_id=20),
    ]
    assert aggregate_preference(votes, {"translator_id": 1}).total == 2
    assert aggregate_preference(votes, {"letter_id": 10}).total == 2
    assert aggregate_preference(votes, {"translator_id": 1, "letter_id": 20}).total == 1
