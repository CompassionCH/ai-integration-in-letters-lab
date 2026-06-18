"""Database initialization: create the schema and enable WAL mode."""
from __future__ import annotations

from pathlib import Path

import config
from db import connect

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db(db_path: str | None = None) -> str:
    """Create the database at ``db_path`` (default ``config.db_path()``) if it
    does not exist and apply the schema. Idempotent. Returns the path used.

    WAL mode persists in the database file, so concurrent translator votes and
    the admin dashboard reading aggregates won't hit ``database is locked``.
    """
    path = db_path or config.db_path()
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)

    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return path


if __name__ == "__main__":
    print(f"Initialized database at {init_db()}")
