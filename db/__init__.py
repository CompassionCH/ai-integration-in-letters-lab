"""SQLite access helpers."""
from __future__ import annotations

import sqlite3

import config


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced.

    Foreign-key enforcement is per-connection in SQLite (off by default), so it
    is set on every connection here rather than once at init time.
    """
    conn = sqlite3.connect(db_path or config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
