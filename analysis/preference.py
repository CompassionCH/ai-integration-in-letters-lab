"""A/B preference aggregation: AI translation vs the human reference.

Reports two complementary rates over the same votes, both with a 95% confidence
interval (normal approximation on a binomial proportion):

* **Acceptability (the decision metric)** — ``ai_acceptable_pct`` = the share of
  real-letter votes where the AI was judged *at least as good* as the human
  reference, i.e. an AI win OR an "Equivalent" tie, over all votes. This is a
  non-inferiority framing: the deployment question is "is the AI good enough to
  use without quality loss?", and an Equivalent verdict answers yes. Ties count
  toward the AI here by design.
* **Strict preference** — ``ai_preferred_pct`` = the share of *decisive* (non-tie)
  votes where the AI was chosen outright (ties excluded from numerator AND
  denominator). This is the conservative "was the AI actually preferred?" view.

Reporting both keeps the analysis honest: ties are visible as their own bucket
rather than hidden inside a single headline, and both can be reported:
"preferred outright in X%" and "at least as good in Y%".

Both rates are clean Bernoulli proportions (each vote is one trial), so the
simple ``p ± 1.96·sqrt(p(1-p)/n)`` interval is exactly the right estimator —
unlike a half-credit treatment of ties, which would need a different variance.

The function is PURE: the caller fetches the votes (joined to ``ai_responses``
for ``prompt_version`` / ``alert_category``) and resolves the active-version
default; this module never touches the database or settings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Two-sided 95% interval -> standard-normal quantile. (Wilson / Bayesian
# intervals are explicitly out of scope; the normal approximation is the agreed
# estimator (a small-n caveat applies).)
_Z_95 = 1.96

# Filterable dimensions. A vote is kept only if it matches every filter present
# in the dict; ``"__all__"`` (or an absent key) disables that dimension.
# ``alert_category`` / ``prompt_version`` are expected to ride on each row from
# the caller's join to ``ai_responses``; ``translator_id`` is the session/
# translator identity the caller aliases onto the row (the schema stores it as
# ``session_id``).
_FILTER_KEYS = ("translator_id", "letter_id", "alert_category", "prompt_version")


@dataclass(frozen=True)
class PreferenceReport:
    # Raw tallies (synthetic letters, which carry no A/B card, are excluded).
    ai_wins: int
    human_wins: int
    equivalent: int
    total: int
    # Strict preference among decisive votes: ai_wins / (ai_wins + human_wins).
    ai_preferred_pct: float
    preferred_ci_low: float
    preferred_ci_high: float
    # Non-inferiority headline: (ai_wins + equivalent) / total.
    ai_acceptable_pct: float
    acceptable_ci_low: float
    acceptable_ci_high: float


def _get(row, key):
    """Read ``key`` from a dict or sqlite3.Row, returning None if absent.

    (sqlite3.Row raises IndexError for unknown keys; dict raises KeyError.)
    """
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _passes_filters(row, filters) -> bool:
    for key in _FILTER_KEYS:
        if key not in filters:
            continue
        wanted = filters[key]
        if wanted == "__all__":
            continue
        if _get(row, key) != wanted:
            return False
    return True


def _proportion_ci(successes: int, n: int) -> tuple[float, float, float]:
    """Point estimate + 95% normal-approximation CI for a binomial proportion,
    clamped to [0, 1]. With no trials (``n == 0``) there is nothing to estimate,
    so return zeros — callers should read the raw counts to tell "0%" from
    "no data"."""
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    margin = _Z_95 * math.sqrt(p * (1.0 - p) / n)
    return p, max(0.0, p - margin), min(1.0, p + margin)


def aggregate_preference(votes, filters=None) -> PreferenceReport:
    """Aggregate A/B preference votes into the acceptability + strict-preference
    rates described in the module docstring.

    ``votes`` is any iterable of mappings (dict or sqlite3.Row) carrying at least
    ``preference`` ('A' / 'B' / 'Equivalent', or NULL for synthetic letters) and
    ``a_is_ai`` (1 if column A held the AI text, 0 if A held the human text),
    plus whichever of ``_FILTER_KEYS`` the caller filters on.

    ``filters`` is an optional dict over ``_FILTER_KEYS``; ``"__all__"`` or an
    absent key means "no constraint" on that dimension.
    """
    filters = filters or {}
    ai_wins = human_wins = equivalent = 0

    for row in votes:
        if not _passes_filters(row, filters):
            continue
        preference = _get(row, "preference")
        if preference is None:
            continue  # synthetic letter -> no A/B card -> not a preference vote
        if preference == "Equivalent":
            equivalent += 1
            continue
        a_is_ai = _get(row, "a_is_ai")
        if preference not in ("A", "B") or a_is_ai is None:
            continue  # unmappable row -> skip rather than miscount
        # a_is_ai == 1 means column A held the AI text. The AI is the chosen side
        # when A was picked and A is AI, or B was picked and B is AI (A is human).
        chose_ai = (preference == "A") == bool(a_is_ai)
        if chose_ai:
            ai_wins += 1
        else:
            human_wins += 1

    total = ai_wins + human_wins + equivalent
    decisive = ai_wins + human_wins

    preferred_pct, preferred_lo, preferred_hi = _proportion_ci(ai_wins, decisive)
    acceptable_pct, acceptable_lo, acceptable_hi = _proportion_ci(
        ai_wins + equivalent, total
    )

    return PreferenceReport(
        ai_wins=ai_wins,
        human_wins=human_wins,
        equivalent=equivalent,
        total=total,
        ai_preferred_pct=preferred_pct,
        preferred_ci_low=preferred_lo,
        preferred_ci_high=preferred_hi,
        ai_acceptable_pct=acceptable_pct,
        acceptable_ci_low=acceptable_lo,
        acceptable_ci_high=acceptable_hi,
    )
