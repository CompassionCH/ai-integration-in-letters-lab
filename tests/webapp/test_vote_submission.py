"""Tests for the vote-submission endpoint (POST /evaluate/submit)."""
from __future__ import annotations

import sqlite3

import pytest

from db import connect


def _insert_letter(
    db_path,
    display_ref,
    *,
    source="en",
    target="fr",
    human: str | None = "Human translation",
    safety: str | None = "ok",
    ai_text="AI translation",
    alert: str | None = None,
    prompt_version="v1",
    letter_type="real",
):
    """Insert a letter + its single ai_response; returns (letter_id, ai_response_id)."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, pdf_path, direction, source_lang,"
            " target_lang, country, child_official, child_preferred, child_sex, child_age,"
            " sponsor_first, sponsor_sex, sponsor_age, human_translation_text)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                display_ref, letter_type, f"{letter_type}/{display_ref}.pdf", "child_to_sponsor",
                source, target, "Testland", "Mira", "Mira", "F", 9, "Tom", "M", 40, human,
            ),
        )
        letter_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " alert_category, safety_filter_status) VALUES (?,?,?,?,?,?)",
            (letter_id, prompt_version, "gemini-test", ai_text, alert, safety),
        )
        ai_response_id = cur.lastrowid
        conn.commit()
        return letter_id, ai_response_id
    finally:
        conn.close()


def _count(db_path, table, **where):
    conn = connect(db_path)
    try:
        clause = " AND ".join(f"{col} = ?" for col in where)
        sql = f"SELECT COUNT(*) FROM {table}"
        if clause:
            sql += f" WHERE {clause}"
        return conn.execute(sql, tuple(where.values())).fetchone()[0]
    finally:
        conn.close()


# --- happy paths ------------------------------------------------------------

async def test_happy_path_real_letter_with_alert_records_all(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id, ai_id = _insert_letter(tmp_db, "aaa11111", alert="child_protection")

    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "aaa11111",
            "preference": "A",
            "preference_comment": "A reads more naturally",
            "alert_verdict": "Correct",
            "alert_comment": "valid concern",
            "missed_yes_no": "no",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate?saved=1"

    conn = connect(tmp_db)
    try:
        vote = conn.execute(
            "SELECT * FROM votes WHERE session_id=? AND letter_id=?", (session_id, letter_id)
        ).fetchone()
        assert vote is not None
        assert vote["preference"] == "A"
        assert vote["ai_response_id"] == ai_id
        assert vote["a_is_ai"] in (0, 1)
        assert vote["preference_comment"] == "A reads more naturally"

        alert_eval = conn.execute(
            "SELECT * FROM alert_evaluations WHERE vote_id=?", (vote["id"],)
        ).fetchone()
        assert alert_eval is not None
        assert alert_eval["verdict"] == "Correct"
        assert alert_eval["ai_response_id"] == ai_id

        missed = conn.execute(
            "SELECT * FROM missed_issues WHERE vote_id=?", (vote["id"],)
        ).fetchone()
        assert missed is not None
        assert missed["missed_yes_no"] == 0
        assert missed["category"] is None
    finally:
        conn.close()


async def test_happy_path_no_alert_writes_no_alert_evaluation(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id, _ = _insert_letter(tmp_db, "noa00001", alert=None)  # alert_category NULL -> no_alert

    resp = await client.post(
        "/evaluate/submit",
        data={"display_ref": "noa00001", "preference": "Equivalent", "missed_yes_no": "no"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate?saved=1"
    vote_id = connect(tmp_db).execute(
        "SELECT id FROM votes WHERE session_id=? AND letter_id=?", (session_id, letter_id)
    ).fetchone()["id"]
    assert _count(tmp_db, "alert_evaluations", vote_id=vote_id) == 0  # no alert -> no row
    assert _count(tmp_db, "missed_issues", vote_id=vote_id) == 1


async def test_synthetic_letter_stores_null_preference(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id, ai_id = _insert_letter(tmp_db, "syn00001", human=None, alert=None)

    resp = await client.post(
        "/evaluate/submit",
        data={"display_ref": "syn00001", "missed_yes_no": "no"},  # no preference for synthetic
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate?saved=1"
    conn = connect(tmp_db)
    try:
        vote = conn.execute(
            "SELECT * FROM votes WHERE session_id=? AND letter_id=?", (session_id, letter_id)
        ).fetchone()
        assert vote is not None
        assert vote["preference"] is None
        assert vote["a_is_ai"] is None
        assert vote["ai_response_id"] == ai_id
    finally:
        conn.close()


async def test_missed_yes_records_category_and_reason(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id, _ = _insert_letter(tmp_db, "mis00001", alert=None)

    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "mis00001",
            "preference": "B",
            "missed_yes_no": "yes",
            "missed_category": "wrong_child_name",
            "missed_reason": "The child's name is wrong in the translation.",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    conn = connect(tmp_db)
    try:
        vote_id = conn.execute(
            "SELECT id FROM votes WHERE session_id=? AND letter_id=?", (session_id, letter_id)
        ).fetchone()["id"]
        missed = conn.execute(
            "SELECT * FROM missed_issues WHERE vote_id=?", (vote_id,)
        ).fetchone()
        assert missed["missed_yes_no"] == 1
        assert missed["category"] == "wrong_child_name"
        assert missed["reason"].startswith("The child's name")
    finally:
        conn.close()


# --- validation (422) -------------------------------------------------------

async def test_real_letter_missing_preference_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", alert=None)
    resp = await client.post(
        "/evaluate/submit",
        data={"display_ref": "aaa11111", "missed_yes_no": "no"},  # preference omitted on a real letter
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


async def test_alert_letter_missing_verdict_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", alert="child_protection")
    resp = await client.post(
        "/evaluate/submit",
        data={"display_ref": "aaa11111", "preference": "A", "missed_yes_no": "no"},  # no verdict
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


async def test_no_alert_letter_with_verdict_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "noa00001", alert=None)
    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "noa00001",
            "preference": "A",
            "alert_verdict": "Correct",  # there is no alert -> must be absent
            "missed_yes_no": "no",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


async def test_missed_yes_without_category_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", alert=None)
    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "aaa11111",
            "preference": "A",
            "missed_yes_no": "yes",
            "missed_reason": "something",  # category missing
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


async def test_missed_yes_without_reason_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", alert=None)
    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "aaa11111",
            "preference": "A",
            "missed_yes_no": "yes",
            "missed_category": "other",  # reason missing
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


async def test_unknown_missed_category_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", alert=None)
    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "aaa11111",
            "preference": "A",
            "missed_yes_no": "yes",
            "missed_category": "made_up_category",
            "missed_reason": "x",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


async def test_non_selectable_missed_category_rejected(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", alert=None)
    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "aaa11111",
            "preference": "A",
            "missed_yes_no": "yes",
            "missed_category": "no_alert",  # valid id, but not selectable as a missed issue
            "missed_reason": "x",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert _count(tmp_db, "votes") == 0


# --- idempotency, rollback, auth -------------------------------------------

async def test_duplicate_submission_is_idempotent(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id, _ = _insert_letter(tmp_db, "aaa11111", alert="child_protection")
    data = {
        "display_ref": "aaa11111",
        "preference": "A",
        "alert_verdict": "Correct",
        "missed_yes_no": "no",
    }

    first = await client.post("/evaluate/submit", data=data, follow_redirects=False)
    assert first.status_code == 303
    assert first.headers["location"] == "/evaluate?saved=1"

    second = await client.post("/evaluate/submit", data=data, follow_redirects=False)
    assert second.status_code == 303
    assert second.headers["location"] == "/evaluate"  # idempotent resubmit -> no thank-you flag

    assert _count(tmp_db, "votes", session_id=session_id, letter_id=letter_id) == 1
    assert _count(tmp_db, "alert_evaluations") == 1
    assert _count(tmp_db, "missed_issues") == 1


def test_transaction_rolls_back_on_partial_failure(tmp_db):
    from routes.evaluate import _persist_evaluation

    letter_id, ai_id = _insert_letter(tmp_db, "aaa11111", alert="child_protection")
    conn = connect(tmp_db)
    try:
        session_id = conn.execute(
            "INSERT INTO sessions (session_token, first_name) VALUES ('tok', 'A')"
        ).lastrowid
        conn.commit()

        # A bad verdict trips the alert_evaluations CHECK on the SECOND insert, after the
        # votes row is already inserted -> the whole transaction must roll back.
        with pytest.raises(sqlite3.IntegrityError):
            _persist_evaluation(
                conn,
                session_id=session_id,
                letter_id=letter_id,
                ai_response_id=ai_id,
                preference="A",
                a_is_ai=1,
                preference_comment=None,
                alert_verdict="NOT_A_VALID_VERDICT",
                alert_comment=None,
                missed_yes=0,
                missed_category=None,
                missed_reason=None,
            )

        assert conn.execute(
            "SELECT COUNT(*) FROM votes WHERE session_id=? AND letter_id=?",
            (session_id, letter_id),
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alert_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM missed_issues").fetchone()[0] == 0
    finally:
        conn.close()


async def test_blank_comments_stored_as_null(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id, _ = _insert_letter(tmp_db, "aaa11111", alert="child_protection")
    resp = await client.post(
        "/evaluate/submit",
        data={
            "display_ref": "aaa11111",
            "preference": "A",
            "preference_comment": "   ",  # whitespace-only -> NULL
            "alert_verdict": "Correct",
            "alert_comment": "",  # empty -> NULL
            "missed_yes_no": "no",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    conn = connect(tmp_db)
    try:
        vote = conn.execute(
            "SELECT * FROM votes WHERE session_id=? AND letter_id=?", (session_id, letter_id)
        ).fetchone()
        assert vote["preference_comment"] is None
        alert_eval = conn.execute(
            "SELECT * FROM alert_evaluations WHERE vote_id=?", (vote["id"],)
        ).fetchone()
        assert alert_eval["comment"] is None
    finally:
        conn.close()


async def test_submit_without_session_redirects_home(invited_client, tmp_db):
    _insert_letter(tmp_db, "aaa11111", alert=None)
    resp = await invited_client.post(
        "/evaluate/submit",
        data={"display_ref": "aaa11111", "preference": "A", "missed_yes_no": "no"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert _count(tmp_db, "votes") == 0
