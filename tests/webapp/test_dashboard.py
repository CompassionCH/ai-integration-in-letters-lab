"""Tests for dashboard.py — filter parsing + a smoke test of the view-model assembly."""
import math

from dashboard import build_metrics, dropdown_options, parse_filters
from db import connect


def test_parse_filters_maps_and_coerces_ids():
    f = parse_filters(
        {"translator": "3", "letter": "5", "category": "abuse", "version": "v2"},
        active_version="v1",
    )
    assert f == {"translator_id": 3, "letter_id": 5, "alert_category": "abuse", "prompt_version": "v2"}
    assert isinstance(f["translator_id"], int) and isinstance(f["letter_id"], int)


def test_parse_filters_version_defaults_to_active():
    assert parse_filters({}, active_version="v1") == {"prompt_version": "v1"}


def test_parse_filters_all_versions_sentinel():
    assert parse_filters({"version": "__all__"}, active_version="v1") == {"prompt_version": "__all__"}


def test_parse_filters_empty_values_and_no_active_yield_no_filters():
    assert parse_filters({"translator": "", "letter": "", "category": ""}, active_version=None) == {}


def _seed(db_path):
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, target_lang, ground_truth_category)"
            " VALUES ('aaa00001', 'synthetic', 'fr', 'child_protection')"
        )
        lid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, alert_category, cost_usd)"
            " VALUES (?, 'v1', 'gemini-x', 'child_protection', 0.05)",
            (lid,),
        )
        aid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO sessions (session_token, first_name, last_name, source_langs_csv, target_langs_csv)"
            " VALUES ('t', 'Mae', 'Tan', 'en', 'fr')"
        )
        conn.execute(
            "INSERT INTO votes (session_id, letter_id, ai_response_id) VALUES (?, ?, ?)",
            (cur.lastrowid, lid, aid),
        )
        conn.commit()
    finally:
        conn.close()


def test_build_metrics_returns_all_reports(tmp_db):
    _seed(tmp_db)
    conn = connect(tmp_db)
    try:
        m = build_metrics(conn, {"prompt_version": "v1"})
    finally:
        conn.close()
    assert set(m) == {"preference", "alert_verdicts", "missed", "cost", "ground_truth", "participation"}
    assert m["participation"].n_votes == 1
    assert math.isclose(m["cost"].total_usd, 0.05)
    assert m["ground_truth"].per_category["child_protection"].tp == 1  # emitted matches expected


def test_dropdown_options_smoke(tmp_db):
    _seed(tmp_db)
    conn = connect(tmp_db)
    try:
        opts = dropdown_options(conn, "v1")
    finally:
        conn.close()
    assert [t["name"] for t in opts["translators"]] == ["Mae Tan"]
    assert opts["letters"][0]["label"] == "aaa00001"
    assert opts["versions"][0] == {"version": "v1", "covered": 1, "total": 1}
