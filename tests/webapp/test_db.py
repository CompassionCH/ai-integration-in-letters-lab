"""Schema and initialization tests."""
import sqlite3

import pytest

from db import connect
from db.init import init_db

EXPECTED_TABLES = {
    "letters",
    "letter_paragraphs",
    "ai_responses",
    "ai_response_paragraphs",
    "sessions",
    "votes",
    "alert_evaluations",
    "missed_issues",
    "app_settings",
}

EXPECTED_INDICES = {
    "idx_letter_paragraphs_letter",
    "idx_ai_responses_letter",
    "idx_ai_response_paragraphs_response",
    "idx_votes_session",
    "idx_votes_letter",
    "idx_votes_ai_response",
    "idx_alert_evaluations_vote",
    "idx_missed_issues_vote",
}


def _names(conn, kind):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'",
        (kind,),
    ).fetchall()
    return {row["name"] for row in rows}


def test_init_creates_all_tables(tmp_db):
    conn = connect(tmp_db)
    try:
        assert EXPECTED_TABLES <= _names(conn, "table")
    finally:
        conn.close()


def test_init_creates_expected_indices(tmp_db):
    conn = connect(tmp_db)
    try:
        assert EXPECTED_INDICES <= _names(conn, "index")
    finally:
        conn.close()


def test_journal_mode_is_wal(tmp_db):
    conn = connect(tmp_db)
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_init_is_idempotent(tmp_db):
    # Re-running init on an existing DB must not raise and must keep the schema.
    init_db(tmp_db)
    conn = connect(tmp_db)
    try:
        assert EXPECTED_TABLES <= _names(conn, "table")
    finally:
        conn.close()


def test_foreign_keys_enforced(tmp_db):
    conn = connect(tmp_db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
                " VALUES (999, 999, 999, 'A', 1)"
            )
            conn.commit()
    finally:
        conn.close()


def test_seed_inserts_connected_rows(seed):
    ids = seed()
    assert ids["letter_id"]
    assert ids["vote_id"]


def test_preference_check_rejects_invalid(tmp_db):
    conn = connect(tmp_db)
    try:
        conn.execute("INSERT INTO sessions (session_token, first_name) VALUES ('s1', 'A')")
        conn.execute("INSERT INTO letters (target_lang) VALUES ('fr')")
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model) VALUES (1, 'v1', 'm')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
                " VALUES (1, 1, 1, 'Maybe', 1)"
            )
    finally:
        conn.close()


def test_display_ref_unique(tmp_db):
    conn = connect(tmp_db)
    try:
        conn.execute("INSERT INTO letters (display_ref) VALUES ('dup00001')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO letters (display_ref) VALUES ('dup00001')")
    finally:
        conn.close()


def test_sessions_has_session_token_column(tmp_db):
    conn = connect(tmp_db)
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "session_token" in cols
    finally:
        conn.close()


def test_session_token_is_unique(tmp_db):
    conn = connect(tmp_db)
    try:
        conn.execute("INSERT INTO sessions (session_token, first_name) VALUES ('tok-1', 'A')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO sessions (session_token, first_name) VALUES ('tok-1', 'B')")
    finally:
        conn.close()
