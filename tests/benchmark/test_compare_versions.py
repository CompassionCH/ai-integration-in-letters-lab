"""Tests for the prompt-version comparison helper.

All data is fictional and generated in-test (no real corpus/results). Scorecard maths
is reused from benchmark.report (tested in test_report.py); here we cover the new logic:
version discovery across roots, the intersection-only change diff, and the honest-coverage
scorecard (a partial run is scored only over the letters it processed).
"""
import json
from pathlib import Path

from data.corpus import load_corpus
from benchmark.compare_versions import (
    discover_versions, changes_between, version_scorecard, version_preds,
)


# --------------------------------------------------------------------------- fixtures

def _write_flat(vdir: Path, letter_id, *, category, cost=0.01, model="gemini-x", strategy="F"):
    """Write one flat production result (run_gemini envelope) under a version dir."""
    vdir.mkdir(parents=True, exist_ok=True)
    rec = {
        "letter_id": letter_id, "prompt_version": vdir.name, "model": model, "strategy": strategy,
        "translations": [{"sequence": 1, "text": "x"}],
        "alert": {"category": category, "reason": ""},
        "tokens_in": 10, "tokens_out": 5, "cost_usd": cost, "safety_filter_status": "ok",
    }
    (vdir / f"{letter_id}.json").write_text(json.dumps(rec), encoding="utf-8")


def _letter(lid, *, gold=None, type_="synthetic"):
    return {
        "id": lid, "type": type_, "pdf_path": f"x/{lid}.pdf", "direction": "sponsor_to_child",
        "translation_queue": {"source": "de", "target": "en"}, "country": "X",
        "child": {"official_first_name": "A", "preferred_first_name": "A", "sex": "F", "age": 9},
        "sponsor": {"first_name": "B", "other_sponsored_first_names": [], "sex": "M", "age": 40},
        "page_level": {"original_text": None, "english_text": None, "translated_text": None},
        "paragraphs": None, "human_translation": None, "human_translation_origin_field": None,
        "ground_truth": ({"expected_category": gold, "rationale": "r", "source_letter_id": None} if gold else None),
        "notes": None,
    }


def _write_corpus(tmp_path, letters):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps({"version": 2, "letters": letters}), encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------------- discovery

def test_discover_versions_across_roots(tmp_path):
    r1, r2 = tmp_path / "results", tmp_path / "archive"
    _write_flat(r1 / "v4", "S-1", category="no_alert")
    _write_flat(r2 / "v2", "S-1", category="no_alert")
    _write_flat(r2 / "v3", "S-1", category="no_alert")
    v = discover_versions([str(r1), str(r2)])
    assert list(v) == ["v2", "v3", "v4"]          # sorted by name, merged across roots
    assert v["v4"] == r1 / "v4"
    assert v["v2"] == r2 / "v2"


def test_discover_versions_first_root_wins_on_collision(tmp_path):
    r1, r2 = tmp_path / "results", tmp_path / "archive"
    _write_flat(r1 / "v2", "S-1", category="no_alert")
    _write_flat(r2 / "v2", "S-1", category="no_alert")
    v = discover_versions([str(r1), str(r2)])
    assert v["v2"] == r1 / "v2"                    # first root wins


def test_discover_versions_skips_dirs_without_results(tmp_path):
    r = tmp_path / "results"
    _write_flat(r / "v2", "S-1", category="no_alert")
    (r / "empty").mkdir(parents=True)
    (r / "failed").mkdir()
    (r / "failed" / "_failures.jsonl").write_text("{}\n", encoding="utf-8")
    assert list(discover_versions([str(r)])) == ["v2"]


# --------------------------------------------------------------------------- change diff

def test_changes_between_intersection_only():
    old = {"a": "no_alert", "b": "child_protection", "c": "no_alert"}
    new = {"a": "content_inappropriate", "b": "child_protection", "d": "no_alert"}
    # a flipped; b unchanged; c only in old; d only in new -> only 'a' is a change
    assert changes_between(old, new) == [("a", "no_alert", "content_inappropriate")]


def test_changes_between_none_when_identical():
    p = {"a": "no_alert", "b": "child_protection"}
    assert changes_between(p, dict(p)) == []


# --------------------------------------------------------------------------- scorecard (honest coverage)

def test_version_scorecard_scores_only_covered_letters(tmp_path):
    # 2 gold letters, but this version processed only 1 (correctly): recall must be 1.0,
    # n must be 1 — the uncovered gold letter is NOT counted as a miss.
    corpus = load_corpus(_write_corpus(tmp_path, [
        _letter("SI-1", gold="content_inappropriate"),
        _letter("SI-2", gold="content_inappropriate"),
    ]))
    vdir = tmp_path / "results" / "v4"
    _write_flat(vdir, "SI-1", category="content_inappropriate", cost=0.02)
    s = version_scorecard(corpus, vdir)
    assert s["coverage"] == 1
    assert s["n"] == 1
    assert s["recall"] == 1.0 and s["precision"] == 1.0
    assert (s["tp"], s["fn"], s["fp"]) == (1, 0, 0)
    assert s["cost"] == 0.02


def test_version_scorecard_counts_miss_within_coverage(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_letter("SI-1", gold="content_inappropriate")]))
    vdir = tmp_path / "results" / "v4"
    _write_flat(vdir, "SI-1", category="no_alert")     # covered gold letter, wrongly no_alert
    s = version_scorecard(corpus, vdir)
    assert s["n"] == 1 and s["recall"] == 0.0 and s["fn"] == 1


def test_version_preds_maps_id_to_category(tmp_path):
    vdir = tmp_path / "results" / "v4"
    _write_flat(vdir, "SI-1", category="content_inappropriate")
    _write_flat(vdir, "R-1", category="no_alert")
    assert version_preds(vdir) == {"SI-1": "content_inappropriate", "R-1": "no_alert"}
