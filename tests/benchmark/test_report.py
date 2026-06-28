"""Tests for the benchmark report's view-model assembly.

All data here is fictional and generated in-test; these tests never touch the
real corpus or result files. The HTML render layer is UI and is not unit-tested
(per the task contract) — only the corpus + result-files -> per-letter structure
assembly is covered here, including the missing-result case and the
gold-vs-predicted verdict.
"""
import json
from pathlib import Path

from data.corpus import load_corpus
from benchmark.report import build_report, _render_pdf, LetterView


# --------------------------------------------------------------------------- builders

def _valid_letter(letter_id="R-001", **overrides):
    """A minimal valid (fictional) letter dict; override any field via kwargs."""
    letter = {
        "id": letter_id,
        "type": "real",
        "pdf_path": f"real/{letter_id}.pdf",
        "direction": "child_to_sponsor",
        "translation_queue": {"source": "en", "target": "fr"},
        "country": "Testland",
        "child": {"official_first_name": "Mira", "preferred_first_name": "Mira", "sex": "F", "age": 9},
        "sponsor": {"first_name": "Tom", "other_sponsored_first_names": [], "sex": "M", "age": 40},
        "page_level": {"original_text": "Dear Tom.", "english_text": "Dear Tom.", "translated_text": "Cher Tom."},
        "paragraphs": None,
        "human_translation": None,
        "human_translation_origin_field": None,
        "ground_truth": None,
        "notes": None,
    }
    letter.update(overrides)
    return letter


def _gold_letter(letter_id="S-001", *, category="child_protection", rationale="injected issue"):
    """A synthetic letter carrying ground truth (no human translation)."""
    return _valid_letter(
        letter_id,
        type="synthetic",
        human_translation=None,
        ground_truth={"expected_category": category, "rationale": rationale, "source_letter_id": None},
    )


def _para(sequence, source_text="src", human_translation=None):
    return {
        "page_index": 0,
        "sequence": sequence,
        "source_text": source_text,
        "human_translation": human_translation,
        "comments": None,
    }


def _write_corpus(tmp_path, letters, version=2):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"version": version, "letters": letters}), encoding="utf-8")
    return str(path)


def _write_result(results_dir, model, strategy, letter_id, *,
                  translations=None, category=None, reason="", telemetry=None):
    """Write a result file in the layout benchmark.run produces.

    `translations` is a list of (sequence, text) tuples (order preserved on disk).
    `category` None omits the alert block entirely; `telemetry` None omits it.
    """
    dest = Path(results_dir) / model / strategy
    dest.mkdir(parents=True, exist_ok=True)
    response = {}
    if translations is not None:
        response["translations"] = [{"sequence": s, "text": t} for s, t in translations]
    if category is not None:
        response["alert"] = {"category": category, "reason": reason}
    record = {"letter_id": letter_id, "strategy": strategy, "model": model, "response": response}
    if telemetry is not None:
        record["telemetry"] = telemetry
    (dest / f"{letter_id}.json").write_text(json.dumps(record), encoding="utf-8")


# --------------------------------------------------------------------------- cell parsing

def test_cell_found_parses_translations_alert_telemetry(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter("R-001")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "R-001",
                  translations=[(1, "Bonjour"), (2, "Au revoir")],
                  category="no_alert", reason="ok",
                  telemetry={"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.01})
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.found is True
    assert cell.translations == {1: "Bonjour", 2: "Au revoir"}
    assert cell.alert_category == "no_alert"
    assert cell.alert_reason == "ok"
    assert cell.telemetry == {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.01}


def test_missing_result_cell_is_no_result(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter("R-001")]))
    rd = tmp_path / "results"  # nothing written; dir does not even exist
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.found is False
    assert cell.translations == {}
    assert cell.alert_category is None
    assert cell.alert_reason is None
    assert cell.telemetry is None


# --------------------------------------------------------------------------- verdicts (reuse score_screening.tally)

def test_verdict_exact(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter(category="child_protection")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category="child_protection")
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.verdict == "exact"
    assert cell.verdict_class == "pass"


