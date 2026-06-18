"""Shared test fixtures for the whole suite."""
import os

import pytest

# The perimeter gate needs an invite token and the ASGI client speaks plain
# HTTP, so make Secure cookies round-trip. Set before the app is imported;
# config reads the environment lazily and load_dotenv() will not override these.
os.environ.setdefault("ACCESS_TOKEN", "test-invite-token")
os.environ.setdefault("COOKIE_SECURE", "false")

import httpx


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """A fresh WAL SQLite database initialized via db.init, isolated per test."""
    from db.init import init_db

    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    init_db(str(db_file))
    return str(db_file)


@pytest.fixture
def seed(tmp_db):
    """Factory that inserts a minimal connected row set; returns the new ids."""
    from db import connect

    def _seed():
        conn = connect(tmp_db)
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO letters (display_ref, type, target_lang) VALUES (?, ?, ?)",
                ("abc12345", "real", "fr"),
            )
            letter_id = cur.lastrowid
            cur.execute(
                "INSERT INTO letter_paragraphs (letter_id, page_index, sequence, source_text)"
                " VALUES (?, ?, ?, ?)",
                (letter_id, 0, 0, "Hello"),
            )
            cur.execute(
                "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text)"
                " VALUES (?, ?, ?, ?)",
                (letter_id, "v1", "gemini-test", "Bonjour"),
            )
            ai_response_id = cur.lastrowid
            cur.execute(
                "INSERT INTO sessions (first_name, target_langs_csv) VALUES (?, ?)",
                ("Alex", "fr"),
            )
            session_id = cur.lastrowid
            cur.execute(
                "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, letter_id, ai_response_id, "A", 1),
            )
            vote_id = cur.lastrowid
            conn.commit()
            return {
                "letter_id": letter_id,
                "ai_response_id": ai_response_id,
                "session_id": session_id,
                "vote_id": vote_id,
            }
        finally:
            conn.close()

    return _seed


@pytest.fixture
async def client():
    """An httpx.AsyncClient bound to the ASGI app."""
    from main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
