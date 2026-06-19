"""Cost rollup: sum the measured Gemini spend on the corpus and extrapolate it
linearly to the production volume. All amounts in USD (matches Gemini billing).

PURE function over caller-supplied ``ai_responses`` rows (dict / sqlite3.Row); it
trusts the ``cost_usd`` already stored on each row (computed by the offline
pipeline) and never reads the database or any pricing table. The caller resolves
the active prompt_version and passes it via ``filters``.
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis._common import get_value, passes_filters

# Production baseline (letters / pages per year) for the extrapolation. The
# page-per-letter ratio (real_pages / real_volume) turns the annual letter figure
# into a per-page unit cost.
_DEFAULT_REAL_VOLUME = 77382
_DEFAULT_REAL_PAGES = 129419


@dataclass(frozen=True)
class CostReport:
    total_usd: float
    per_letter_usd_avg: float
    tokens_in_total: int
    tokens_out_total: int
    extrapolated_annual_usd: float
    extrapolated_annual_per_page_usd: float


def aggregate_cost(
    ai_responses,
    real_volume=_DEFAULT_REAL_VOLUME,
    real_pages=_DEFAULT_REAL_PAGES,
    filters=None,
) -> CostReport:
    """Roll up cost + tokens over the (prompt_version-filtered) responses and
    extrapolate linearly to ``real_volume`` letters / ``real_pages`` pages a year.

    Rows whose ``cost_usd`` is NULL are not-yet-costed and are skipped entirely
    (excluded from both the total and the per-letter denominator), so the average
    reflects costed responses only. ``filters`` honors ``prompt_version`` only
    (``"__all__"`` or an absent key disables it)."""
    filters = filters or {}
    total_usd = 0.0
    tokens_in_total = 0
    tokens_out_total = 0
    n_corpus = 0
    for row in ai_responses:
        if not passes_filters(row, filters, keys=("prompt_version",)):
            continue
        cost = get_value(row, "cost_usd")
        if cost is None:
            continue  # not yet costed -> excluded from the rollup
        total_usd += cost
        tokens_in_total += get_value(row, "tokens_in") or 0
        tokens_out_total += get_value(row, "tokens_out") or 0
        n_corpus += 1

    per_letter = total_usd / n_corpus if n_corpus else 0.0
    annual = per_letter * real_volume
    per_page = annual / real_pages if real_pages else 0.0
    return CostReport(
        total_usd=total_usd,
        per_letter_usd_avg=per_letter,
        tokens_in_total=tokens_in_total,
        tokens_out_total=tokens_out_total,
        extrapolated_annual_usd=annual,
        extrapolated_annual_per_page_usd=per_page,
    )
