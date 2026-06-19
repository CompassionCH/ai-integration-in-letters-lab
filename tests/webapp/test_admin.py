"""Admin endpoint: shared-secret auth (cookie / Bearer / query) + the non-blind
admin PDF route. ``/admin`` is allow-listed out of the invite gate, so the bare
(un-invited) client reaches it; its own ADMIN_TOKEN gate is what's exercised here."""
import hmac

from db import connect

# Matches the conftest default; the cookie payload is HMAC("admin") keyed by it.
ADMIN_TOKEN = "test-admin-token"
EXPECTED_COOKIE = hmac.new(ADMIN_TOKEN.encode(), b"admin", "sha256").hexdigest()


def _insert_letter(db_path, *, pdf_path="real/adm00001.pdf"):
    """Insert a bare letter row; returns its real id."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, pdf_path, target_lang)"
            " VALUES (?, ?, ?, ?)",
            ("adm00001", "real", pdf_path, "fr"),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


async def test_admin_401_without_token(client, tmp_db):
    resp = await client.get("/admin")
    assert resp.status_code == 401


async def test_admin_401_wrong_token(client, tmp_db):
    resp = await client.get("/admin", params={"token": "not-the-token"})
    assert resp.status_code == 401


async def test_admin_query_token_sets_cookie_and_redirects(client, tmp_db):
    resp = await client.get("/admin", params={"token": ADMIN_TOKEN}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin"  # query string stripped
    set_cookie = resp.headers.get("set-cookie", "")
    assert "admin_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    # The 302 set the cookie in the jar; following it renders the dashboard.
    followed = await client.get("/admin")
    assert followed.status_code == 200
    assert "Admin dashboard" in followed.text


async def test_admin_cookie_alone_renders(client, tmp_db):
    client.cookies.set("admin_session", EXPECTED_COOKIE)
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code == 200
    assert "Admin dashboard" in resp.text


async def test_admin_wrong_cookie_rejected(client, tmp_db):
    client.cookies.set("admin_session", "forged-value")
    resp = await client.get("/admin")
    assert resp.status_code == 401


async def test_admin_bearer_header_authenticates(client, tmp_db):
    resp = await client.get(
        "/admin",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "admin_session=" in resp.headers.get("set-cookie", "")
    # Cookie from the Bearer-triggered 302 now renders the dashboard.
    followed = await client.get("/admin")
    assert followed.status_code == 200


async def test_admin_version_and_model_in_header(client, tmp_db):
    conn = connect(tmp_db)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, target_lang) VALUES ('hdr00001', 'real', 'fr')"
        )
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model) VALUES (?, 'v1', 'gemini-xyz')",
            (cur.lastrowid,),
        )
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v1')")
        conn.commit()
    finally:
        conn.close()
    client.cookies.set("admin_session", EXPECTED_COOKIE)
    resp = await client.get("/admin")
    assert resp.status_code == 200
    assert "v1" in resp.text  # active prompt version
    assert "gemini-xyz" in resp.text  # model behind the active version


async def test_admin_pdf_serves_any_letter_with_cookie(client, tmp_db, tmp_path, monkeypatch):
    letter_id = _insert_letter(tmp_db)
    letters_dir = tmp_path / "letters"
    (letters_dir / "real").mkdir(parents=True)
    (letters_dir / "real" / "adm00001.pdf").write_bytes(b"%PDF-1.4 test")
    monkeypatch.setenv("LETTERS_DIR", str(letters_dir))

    client.cookies.set("admin_session", EXPECTED_COOKIE)
    # No session, no served-set binding — the admin cookie alone serves any id.
    resp = await client.get(f"/admin/letters/{letter_id}.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"


async def test_admin_pdf_401_without_cookie(client, tmp_db):
    letter_id = _insert_letter(tmp_db)
    resp = await client.get(f"/admin/letters/{letter_id}.pdf")
    assert resp.status_code == 401


async def test_admin_pdf_404_for_unknown_letter(client, tmp_db):
    client.cookies.set("admin_session", EXPECTED_COOKIE)
    resp = await client.get("/admin/letters/999999.pdf")
    assert resp.status_code == 404