def test_verdict_wrong_category(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter(category="child_protection")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category="content_inappropriate")
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.verdict == "wrong_category"
    assert cell.verdict_class == "partial"


def test_verdict_missed_pred_no_alert(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter(category="child_protection")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category="no_alert")
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.verdict == "missed"
    assert cell.verdict_class == "fail"


def test_verdict_missed_when_result_missing(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter(category="child_protection")]))
    rd = tmp_path / "results"  # no file -> pred None -> missed (FN)
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.found is False
    assert cell.verdict == "missed"
    assert cell.verdict_class == "fail"


def test_verdict_false_alarm(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter(category="no_alert")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category="child_protection")
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.verdict == "false_alarm"
    assert cell.verdict_class == "fail"


def test_verdict_correct_no_alert(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter(category="no_alert")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category="no_alert")
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.verdict == "correct_no_alert"
    assert cell.verdict_class == "pass"


def test_verdict_neutral_when_no_gold(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter("R-001")]))  # ground_truth None
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "R-001", translations=[(1, "x")], category="no_alert")
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.verdict is None
    assert cell.verdict_class == "neutral"


# --------------------------------------------------------------------------- paragraph alignment (model columns)

def test_aligned_rows_union_and_sort_across_models(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter("R-001")]))
    rd = tmp_path / "results"
    # out of order, and the two models cover different sequence sets
    _write_result(rd, "m1", "F", "R-001", translations=[(3, "a3"), (1, "a1")], category="no_alert")
    _write_result(rd, "m2", "F", "R-001", translations=[(2, "b2"), (1, "b1")], category="no_alert")
    lv = build_report(corpus, rd, ["m1", "m2"], ["F"]).letters[0]
    assert [r.sequence for r in lv.rows] == [1, 2, 3]
    rows = {r.sequence: r for r in lv.rows}
    assert rows[1].cell_texts == {"m1/F": "a1", "m2/F": "b1"}
    assert rows[2].cell_texts == {"m1/F": None, "m2/F": "b2"}  # m1 has no seq 2
    assert rows[3].cell_texts == {"m1/F": "a3", "m2/F": None}  # m2 has no seq 3


def test_human_reference_block_is_carried(tmp_path):
    letter = _valid_letter("R-001", human_translation="Cher Tom\n\nBody")
    corpus = load_corpus(_write_corpus(tmp_path, [letter]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "R-001", translations=[(1, "uno")], category="no_alert")
    lv = build_report(corpus, rd, ["m1"], ["F"]).letters[0]
    assert lv.human_translation == "Cher Tom\n\nBody"
    # rows align model cells only; the human reference is a block, not a table column
    assert [r.sequence for r in lv.rows] == [1]
    assert lv.rows[0].cell_texts == {"m1/F": "uno"}


def test_rows_ignore_human_paragraph_sequences(tmp_path):
    # Regression: the real corpus keys every human paragraph at sequence 0 while models
    # output 1..N. Human paragraphs must not create or collapse the aligned rows.
    paragraphs = [_para(0, human_translation="page one"), _para(0, human_translation="page two")]
    letter = _valid_letter("R-001", paragraphs=paragraphs, human_translation="page one\n\npage two")
    corpus = load_corpus(_write_corpus(tmp_path, [letter]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "R-001", translations=[(1, "uno"), (2, "due")], category="no_alert")
    lv = build_report(corpus, rd, ["m1"], ["F"]).letters[0]
    assert [r.sequence for r in lv.rows] == [1, 2]  # driven by model sequences, not the seq-0 human paras
    assert lv.human_translation == "page one\n\npage two"


def test_synthetic_no_human_carries_rationale(tmp_path):
    letter = _gold_letter("S-001", category="child_protection", rationale="injected visit invite")
    corpus = load_corpus(_write_corpus(tmp_path, [letter]))
    lv = build_report(corpus, tmp_path / "results", ["m1"], ["F"]).letters[0]
    assert lv.human_translation is None
    assert lv.gold_category == "child_protection"
    assert lv.rationale == "injected visit invite"


# --------------------------------------------------------------------------- run summary + top-level

def test_report_summary_recall_precision_and_missed_list(tmp_path):
    letters = [
        _gold_letter("S-001", category="child_protection"),  # caught -> TP
        _gold_letter("S-002", category="child_protection"),  # missed -> FN
        _gold_letter("S-003", category="no_alert"),          # flagged -> FP
    ]
    corpus = load_corpus(_write_corpus(tmp_path, letters))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category="child_protection")
    _write_result(rd, "m1", "F", "S-002", translations=[(1, "x")], category="no_alert")
    _write_result(rd, "m1", "F", "S-003", translations=[(1, "x")], category="child_protection")
    report = build_report(corpus, rd, ["m1"], ["F"])
    assert report.has_ground_truth is True
    d = report.summary["m1/F"]["detection"]
    assert (d["tp"], d["fn"], d["fp"]) == (1, 1, 1)
    assert d["recall"] == 1 / 2
    assert d["precision"] == 1 / 2
    assert [i for i, _, _ in report.summary["m1/F"]["false_negatives"]] == ["S-002"]


def test_report_no_ground_truth_has_empty_summary(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter("R-001"), _valid_letter("R-002")]))
    report = build_report(corpus, tmp_path / "results", ["m1"], ["F"])
    assert report.has_ground_truth is False
    assert report.summary == {}


