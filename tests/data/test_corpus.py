"""Tests for the corpus.json schema + loader.

All data here is fictional and generated in-test or read from a committed
fictional fixture; these tests never touch the real letters/corpus.json.
"""
import json
import logging
from pathlib import Path

import pytest

from data.corpus import LetterMetadata, load_corpus

FIXTURE = Path(__file__).parent.parent / "fixtures" / "corpus_sample.json"


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


def _write_corpus(tmp_path, letters, version=2):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"version": version, "letters": letters}), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("size", [1, 10, 40])
def test_loads_corpus_of_size(tmp_path, size):
    letters = [_valid_letter(letter_id=f"R-{i:03d}") for i in range(size)]
    corpus = load_corpus(_write_corpus(tmp_path, letters))
    assert len(corpus) == size
    assert all(isinstance(item, LetterMetadata) for item in corpus)


def test_committed_fixture_loads():
    corpus = load_corpus(str(FIXTURE))
    assert len(corpus) == 3


def test_ground_truth_null_on_real_ok(tmp_path):
    corpus = load_corpus(_write_corpus(tmp_path, [_valid_letter(ground_truth=None)]))
    assert corpus[0].ground_truth is None


def test_ground_truth_absent_on_real_ok(tmp_path):
    letter = _valid_letter()
    del letter["ground_truth"]
    corpus = load_corpus(_write_corpus(tmp_path, [letter]))
    assert corpus[0].ground_truth is None


def test_synthetic_missing_human_translation_ok(tmp_path):
    letter = _valid_letter(
        letter_id="S-001",
        type="synthetic",
        human_translation=None,
        ground_truth={"expected_category": "no_alert", "rationale": "x", "source_letter_id": "R-001"},
    )
    corpus = load_corpus(_write_corpus(tmp_path, [letter]))
    assert corpus[0].human_translation is None


def test_queue_lang_outside_set_rejected(tmp_path):
    letter = _valid_letter(translation_queue={"source": "sw", "target": "fr"})
    with pytest.raises(ValueError) as exc:
        load_corpus(_write_corpus(tmp_path, [letter]))
    msg = str(exc.value)
    assert "R-001" in msg
    assert "sw" in msg or "source" in msg


def test_missing_pdf_path_rejected(tmp_path):
    letter = _valid_letter()
    del letter["pdf_path"]
    with pytest.raises(ValueError) as exc:
        load_corpus(_write_corpus(tmp_path, [letter]))
    msg = str(exc.value)
    assert "R-001" in msg
    assert "pdf_path" in msg


def test_other_sponsored_over_16_warns_not_rejects(tmp_path, caplog):
    sponsor = {
        "first_name": "Tom",
        "other_sponsored_first_names": [f"Name{i}" for i in range(17)],
        "sex": "M",
        "age": 40,
    }
    letter = _valid_letter(sponsor=sponsor)
    with caplog.at_level(logging.WARNING):
        corpus = load_corpus(_write_corpus(tmp_path, [letter]))
    assert len(corpus) == 1  # warned, not rejected
    assert "R-001" in caplog.text


def test_issue_letter_can_be_real_or_synthetic(tmp_path):
    gt = {"expected_category": "child_protection", "rationale": "x", "source_letter_id": None}
    real_issue = _valid_letter(letter_id="I-001", type="real", ground_truth=gt)
    synth_issue = _valid_letter(
        letter_id="I-002", type="synthetic", human_translation=None, ground_truth=gt
    )
    corpus = load_corpus(_write_corpus(tmp_path, [real_issue, synth_issue]))
    assert {item.type for item in corpus} == {"real", "synthetic"}
    assert all(item.id.startswith("I-") for item in corpus)


def test_empty_corpus_returns_empty_list(tmp_path):
    assert load_corpus(_write_corpus(tmp_path, [])) == []


def test_missing_letters_key_rejected(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"version": 2}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_corpus(str(path))
