"""Tests for the pre-processing result loader (data layer).

Self-contained: each test builds a fictional corpus + result files in tmp_path and
loads into a fresh temp DB. No real corpus/results, no network.
"""
import json
from pathlib import Path

from db import connect
from db.init import init_db
from pre_processing.load_results import load, display_ref, clean_block, join_translations


# --------------------------------------------------------------------------- builders

def _letter(lid, *, ltype="real", human: "str | None" = "Hello\n#PAGE#\nWorld", gt=None, paras=None):
    return {
        "id": lid, "type": ltype, "pdf_path": f"real/{lid}.pdf", "direction": "child_to_sponsor",
        "translation_queue": {"source": "en", "target": "fr"}, "country": "Testland",
        "child": {"official_first_name": "Mira", "preferred_first_name": "Mira", "sex": "F", "age": 9},
        "sponsor": {"first_name": "Tom", "other_sponsored_first_names": [], "sex": "M", "age": 40},
        "page_level": {"original_text": "x", "english_text": "x", "translated_text": "x"},
        "paragraphs": paras, "human_translation": human, "human_translation_origin_field": None,
        "ground_truth": gt, "notes": None,
    }


def _para(seq, src="src", human=None):
    return {"page_index": 0, "sequence": seq, "source_text": src, "human_translation": human, "comments": None}


def _record(lid, *, version="v1", model="m1", translations=None, category="no_alert", safety="ok"):
    return {"letter_id": lid, "prompt_version": version, "model": model,
            "translations": translations if translations is not None else [{"sequence": 1, "text": "Bonjour"}],
            "alert": {"category": category, "reason": "r"}, "tokens_in": 100, "tokens_out": 50,
            "cost_usd": 0.01, "safety_filter_status": safety, "processed_at": "2026-01-01T00:00:00Z"}


def _write_corpus(tmp_path, letters):
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps({"version": 2, "letters": letters}), encoding="utf-8")
    return str(p)


def _write_result(root, version, record):
    d = Path(root) / version
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{record['letter_id']}.json").write_text(json.dumps(record), encoding="utf-8")


def _fresh_db(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    return db


# --------------------------------------------------------------------------- pure transforms

def test_display_ref_deterministic_and_8_chars():
    assert display_ref("R-002") == display_ref("R-002")
    assert len(display_ref("R-002")) == 8
    assert display_ref("R-002") != display_ref("R-003")


def test_clean_block_pagebreak_and_empty():
    out = clean_block("Hello\n#PAGE#\nWorld")
    assert "#PAGE#" not in out and "Hello" in out and "World" in out
    assert clean_block(None) is None
    assert clean_block("   ") is None


def test_join_translations_orders_by_sequence():
    assert join_translations([{"sequence": 2, "text": "B"}, {"sequence": 1, "text": "A"}]) == "A\n\nB"


# --------------------------------------------------------------------------- load

def test_load_empty_results(tmp_path):
    db = _fresh_db(tmp_path)
    corpus = _write_corpus(tmp_path, [_letter("R-001")])
    counts = load(db, [corpus], str(tmp_path / "results"))  # results dir does not exist
    assert counts == {"letters": 1, "responses": 0, "skipped": []}
    conn = connect(db)
    human = conn.execute("SELECT human_translation_text FROM letters").fetchone()[0]
    assert "#PAGE#" not in human  # normalized
    conn.close()


def test_load_letters_responses_and_paragraphs(tmp_path):
    db = _fresh_db(tmp_path)
    corpus = _write_corpus(tmp_path, [
        _letter("R-001", paras=[_para(0, human="H1")]),
        _letter("S-001", ltype="synthetic", human=None,
                gt={"expected_category": "child_protection", "rationale": "x", "source_letter_id": None}),
    ])
    root = str(tmp_path / "results")
    _write_result(root, "v1", _record("R-001", translations=[{"sequence": 1, "text": "A"}, {"sequence": 2, "text": "B"}]))
    _write_result(root, "v1", _record("S-001", category="child_protection"))
    counts = load(db, [corpus], root)
    assert counts["letters"] == 2 and counts["responses"] == 2 and counts["skipped"] == []
    conn = connect(db)
    tt = conn.execute(
        "SELECT translation_text FROM ai_responses ar JOIN letters l ON ar.letter_id=l.id WHERE l.display_ref=?",
        (display_ref("R-001"),)).fetchone()[0]
    assert tt == "A\n\nB"  # joined for A/B parity
    syn_human = conn.execute("SELECT human_translation_text FROM letters WHERE display_ref=?",
                             (display_ref("S-001"),)).fetchone()[0]
    assert syn_human is None  # synthetic -> no human ref -> no A/B card
    assert conn.execute("SELECT COUNT(*) FROM ai_response_paragraphs").fetchone()[0] == 3  # 2 + 1
    assert conn.execute("SELECT ground_truth_category FROM letters WHERE display_ref=?",
                        (display_ref("S-001"),)).fetchone()[0] == "child_protection"
    # corpus id persisted verbatim (admin views map the opaque ref back to R-/S- ids)
    assert conn.execute("SELECT corpus_id FROM letters WHERE display_ref=?",
                        (display_ref("S-001"),)).fetchone()[0] == "S-001"
    conn.close()


def test_load_is_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    corpus = _write_corpus(tmp_path, [_letter("R-001")])
    root = str(tmp_path / "results")
    _write_result(root, "v1", _record("R-001"))
    load(db, [corpus], root)
    load(db, [corpus], root)  # re-run must not duplicate
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM letters").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ai_responses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ai_response_paragraphs").fetchone()[0] == 1
    conn.close()


def test_skips_result_without_matching_letter(tmp_path):
    db = _fresh_db(tmp_path)
    corpus = _write_corpus(tmp_path, [_letter("R-001")])
    root = str(tmp_path / "results")
    _write_result(root, "v1", _record("R-001"))
    _write_result(root, "v1", _record("UNKNOWN-99"))
    counts = load(db, [corpus], root)
    assert counts["responses"] == 1
    assert any("UNKNOWN-99" in s for s in counts["skipped"])
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM ai_responses").fetchone()[0] == 1
    conn.close()


def test_multiple_prompt_versions_coexist(tmp_path):
    db = _fresh_db(tmp_path)
    corpus = _write_corpus(tmp_path, [_letter("R-001")])
    root = str(tmp_path / "results")
    _write_result(root, "v1", _record("R-001", version="v1"))
    _write_result(root, "v2", _record("R-001", version="v2"))
    counts = load(db, [corpus], root)
    assert counts["responses"] == 2
    conn = connect(db)
    versions = {r[0] for r in conn.execute("SELECT prompt_version FROM ai_responses")}
    assert versions == {"v1", "v2"}
    conn.close()