def test_report_top_level_counts(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter("R-001"), _valid_letter("R-002")]))
    report = build_report(corpus, tmp_path / "results", ["m1", "m2"], ["F"])
    assert report.letter_count == 2
    assert report.models == ["m1", "m2"]
    assert report.strategies == ["F"]
    assert len(report.letters[0].cells) == 2  # 2 models x 1 strategy


def test_multiple_strategies_keep_predictions_separate(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter("S-001", category="child_protection")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "A", "S-001", translations=[(1, "x")], category="child_protection")  # exact
    _write_result(rd, "m1", "D", "S-001", translations=[(1, "x")], category="no_alert")          # missed
    report = build_report(corpus, rd, ["m1"], ["A", "D"])
    cells = {(c.model, c.strategy): c for c in report.letters[0].cells}
    assert cells[("m1", "A")].verdict == "exact"
    assert cells[("m1", "D")].verdict == "missed"
    assert set(report.summary.keys()) == {"m1/A", "m1/D"}


def test_result_without_alert_block_does_not_crash(tmp_path):
    # response with translations but no alert key -> pred None
    corpus = load_corpus(_write_corpus(tmp_path, [_gold_letter("S-001", category="child_protection")]))
    rd = tmp_path / "results"
    _write_result(rd, "m1", "F", "S-001", translations=[(1, "x")], category=None)
    cell = build_report(corpus, rd, ["m1"], ["F"]).letters[0].cells[0]
    assert cell.found is True
    assert cell.alert_category is None
    assert cell.verdict == "missed"  # gold alert, no prediction -> FN


# --------------------------------------------------------------------------- PDF render mode (link vs embed)

def _letterview(pdf_path):
    """Minimal LetterView for exercising _render_pdf directly (metadata unused when pdf_path is set)."""
    return LetterView(id="R-001", metadata=None, pdf_path=pdf_path, human_translation=None,
                      gold_category=None, rationale=None, rows=[], cells=[])


def test_render_pdf_link_mode_uses_relative_path():
    out = _render_pdf(_letterview("letters/real/R-001.pdf"), True, "link", Path("benchmark/results/full"))
    assert "data:" not in out                          # no base64 blob in the file
    assert "../../../letters/real/R-001.pdf" in out     # relative path from out_dir to the PDF


def test_render_pdf_embed_mode_inlines_base64(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 test bytes")
    out = _render_pdf(_letterview(str(pdf)), True, "embed", tmp_path)
    assert "src='data:application/pdf;base64," in out
