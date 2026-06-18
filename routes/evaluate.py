"""Evaluation flow: serve the next letter + the session-bound letter PDF."""
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

import config
import selection
from db import connect
from routes.session import (
    SESSION_COOKIE,
    clear_session_cookie,
    resolve_session,
    set_session_cookie,
)
from templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _session_langs(session):
    source = {s for s in (session["source_langs_csv"] or "").split(",") if s}
    target = {t for t in (session["target_langs_csv"] or "").split(",") if t}
    return source, target


def _active_prompt_version(conn):
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'active_prompt_version'"
    ).fetchone()
    return row["value"] if row else None


def _select_ai_row(conn, letter_id, active_version):
    """The single chosen ai_response for a letter: the active prompt_version if a
    row exists, else the most-recently processed. Pure selection — no logging, so
    both serving and the safety-warning resolve the *same* row per letter."""
    if active_version is not None:
        row = conn.execute(
            "SELECT * FROM ai_responses WHERE letter_id = ? AND prompt_version = ?",
            (letter_id, active_version),
        ).fetchone()
        if row is not None:
            return row
    return conn.execute(
        "SELECT * FROM ai_responses WHERE letter_id = ?"
        " ORDER BY processed_at DESC, id DESC LIMIT 1",
        (letter_id,),
    ).fetchone()


def _load_candidates(conn, active_version):
    """Servable letters (each with its chosen, safety-ok ai_response)."""
    candidates = []
    for letter in conn.execute("SELECT * FROM letters").fetchall():
        ai = _select_ai_row(conn, letter["id"], active_version)
        if ai is None:
            continue  # no AI response yet -> not servable
        if ai["safety_filter_status"] != "ok":
            continue  # chosen response safety-filtered (or unknown status) -> excluded
        candidates.append(
            {
                "id": letter["id"],
                "source_lang": letter["source_lang"],
                "target_lang": letter["target_lang"],
                "letter": letter,
                "ai": ai,
            }
        )
    return candidates


def _voted_ids(conn, session_id):
    rows = conn.execute(
        "SELECT letter_id FROM votes WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {row["letter_id"] for row in rows}


def warn_safety_filtered() -> None:
    """Log the letters excluded from serving because their CHOSEN ai_response has a
    non-ok safety filter — exactly the set the serving filter (_load_candidates)
    excludes, resolved via the same _select_ai_row. Best-effort at startup: a
    no-op if the DB isn't ready yet."""
    try:
        conn = connect()
        try:
            active = _active_prompt_version(conn)
            excluded = []
            for letter in conn.execute("SELECT id, display_ref FROM letters").fetchall():
                ai = _select_ai_row(conn, letter["id"], active)
                if ai is not None and ai["safety_filter_status"] != "ok":
                    excluded.append(letter["display_ref"])
        finally:
            conn.close()
    except Exception as exc:  # DB not initialised yet, missing tables, etc.
        logger.debug("Safety-filter startup check skipped: %s", exc)
        return
    if excluded:
        logger.warning("Letters excluded from serving by safety filter: %s", excluded)


@router.get("/evaluate")
async def evaluate(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(request)
    if session is None:
        response = RedirectResponse(url="/", status_code=303)
        if token:  # stale cookie with no matching row -> clear it
            clear_session_cookie(response)
        return response

    source_langs, target_langs = _session_langs(session)
    conn = connect()
    try:
        active = _active_prompt_version(conn)
        candidates = _load_candidates(conn, active)
        voted_ids = _voted_ids(conn, session["id"])
    finally:
        conn.close()

    chosen = selection.select_next_letter(
        session["id"], candidates, voted_ids, source_langs, target_langs
    )
    if chosen is None:
        response = RedirectResponse(url="/evaluate/done", status_code=303)
        set_session_cookie(response, token)  # sliding refresh
        return response

    letter, ai = chosen["letter"], chosen["ai"]
    if active is not None and ai["prompt_version"] != active:
        logger.warning(
            "Serving letter %s from fallback prompt_version %r (active %r has no response)",
            letter["display_ref"], ai["prompt_version"], active,
        )
    a_is_ai = selection.a_is_ai(session["id"], letter["id"])
    show_ab = selection.show_ab_card(letter["human_translation_text"])
    if show_ab:
        ai_text, human_text = ai["translation_text"], letter["human_translation_text"]
        translation_a = ai_text if a_is_ai else human_text
        translation_b = human_text if a_is_ai else ai_text
    else:
        translation_a = translation_b = None

    matching_ids = {
        c["id"]
        for c in candidates
        if selection.matches_session_langs(c, source_langs, target_langs)
    }

    context = {
        "display_ref": letter["display_ref"],
        "pdf_url": f"/letters/{letter['display_ref']}.pdf",
        "child_official": letter["child_official"],
        "child_preferred": letter["child_preferred"],
        "child_sex": letter["child_sex"],
        "child_age": letter["child_age"],
        "country": letter["country"],
        "sponsor_first": letter["sponsor_first"],
        "sponsor_other_first_names_csv": letter["sponsor_other_first_names_csv"],
        "sponsor_sex": letter["sponsor_sex"],
        "sponsor_age": letter["sponsor_age"],
        "source_lang": letter["source_lang"],
        "target_lang": letter["target_lang"],
        "show_ab_card": show_ab,
        "translation_a": translation_a,
        "translation_b": translation_b,
        "a_is_ai": a_is_ai,
        "alert_category": ai["alert_category"] or "no_alert",
        "alert_reason": ai["alert_reason"],
        "ai_response_id": ai["id"],
        "prompt_version": ai["prompt_version"],
        "model": ai["model"],
        "n_done": len(voted_ids & matching_ids),
        "n_total": len(matching_ids),
        "show_thanks": request.query_params.get("saved") == "1",
    }
    response = templates.TemplateResponse(request=request, name="evaluate.html", context=context)
    set_session_cookie(response, token)  # sliding refresh
    return response


@router.get("/evaluate/done")
async def evaluate_done(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(request)
    if session is None:
        response = RedirectResponse(url="/", status_code=303)
        if token:
            clear_session_cookie(response)
        return response
    response = templates.TemplateResponse(request=request, name="evaluate_done.html", context={})
    set_session_cookie(response, token)  # sliding refresh
    return response


@router.get("/letters/{display_ref}.pdf")
async def letter_pdf(display_ref: str, request: Request):
    session = resolve_session(request)
    if session is None:
        return Response(status_code=404)  # opaque: no valid session -> not found

    source_langs, target_langs = _session_langs(session)
    conn = connect()
    try:
        letter = conn.execute(
            "SELECT id, pdf_path FROM letters WHERE display_ref = ?", (display_ref,)
        ).fetchone()
        active = _active_prompt_version(conn)
        candidates = _load_candidates(conn, active)
        voted_ids = _voted_ids(conn, session["id"])
    finally:
        conn.close()

    if letter is None:
        return Response(status_code=404)

    served = selection.served_set(
        session["id"], candidates, voted_ids, source_langs, target_langs
    )
    if letter["id"] not in served:  # bind to this session's served set; any other ref is 404
        return Response(status_code=404)

    pdf_path = Path(config.letters_dir()) / letter["pdf_path"]
    if not pdf_path.is_file():
        return Response(status_code=404)
    return FileResponse(str(pdf_path), media_type="application/pdf")
