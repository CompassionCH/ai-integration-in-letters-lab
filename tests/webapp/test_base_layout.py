"""Smoke tests for the base layout shell."""
from __future__ import annotations

from db import connect

# Hosts that would indicate a non-self-hosted asset slipped into the shell.
CDN_HOSTS = ("googleapis", "gstatic", "jsdelivr", "unpkg", "cdnjs", "cdn.")


async def test_brand_shell_and_self_hosted_assets(invited_client):
    resp = await invited_client.get("/")
    assert resp.status_code == 200
    text = resp.text
    # Brand + assets, all served locally.
    assert "/static/branding/logo.png" in text
    assert "/static/branding/favicon.png" in text
    assert "/static/css/app.css" in text
    assert "/static/vendor/htmx.min.js" in text
    for host in CDN_HOSTS:
        assert host not in text, f"unexpected external asset host: {host}"
    # Logged out (no session cookie) -> no session controls.
    assert "Sign out" not in text


async def test_session_controls_appear_only_when_logged_in(logged_in):
    client, _ = logged_in
    resp = await client.get("/evaluate/done")
    assert resp.status_code == 200
    text = resp.text
    assert "Sign out" in text
    assert 'action="/session/signout"' in text
    assert "My languages" in text


async def test_progress_slot_renders_when_context_has_totals(logged_in, tmp_db):
    client, _ = logged_in  # session: en -> fr
    conn = connect(tmp_db)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, source_lang, target_lang, human_translation_text)"
            " VALUES ('prg00001', 'real', 'en', 'fr', 'Human translation')"
        )
        letter_id = cur.lastrowid
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " safety_filter_status) VALUES (?, 'v1', 'gemini-test', 'AI translation', 'ok')",
            (letter_id,),
        )
        conn.commit()
    finally:
        conn.close()
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    # base.html progress slot shows the 1-based position of the letter on screen:
    # nothing voted yet (n_done = 0), so the first of one letter reads "Letter 1 / 1".
    assert "Letter 1 / 1" in resp.text
