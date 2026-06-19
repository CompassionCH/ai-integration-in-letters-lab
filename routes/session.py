"""Session lifecycle: start and sign-out."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import config
from db import connect
from templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

SESSION_COOKIE = "session_id"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
SUPPORTED_LANGS = {"fr", "de", "it", "en"}


def _supported_subset(langs: list[str]) -> list[str]:
    """The submitted languages that are supported, de-duplicated, order preserved."""
    subset: list[str] = []
    for lang in langs:
        if lang in SUPPORTED_LANGS and lang not in subset:
            subset.append(lang)
    return subset


def set_session_cookie(response, token: str) -> None:
    """Set (or refresh, for the sliding 30-day window) the session_id cookie."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        secure=config.cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def resolve_session(request: Request):
    """Return the sessions row for the request's session_id cookie, bumping
    last_seen_at (the sliding window's server side); None if there is no cookie
    or no matching session row."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_token = ?", (token,)
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            conn.commit()
        return row
    finally:
        conn.close()


@router.post("/session/start")
async def session_start(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    spoken_langs: list[str] = Form(default=[]),
):
    langs = _supported_subset(spoken_langs)
    if len(langs) < 2:
        # Re-render the form inline with the error and the values already entered,
        # so the participant can fix the selection without re-typing.
        return templates.TemplateResponse(
            request=request,
            name="start.html",
            context={
                "error": (
                    "Please choose at least two languages you speak "
                    "(from French, German, Italian or English)."
                ),
                "first_name": first_name,
                "last_name": last_name,
                "spoken_langs": spoken_langs,
            },
            status_code=422,
        )

    # One "languages you speak" set, stored in both columns so a letter matches
    # when the volunteer speaks both its source and target language (see selection).
    langs_csv = ",".join(langs)
    token = str(uuid.uuid4())
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO sessions"
            " (session_token, first_name, last_name, source_langs_csv, target_langs_csv)"
            " VALUES (?, ?, ?, ?, ?)",
            (token, first_name, last_name, langs_csv, langs_csv),
        )
        conn.commit()
    finally:
        conn.close()

    # Log languages only — never the participant's name.
    logger.info("Session started (spoken langs %s)", langs)

    response = RedirectResponse(url="/evaluate", status_code=303)
    set_session_cookie(response, token)
    return response


@router.post("/session/signout")
async def session_signout():
    response = RedirectResponse(url="/", status_code=303)
    clear_session_cookie(response)
    return response


def _session_spoken_langs(session) -> list[str]:
    """The session's declared languages as one list, for the edit form. New
    sessions store the same set in both columns; older sessions (separate
    from/into) fold to the union so the form shows a sensible ≥ 2 selection."""
    spoken: list[str] = []
    for csv in (session["source_langs_csv"], session["target_langs_csv"]):
        for lang in (csv or "").split(","):
            if lang and lang not in spoken:
                spoken.append(lang)
    return spoken


@router.get("/session/languages")
async def languages_form(request: Request):
    """Render the language-edit form, pre-filled with the session's current
    selection (the top-bar "My languages" link points here)."""
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(request)
    if session is None:
        response = RedirectResponse(url="/", status_code=303)
        if token:  # stale cookie with no matching row -> clear it
            clear_session_cookie(response)
        return response
    response = templates.TemplateResponse(
        request=request,
        name="languages.html",
        context={"spoken_langs": _session_spoken_langs(session)},
    )
    set_session_cookie(response, session["session_token"])  # sliding refresh
    return response


@router.post("/session/languages")
async def languages_update(
    request: Request,
    spoken_langs: list[str] = Form(default=[]),
):
    """Update the session's declared languages mid-session. No progress is lost —
    only the next-letter selection is affected by the new prefs."""
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(request)
    if session is None:
        response = RedirectResponse(url="/", status_code=303)
        if token:
            clear_session_cookie(response)
        return response

    langs = _supported_subset(spoken_langs)
    if len(langs) < 2:
        # Re-render the form inline with the error and the attempted selection.
        response = templates.TemplateResponse(
            request=request,
            name="languages.html",
            context={
                "error": (
                    "Please choose at least two languages you speak "
                    "(from French, German, Italian or English)."
                ),
                "spoken_langs": spoken_langs,
            },
            status_code=422,
        )
        set_session_cookie(response, session["session_token"])
        return response

    langs_csv = ",".join(langs)
    conn = connect()
    try:
        conn.execute(
            "UPDATE sessions SET source_langs_csv = ?, target_langs_csv = ? WHERE id = ?",
            (langs_csv, langs_csv, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    # Log languages only — never the participant's name.
    logger.info("Session languages updated (spoken langs %s)", langs)
    response = RedirectResponse(url="/evaluate", status_code=303)
    set_session_cookie(response, session["session_token"])  # sliding refresh
    return response
