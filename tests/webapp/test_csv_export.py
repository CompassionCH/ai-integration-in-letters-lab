"""Tests for the CSV export endpoint (one row per vote): column order, quoting,
sample values, and the admin auth chain."""
import csv
import hmac
import io

from db import connect

ADMIN_TOKEN = "test-admin-token"  # the conftest default
ADMIN_COOKIE = hmac.new(ADMIN_TOKEN.encode(), b"admin", "sha256").hexdigest()

EXPECTED_COLUMNS = [
    "session_id", "translator_first_name", "translator_last_name", "letter_id",
    "corpus_id", "letter_type", "direction", "source_lang", "target_lang", "country",
    "preference", "preference_comment", "ai_response_id", "a_is_ai",
    "alert_category", "alert_verdict", "alert_comment", "missed_yes_no",
    "missed_category", "missed_reason", "prompt_version", "model", "voted_at_iso",
]


def _seed_full_vote(db_path, *, comment="Good translation"):
    """A complete vote: letter + ai_response + session + vote + alert eval + missed."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, corpus_id, type, direction, source_lang, target_lang, country)"
            " VALUES ('ref00001', 'R-001', 'real', 'child_to_sponsor', 'en', 'fr', 'Kenya')"
        )
        lid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, alert_category)"
            " VALUES (?, 'v1', 'gemini-x', 'child_protection')",
            (lid,),
        )
        aid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO sessions (session_token, first_name, last_name) VALUES ('tok', 'Mae', 'Tan')"
        )
        sid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai, preference_comment)"
            " VALUES (?, ?, ?, 'A', 1, ?)",
            (sid, lid, aid, comment),
        )
        vid = cur.lastrowid
        conn.execute(
            "INSERT INTO alert_evaluations (vote_id, ai_response_id, verdict, comment)"
            " VALUES (?, ?, 'Correct', 'agree')",
            (vid, aid),
        )
        conn.execute(
            "INSERT INTO missed_issues (vote_id, missed_yes_no, category, reason)"
            " VALUES (?, 1, 'wrong_child_name', 'name mismatch')",
            (vid,),
        )
        conn.commit()
        return {"session_id": sid, "letter_id": lid, "ai_response_id": aid, "vote_id": vid}
    finally:
        conn.close()


async def test_export_csv_columns_and_row(client, tmp_db):
    ids = _seed_full_vote(tmp_db)
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.get("/admin/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment;") and "filename=votes-" in cd and cd.endswith(".csv")

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == EXPECTED_COLUMNS  # header present, exact order
    row = dict(zip(rows[0], rows[1]))
    assert row["session_id"] == str(ids["session_id"])
    assert row["translator_first_name"] == "Mae"
    assert row["translator_last_name"] == "Tan"
    assert row["letter_id"] == str(ids["letter_id"])
    assert row["corpus_id"] == "R-001"  # human-readable corpus id, for cross-referencing the source
    assert row["letter_type"] == "real"
    assert row["direction"] == "child_to_sponsor"
    assert row["source_lang"] == "en"
    assert row["target_lang"] == "fr"
    assert row["country"] == "Kenya"
    assert row["preference"] == "A"
    assert row["a_is_ai"] == "1"
    assert row["ai_response_id"] == str(ids["ai_response_id"])
    assert row["alert_category"] == "child_protection"
    assert row["alert_verdict"] == "Correct"
    assert row["alert_comment"] == "agree"
    assert row["missed_yes_no"] == "1"
    assert row["missed_category"] == "wrong_child_name"
    assert row["missed_reason"] == "name mismatch"
    assert row["prompt_version"] == "v1"
    assert row["model"] == "gemini-x"
    assert "T" in row["voted_at_iso"] and row["voted_at_iso"].endswith("Z")


async def test_export_csv_quotes_free_text(client, tmp_db):
    tricky = 'He said "great", and\nadded a line, with a comma'
    _seed_full_vote(tmp_db, comment=tricky)
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.get("/admin/export.csv")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 2  # header + 1 vote; the embedded newline stays inside the quoted field
    row = dict(zip(rows[0], rows[1]))
    assert row["preference_comment"] == tricky  # round-trips through csv quoting


async def test_export_csv_multiple_votes(client, tmp_db):
    _seed_full_vote(tmp_db)
    # a second, minimal vote (no alert eval, missed = no)
    conn = connect(tmp_db)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, target_lang) VALUES ('ref00002', 'synthetic', 'fr')"
        )
        lid2 = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model) VALUES (?, 'v1', 'gemini-x')",
            (lid2,),
        )
        aid2 = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO sessions (session_token, first_name, last_name) VALUES ('tok2', 'Sam', 'Lee')"
        )
        sid2 = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO votes (session_id, letter_id, ai_response_id) VALUES (?, ?, ?)",
            (sid2, lid2, aid2),
        )
        conn.execute("INSERT INTO missed_issues (vote_id, missed_yes_no) VALUES (?, 0)", (cur.lastrowid,))
        conn.commit()
    finally:
        conn.close()
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.get("/admin/export.csv")
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 3  # header + 2 votes (no fan-out from the LEFT JOINs)


async def test_export_csv_requires_admin_cookie(client, tmp_db):
    resp = await client.get("/admin/export.csv", follow_redirects=False)
    assert resp.status_code == 401


async def test_export_csv_token_query_sets_cookie_and_redirects(client, tmp_db):
    resp = await client.get(
        "/admin/export.csv", params={"token": ADMIN_TOKEN}, follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/export.csv"  # token stripped
    assert "admin_session=" in resp.headers.get("set-cookie", "")
