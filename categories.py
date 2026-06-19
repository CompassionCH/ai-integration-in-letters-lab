"""Loader for the alert-category set (``pre_processing/prompts/categories.json``).

That file is the single source of truth for alert ids. The webapp consumes the
``selectable_for_missed`` subset — the categories a reviewer may choose when
reporting an issue the model missed (everything except the two model-output-only
states, ``no_alert`` and ``safety_filter_triggered``).
"""
from __future__ import annotations

import json
from pathlib import Path

CATEGORIES_PATH = (
    Path(__file__).resolve().parent / "pre_processing" / "prompts" / "categories.json"
)


def _load() -> list[dict]:
    return json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))


def selectable_for_missed_ids() -> set[str]:
    """Return the category ids a reviewer may pick as a missed-issue report."""
    return {c["id"] for c in _load() if c["selectable_for_missed"]}


def selectable_for_missed() -> list[dict]:
    """Ordered ``{id, label_en}`` entries for the missed-issue dropdown.

    Same subset as :func:`selectable_for_missed_ids`, but carrying the English
    label the reviewer sees and preserving the file's order.
    """
    return [
        {"id": c["id"], "label_en": c["label_en"]}
        for c in _load()
        if c["selectable_for_missed"]
    ]


def label_for(category_id: str) -> str:
    """Human label (``label_en``) for a category id; falls back to the id itself."""
    for c in _load():
        if c["id"] == category_id:
            return c["label_en"]
    return category_id
