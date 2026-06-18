"""Single settings module.

This is the ONLY module that reads ``os.environ`` directly; every other module
imports these accessors instead. ``main`` loads the ``.env`` file (via
python-dotenv) before any of these are called, so the values reflect the process
environment at call time.

Accessors are functions (not import-time constants) on purpose: reading at call
time avoids any ordering hazard with ``.env`` loading and lets tests set the
environment freely before exercising a request.
"""
from __future__ import annotations

import os

# Default location of the SQLite database file (consumed by the DB layer).
DEFAULT_DB_PATH = "poc.db"

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise ValueError(f"{name} must be a boolean-like value, got {raw!r}")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable {name} is not set. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def db_path() -> str:
    """Filesystem path to the SQLite database."""
    return os.environ.get("DB_PATH") or DEFAULT_DB_PATH


def letters_dir() -> str:
    """Base directory holding the letter PDFs (real/ and synthetic/ subdirs)."""
    return os.environ.get("LETTERS_DIR") or "letters"


def log_level() -> str:
    """Logging level name; defaults to INFO."""
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def cookie_secure() -> bool:
    """Whether auth cookies carry the ``Secure`` flag.

    Defaults to True (production is HTTPS-only). Set ``COOKIE_SECURE=false`` in
    dev/test so cookies round-trip over plain HTTP.
    """
    return _env_bool("COOKIE_SECURE", default=True)


def access_token() -> str:
    """Shared invite token gating the whole application perimeter."""
    return _require("ACCESS_TOKEN")


def admin_token() -> str:
    """Token gating the admin endpoints (a distinct secret from the invite token)."""
    return _require("ADMIN_TOKEN")


def gemini_api_key() -> str:
    """API key for the Gemini SDK (used by the offline pre-processing pipeline)."""
    return _require("GEMINI_API_KEY")
