"""Tests for the production pre-compute runner's pure logic (parser, cost, record).

The Gemini SDK call is mocked; these tests touch no network, no key, and no real
corpus/result files. Per the task contract, TDD covers the parser + cost computation;
the SDK call itself is mocked.
"""
from types import SimpleNamespace

import pytest

from pre_processing.run_gemini import (
    compute_cost, parse_response, build_record, safety_record, process_letter,
)

VALID = ('{"translations": [{"sequence": 1, "text": "Bonjour"}], '
         '"alert": {"category": "no_alert", "reason": "ok"}}')


# --------------------------------------------------------------------------- parser

def test_parse_response_valid():
    r = parse_response(VALID)
    assert r["translations"] == [{"sequence": 1, "text": "Bonjour"}]
    assert r["alert"]["category"] == "no_alert"


def test_parse_response_malformed_raises():
    with pytest.raises(ValueError):
        parse_response("not json {")


def test_parse_response_missing_keys_raises():
    with pytest.raises(ValueError):
        parse_response('{"translations": []}')  # no alert block


def test_parse_response_empty_raises():
    with pytest.raises(ValueError):
        parse_response("")


# --------------------------------------------------------------------------- cost

def test_compute_cost_known_tokens():
    # gemini-3.5-flash = 1.50 in / 9.00 out per Mtok (pre_processing/pricing.json)
    assert compute_cost("gemini-3.5-flash", 1_000_000, 1_000_000) == pytest.approx(10.50)
    assert compute_cost("gemini-3.5-flash", 0, 0) == 0.0


def test_compute_cost_unknown_model_raises():
    with pytest.raises(KeyError):
        compute_cost("no-such-model", 10, 10)


# --------------------------------------------------------------------------- records

def test_build_record_shape_and_cost():
    rec = build_record("R-001", "v1", "gemini-3.5-flash", parse_response(VALID),
                       1_000_000, 1_000_000, "2026-01-01T00:00:00Z")
    assert rec["letter_id"] == "R-001"
    assert rec["prompt_version"] == "v1"
    assert rec["safety_filter_status"] == "ok"
    assert rec["alert"]["category"] == "no_alert"
    assert rec["cost_usd"] == pytest.approx(10.50)


def test_safety_record_synthesizes_blocked():
    rec = safety_record("R-002", "v1", "gemini-3.5-flash", "2026-01-01T00:00:00Z")
    assert rec["alert"]["category"] == "safety_filter_triggered"
    assert rec["safety_filter_status"] == "blocked"
    assert rec["translations"] == []
    assert rec["cost_usd"] == 0.0


# --------------------------------------------------------------------------- process_letter (SDK mocked)

def test_process_letter_success(monkeypatch):
    import pre_processing.run_gemini as m
    resp = SimpleNamespace(text=VALID, usage_metadata=SimpleNamespace(
        prompt_token_count=100, candidates_token_count=40, thoughts_token_count=10))
    monkeypatch.setattr(m, "_call", lambda client, letter, model, prompt_version, temperature: resp)
    rec = process_letter(None, SimpleNamespace(id="R-003"), "gemini-3.5-flash", "v1", 0.3, "t")
    assert rec["letter_id"] == "R-003"
    assert rec["tokens_in"] == 100
    assert rec["tokens_out"] == 50  # 40 candidate + 10 thinking
    assert rec["safety_filter_status"] == "ok"


def test_process_letter_safety_block(monkeypatch):
    import pre_processing.run_gemini as m
    monkeypatch.setattr(m, "_call", lambda *a, **k: SimpleNamespace(text="", usage_metadata=None))
    rec = process_letter(None, SimpleNamespace(id="R-004"), "gemini-3.5-flash", "v1", 0.3, "t")
    assert rec["alert"]["category"] == "safety_filter_triggered"
    assert rec["safety_filter_status"] == "blocked"
