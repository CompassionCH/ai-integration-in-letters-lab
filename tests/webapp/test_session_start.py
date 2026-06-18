"""Tests for the session start + sign-out endpoints."""
from db import connect

VALID_FORM = {
    "first_name": "Mira",
    "last_name": "Tester",
    "source_langs": ["en"],
    "target_langs": ["fr"],
}


async def test_session_start_happy_path(invited_client, tmp_db):
    resp = await invited_client.post("/session/start", data=VALID_FORM, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate"
    assert "session_id" in resp.cookies
    # Lock the DoD-specified cookie flags (Secure is gated off in the test env).
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "max-age=2592000" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie

    conn = connect(tmp_db)
    try:
        row = conn.execute(
            "SELECT first_name, source_langs_csv, target_langs_csv FROM sessions"
        ).fetchone()
    finally:
        conn.close()
    assert row["first_name"] == "Mira"
    assert row["source_langs_csv"] == "en"
    assert row["target_langs_csv"] == "fr"


async def test_session_start_rejects_empty_target_lang(invited_client):
    form = {"first_name": "Mira", "last_name": "T", "source_langs": ["en"], "target_langs": []}
    resp = await invited_client.post("/session/start", data=form, follow_redirects=False)
    assert resp.status_code == 422


async def test_session_start_rejects_unsupported_lang(invited_client):
    form = {"first_name": "Mira", "last_name": "T", "source_langs": ["sw"], "target_langs": ["fr"]}
    resp = await invited_client.post("/session/start", data=form, follow_redirects=False)
    assert resp.status_code == 422


async def test_signout_clears_cookie(invited_client):
    resp = await invited_client.post("/session/signout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "session_id=" in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie
