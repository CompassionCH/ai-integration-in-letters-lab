"""Tests for analysis.ground_truth — AI alert detection vs corpus labels (pure)."""
from __future__ import annotations

from analysis.ground_truth import (
    CategoryScore,
    FpTrap,
    GroundTruthReport,
    LetterOutcome,
    score_ground_truth,
)


def _letter(letter_id, ground_truth_category):
    return {"id": letter_id, "ground_truth_category": ground_truth_category}


def _resp(letter_id, alert_category, *, prompt_version="v1"):
    return {
        "letter_id": letter_id,
        "alert_category": alert_category,
        "prompt_version": prompt_version,
    }


def test_true_positive():
    r = score_ground_truth([_letter(1, "abuse")], [_resp(1, "abuse")])
    assert r.per_category == {"abuse": CategoryScore(tp=1)}
    assert r.fp_trap == FpTrap(0, 0)
    assert r.per_letter_detail == [LetterOutcome(1, "abuse", "abuse", "v1")]


def test_false_negative_when_emitted_no_alert():
    r = score_ground_truth([_letter(1, "abuse")], [_resp(1, None)])
    assert r.per_category == {"abuse": CategoryScore(fn=1)}
    assert r.per_letter_detail == [LetterOutcome(1, "abuse", "no_alert", "v1")]


def test_wrong_category_bucket():
    r = score_ground_truth([_letter(1, "abuse")], [_resp(1, "neglect")])
    assert r.per_category == {"abuse": CategoryScore(wrong_category=1)}


def test_fp_trap_passed_with_none_and_literal_string():
    letters = [_letter(1, "no_alert"), _letter(2, "no_alert")]
    resps = [_resp(1, None), _resp(2, "no_alert")]
    r = score_ground_truth(letters, resps)
    assert r.fp_trap == FpTrap(passed=2, failed=0)
    assert r.per_category == {}


def test_fp_trap_failed():
    r = score_ground_truth([_letter(1, "no_alert")], [_resp(1, "abuse")])
    assert r.fp_trap == FpTrap(passed=0, failed=1)


def test_clean_letters_without_ground_truth_skipped():
    r = score_ground_truth([_letter(2, None)], [_resp(2, "abuse")])
    assert r.per_category == {}
    assert r.fp_trap == FpTrap(0, 0)
    assert r.per_letter_detail == []


def test_letter_without_response_not_scored():
    r = score_ground_truth([_letter(1, "abuse")], [])
    assert r.per_category == {}
    assert r.per_letter_detail == []


def test_empty_input():
    r = score_ground_truth([], [])
    assert r == GroundTruthReport(per_category={}, fp_trap=FpTrap(0, 0), per_letter_detail=[])


def test_mixed_corpus():
    letters = [
        _letter(1, "abuse"),     # TP
        _letter(2, "abuse"),     # FN
        _letter(3, "neglect"),   # wrong-category
        _letter(4, "no_alert"),  # trap passed
        _letter(5, "no_alert"),  # trap failed
        _letter(6, None),        # clean -> skipped
    ]
    resps = [
        _resp(1, "abuse"),
        _resp(2, None),
        _resp(3, "abuse"),
        _resp(4, None),
        _resp(5, "neglect"),
        _resp(6, "abuse"),       # response for a clean letter -> skipped
    ]
    r = score_ground_truth(letters, resps)
    assert r.per_category == {
        "abuse": CategoryScore(tp=1, fn=1),
        "neglect": CategoryScore(wrong_category=1),
    }
    assert r.fp_trap == FpTrap(passed=1, failed=1)
    assert len(r.per_letter_detail) == 5  # the clean letter is absent from detail


def test_prompt_version_filter_and_all_sentinel():
    letters = [_letter(1, "abuse")]
    resps = [_resp(1, "abuse", prompt_version="v1"), _resp(1, None, prompt_version="v2")]
    assert score_ground_truth(letters, resps, {"prompt_version": "v1"}).per_category == {
        "abuse": CategoryScore(tp=1)
    }
    assert score_ground_truth(letters, resps, {"prompt_version": "v2"}).per_category == {
        "abuse": CategoryScore(fn=1)
    }
    # "__all__" scores each version -> tp AND fn for the same letter, two detail rows.
    r_all = score_ground_truth(letters, resps, {"prompt_version": "__all__"})
    assert r_all.per_category == {"abuse": CategoryScore(tp=1, fn=1)}
    assert len(r_all.per_letter_detail) == 2
    assert score_ground_truth(letters, resps, {}).per_category == {"abuse": CategoryScore(tp=1, fn=1)}
