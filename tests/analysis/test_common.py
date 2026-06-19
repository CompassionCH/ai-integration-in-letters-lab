"""Tests for analysis._common — the shared filter/field helpers used by every
aggregation. Locks the dict AND sqlite3.Row access paths at their source."""
import sqlite3

from analysis._common import FILTER_KEYS, get_value, passes_filters


def _row(**cols):
    """Build a real sqlite3.Row from the given columns."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    names = ", ".join(cols)
    marks = ", ".join("?" * len(cols))
    conn.execute(f"CREATE TABLE t ({names})")
    conn.execute(f"INSERT INTO t ({names}) VALUES ({marks})", tuple(cols.values()))
    return conn.execute("SELECT * FROM t").fetchone()


def test_get_value_from_dict():
    assert get_value({"a": 1}, "a") == 1
    assert get_value({"a": 1}, "missing") is None


def test_get_value_from_sqlite_row():
    row = _row(prompt_version="v1", letter_id=3)
    assert get_value(row, "prompt_version") == "v1"
    assert get_value(row, "letter_id") == 3
    assert get_value(row, "missing") is None  # IndexError on a Row -> None


def test_passes_filters_absent_key_and_all_are_no_constraint():
    row = {"prompt_version": "v1"}
    assert passes_filters(row, {}) is True
    assert passes_filters(row, {"prompt_version": "__all__"}) is True


def test_passes_filters_match_and_mismatch():
    row = {"prompt_version": "v1", "translator_id": 7}
    assert passes_filters(row, {"prompt_version": "v1"}) is True
    assert passes_filters(row, {"prompt_version": "v2"}) is False
    assert passes_filters(row, {"prompt_version": "v1", "translator_id": 7}) is True
    assert passes_filters(row, {"prompt_version": "v1", "translator_id": 8}) is False


def test_passes_filters_missing_key_fails_closed():
    # A filter on a dimension the row lacks -> the row drops.
    assert passes_filters({"prompt_version": "v1"}, {"letter_id": 5}) is False


def test_filter_keys_are_the_known_four():
    assert set(FILTER_KEYS) == {"translator_id", "letter_id", "alert_category", "prompt_version"}
