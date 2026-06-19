"""Tests for the language-edit endpoint (GET pre-filled form + POST update)."""
import re

from db import connect


async def test_get_languages_form_prefilled(logged_in, tmp_db):
    client, _ = logged_in  # session: en -> fr
    resp = await client.get("/session/languages")
    assert resp.status_code == 200
    assert 'action="/session/languages"' in resp.text
    # Current selection is pre-checked: en (source) + fr (target); de (source) is not.
    assert re.search(r'name="source_langs" value="en"\s+checked', resp.text)
    assert re.search(r'name="target_langs" value="fr"\s+checked', resp.text)
    assert not re.search(r'name="source_langs" value="de"\s+checked', resp.text)


async def test_post_updates_languages(logged_in, tmp_db):
    client, session_id = logged_in
    resp = await client.post(
        "/session/languages",
        data={"source_langs": ["en", "fr"], "target_langs": ["de"]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate"
    conn = connect(tmp_db)
    try:
        row = conn.execute(
            "SELECT source_langs_csv, target_langs_csv FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["source_langs_csv"] == "en,fr"
    assert row["target_langs_csv"] == "de"


async def test_post_rejects_missing_language(logged_in, tmp_db):
    client, session_id = logged_in
    resp = await client.post(
        "/session/languages",
        data={"source_langs": [], "target_langs": ["fr"]},  # no source language
        follow_redirects=False,
    )
    assert resp.status_code == 422
    conn = connect(tmp_db)
    try:
        row = conn.execute(
            "SELECT source_langs_csv FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row["source_langs_csv"] == "en"  # unchanged


async def test_languages_without_session_redirects_home(invited_client):
    post = await invited_client.post(
        "/session/languages",
        data={"source_langs": ["en"], "target_langs": ["fr"]},
        follow_redirects=False,
    )
    assert post.status_code == 303
    assert post.headers["location"] == "/"
    get = await invited_client.get("/session/languages", follow_redirects=False)
    assert get.status_code == 303
    assert get.headers["location"] == "/"
