"""Tests for the admin settings endpoint (active prompt_version): upsert,
validation, lazy default, and the partial-coverage warning flash."""
import hmac

from db import connect

ADMIN_TOKEN = "test-admin-token"  # the conftest default
ADMIN_COOKIE = hmac.new(ADMIN_TOKEN.encode(), b"admin", "sha256").hexdigest()


def _seed_letter(db_path, display_ref, *, versions=()):
    """Insert a letter + one ai_response per given prompt_version; returns the id."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, target_lang) VALUES (?, 'real', 'fr')",
            (display_ref,),
        )
        lid = cur.lastrowid
        for version in versions:
            conn.execute(
                "INSERT INTO ai_responses (letter_id, prompt_version, model)"
                " VALUES (?, ?, 'gemini-x')",
                (lid, version),
            )
        conn.commit()
        return lid
    finally:
        conn.close()


def _active_setting(db_path):
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'active_prompt_version'"
        ).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


async def test_post_upserts_active_version(client, tmp_db):
    _seed_letter(tmp_db, "aaa00001", versions=("v1", "v2"))
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.post(
        "/admin/settings/active_prompt_version",
        data={"prompt_version": "v2"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"
    assert _active_setting(tmp_db) == "v2"
    # a second POST overwrites (upsert, not insert-only)
    await client.post(
        "/admin/settings/active_prompt_version",
        data={"prompt_version": "v1"},
        follow_redirects=False,
    )
    assert _active_setting(tmp_db) == "v1"


async def test_post_rejects_unknown_version(client, tmp_db):
    _seed_letter(tmp_db, "aaa00001", versions=("v1",))
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.post(
        "/admin/settings/active_prompt_version",
        data={"prompt_version": "v999"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert _active_setting(tmp_db) is None  # nothing upserted


async def test_get_returns_current_value_json(client, tmp_db):
    _seed_letter(tmp_db, "aaa00001", versions=("v1",))
    conn = connect(tmp_db)
    try:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v1')")
        conn.commit()
    finally:
        conn.close()
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.get("/admin/settings/active_prompt_version")
    assert resp.status_code == 200
    assert resp.json() == {"active_prompt_version": "v1"}


async def test_lazy_default_is_most_recent_when_unset(client, tmp_db):
    lid = _seed_letter(tmp_db, "aaa00001", versions=("v1",))
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, processed_at)"
            " VALUES (?, 'v2', 'gemini-x', '2030-01-01 00:00:00')",
            (lid,),
        )
        conn.execute(
            "UPDATE ai_responses SET processed_at = '2020-01-01 00:00:00'"
            " WHERE letter_id = ? AND prompt_version = 'v1'",
            (lid,),
        )
        conn.commit()
    finally:
        conn.close()
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.get("/admin/settings/active_prompt_version")
    assert resp.json() == {"active_prompt_version": "v2"}  # most-recently processed


async def test_lazy_default_null_when_no_responses(client, tmp_db):
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.get("/admin/settings/active_prompt_version")
    assert resp.json() == {"active_prompt_version": None}


async def test_partial_coverage_warning_on_redirect(client, tmp_db):
    # 3 letters; v2 exists for only 1 of them -> partial coverage.
    _seed_letter(tmp_db, "aaa00001", versions=("v1", "v2"))
    _seed_letter(tmp_db, "bbb00002", versions=("v1",))
    _seed_letter(tmp_db, "ccc00003", versions=("v1",))
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.post(
        "/admin/settings/active_prompt_version",
        data={"prompt_version": "v2"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "admin_flash=" in resp.headers.get("set-cookie", "")
    # following the redirect renders the warning in the dashboard
    page = await client.get("/admin")
    assert page.status_code == 200
    assert "covers 1/3 letters" in page.text


async def test_full_coverage_has_no_warning(client, tmp_db):
    _seed_letter(tmp_db, "aaa00001", versions=("v1",))
    _seed_letter(tmp_db, "bbb00002", versions=("v1",))
    client.cookies.set("admin_session", ADMIN_COOKIE)
    resp = await client.post(
        "/admin/settings/active_prompt_version",
        data={"prompt_version": "v1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "admin_flash=" not in resp.headers.get("set-cookie", "")


async def test_settings_require_admin_cookie(client, tmp_db):
    _seed_letter(tmp_db, "aaa00001", versions=("v1",))
    post = await client.post(
        "/admin/settings/active_prompt_version",
        data={"prompt_version": "v1"},
        follow_redirects=False,
    )
    assert post.status_code == 401
    get = await client.get("/admin/settings/active_prompt_version")
    assert get.status_code == 401
