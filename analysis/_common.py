"""Shared helpers for the analysis aggregations.

The aggregation functions all accept the same optional ``filters`` dict and read
fields off caller-supplied rows (dicts or sqlite3.Row). That common contract
lives here so each aggregator stays a thin, pure function.
"""
from __future__ import annotations

# Filterable dimensions shared by the aggregations. A row is kept only if it
# matches every filter PRESENT in the dict; ``"__all__"`` (or an absent key)
# disables that dimension. ``alert_category`` / ``prompt_version`` ride on each
# row from the caller's join to ``ai_responses``; ``translator_id`` is the
# session/translator identity the caller aliases onto the row (the schema stores
# it as ``session_id``). Not every aggregation supports all four — each documents
# the subset it expects the caller to pass.
FILTER_KEYS = ("translator_id", "letter_id", "alert_category", "prompt_version")


def get_value(row, key):
    """Read ``key`` from a dict or sqlite3.Row, returning None if absent.

    (sqlite3.Row raises IndexError for unknown keys; dict raises KeyError.)
    """
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def passes_filters(row, filters) -> bool:
    """True if ``row`` matches every active filter. ``filters`` is a dict over
    FILTER_KEYS; a value of ``"__all__"`` (or an absent key) means no constraint
    on that dimension. A filter key the row lacks fails closed (the row drops)."""
    for key in FILTER_KEYS:
        if key not in filters:
            continue
        wanted = filters[key]
        if wanted == "__all__":
            continue
        if get_value(row, key) != wanted:
            return False
    return True
