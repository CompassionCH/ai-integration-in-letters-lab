"""USD cost for one Gemini call, from the pinned per-model pricing.

Shared by the production runner and the benchmark. The caller folds thinking tokens
into `tokens_out` (Gemini bills them as output).
"""
from __future__ import annotations

import json
from pathlib import Path

_PRICING = json.loads(Path("pre_processing/pricing.json").read_text(encoding="utf-8"))


def compute_cost(model: str, tokens_in: int, tokens_out: int, pricing: dict = _PRICING) -> float:
    pr = pricing["models"].get(model)
    if pr is None:
        raise KeyError(f"no pricing for {model!r} in pre_processing/pricing.json")
    over = tokens_in > pricing["context_tier_threshold_tokens"]
    in_rate = pr.get("input_usd_per_mtok_over_200k", pr["input_usd_per_mtok"]) if over else pr["input_usd_per_mtok"]
    out_rate = pr.get("output_usd_per_mtok_over_200k", pr["output_usd_per_mtok"]) if over else pr["output_usd_per_mtok"]
    return (tokens_in / 1e6) * in_rate + (tokens_out / 1e6) * out_rate
