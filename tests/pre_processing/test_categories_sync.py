"""Drift guard for the two prompt-contract data files.

The alert enum the model is constrained to return (``response_schema.json``)
must stay equal to the id set in ``categories.json`` (the single source of
truth for alert categories), and exactly the two model-output-only states must
be excluded from the human "missed-issue" report. Cheapest possible insurance
against the two files silently diverging.
"""
import json
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[2] / "pre_processing" / "prompts"

# The two states a translator can never legitimately report as a *missed* issue:
# "nothing was wrong" and "the model refused" are valid model outputs only.
NON_SELECTABLE = {"no_alert", "safety_filter_triggered"}


def _load(name):
    return json.loads((PROMPTS / name).read_text(encoding="utf-8"))


def test_schema_enum_equals_category_ids():
    enum = _load("response_schema.json")["properties"]["alert"]["properties"]["category"]["enum"]
    ids = [c["id"] for c in _load("categories.json")]
    assert len(enum) == len(set(enum))  # no duplicate enum members
    assert len(ids) == len(set(ids))  # no duplicate category ids
    assert set(enum) == set(ids)


def test_every_category_has_a_boolean_selectable_flag():
    for category in _load("categories.json"):
        assert isinstance(category.get("selectable_for_missed"), bool), category


def test_only_model_only_states_are_non_selectable():
    categories = _load("categories.json")
    non_selectable = {c["id"] for c in categories if not c["selectable_for_missed"]}
    assert non_selectable == NON_SELECTABLE
