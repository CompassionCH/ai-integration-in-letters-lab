"""Tests for analysis.cost — Gemini cost rollup + linear extrapolation (pure)."""
from __future__ import annotations

import math

from analysis.cost import CostReport, aggregate_cost


def _resp(cost_usd, *, tokens_in: int | None = 0, tokens_out: int | None = 0, prompt_version="v1"):
    return {
        "cost_usd": cost_usd,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "prompt_version": prompt_version,
    }


def test_known_inputs_expected_outputs():
    rows = [
        _resp(0.10, tokens_in=1000, tokens_out=200),
        _resp(0.30, tokens_in=3000, tokens_out=400),
    ]
    r = aggregate_cost(rows, real_volume=1000, real_pages=2000)
    assert math.isclose(r.total_usd, 0.40)
    assert math.isclose(r.per_letter_usd_avg, 0.20)
    assert r.tokens_in_total == 4000
    assert r.tokens_out_total == 600
    assert math.isclose(r.extrapolated_annual_usd, 200.0)          # 0.20 * 1000
    assert math.isclose(r.extrapolated_annual_per_page_usd, 0.10)  # 200 / 2000


def test_default_production_constants():
    r = aggregate_cost([_resp(0.05)])
    assert math.isclose(r.extrapolated_annual_usd, 0.05 * 77382)
    assert math.isclose(r.extrapolated_annual_per_page_usd, (0.05 * 77382) / 129419)


def test_empty_input_is_zero():
    assert aggregate_cost([]) == CostReport(0.0, 0.0, 0, 0, 0.0, 0.0)


def test_null_cost_rows_skipped():
    rows = [_resp(0.10, tokens_in=1000), _resp(None, tokens_in=9999)]
    r = aggregate_cost(rows, real_volume=10, real_pages=10)
    assert math.isclose(r.total_usd, 0.10)
    assert r.tokens_in_total == 1000                  # uncosted row contributes nothing
    assert math.isclose(r.per_letter_usd_avg, 0.10)   # n_corpus = 1, not 2


def test_tokens_none_treated_as_zero():
    r = aggregate_cost([_resp(0.10, tokens_in=None, tokens_out=None)], real_volume=1, real_pages=1)
    assert r.tokens_in_total == 0
    assert r.tokens_out_total == 0
    assert math.isclose(r.total_usd, 0.10)


def test_filter_by_prompt_version_and_all_sentinel():
    rows = [_resp(0.10, prompt_version="v1"), _resp(0.30, prompt_version="v2")]
    assert math.isclose(aggregate_cost(rows, filters={"prompt_version": "v1"}).total_usd, 0.10)
    assert math.isclose(aggregate_cost(rows, filters={"prompt_version": "v2"}).total_usd, 0.30)
    assert math.isclose(aggregate_cost(rows, filters={"prompt_version": "__all__"}).total_usd, 0.40)
    assert math.isclose(aggregate_cost(rows, filters={}).total_usd, 0.40)


def test_unrelated_filters_are_ignored():
    # cost honors prompt_version only -> a translator_id filter must NOT zero it out.
    rows = [_resp(0.10, prompt_version="v1"), _resp(0.30, prompt_version="v1")]
    r = aggregate_cost(rows, filters={"translator_id": 999, "prompt_version": "v1"})
    assert math.isclose(r.total_usd, 0.40)
