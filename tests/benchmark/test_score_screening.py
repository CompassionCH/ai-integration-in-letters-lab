"""Unit tests for the screening scorecard's pure scoring logic."""
from benchmark.score_screening import tally


def test_tally_detection_accuracy_and_lists():
    rows = [
        ("a", "child_protection", "child_protection"),       # TP, exact
        ("b", "content_inappropriate", "child_protection"),  # TP, wrong category
        ("c", "child_protection", "no_alert"),               # FN (missed alert)
        ("d", "no_alert", "no_alert"),                        # TN
        ("e", "no_alert", "content_inappropriate"),          # FP (false alarm)
        ("f", "wrong_language", None),                        # FN (no result file)
    ]
    r = tally(rows)
    assert r["n"] == 6
    d = r["detection"]
    assert (d["tp"], d["fn"], d["fp"], d["tn"]) == (2, 2, 1, 1)
    assert r["exact_accuracy"] == 2 / 6
    assert d["recall"] == 2 / 4
    assert d["precision"] == 2 / 3
    assert d["specificity"] == 1 / 2
    assert sorted(i for i, _, _ in r["false_negatives"]) == ["c", "f"]
    assert [i for i, _ in r["false_positives"]] == ["e"]
    assert [i for i, _, _ in r["category_mismatches"]] == ["b"]
    assert r["per_category"]["child_protection"] == {"n": 2, "caught": 1, "exact": 1}


def test_tally_ignores_rows_without_gold():
    r = tally([("x", None, "child_protection"), ("y", "no_alert", "no_alert")])
    assert r["n"] == 1  # only the row carrying a gold category is scored


def test_tally_empty():
    r = tally([])
    assert r["n"] == 0
    assert r["exact_accuracy"] is None
    assert r["detection"]["recall"] is None
