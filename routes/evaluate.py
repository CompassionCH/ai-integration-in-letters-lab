"""Evaluation flow: serve the next letter + the session-bound letter PDF."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

import categories
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

# Rotating thank-you banner shown after each saved evaluation, indexed by votes
# done so it varies without randomness (deterministic + refresh-stable). Warm and
# non-culpabilizing, affirming the value of the volunteer's judgment.
THANKS_MESSAGES = [
    "Thank you! Your judgment just made one more letter safer for a child.",
    "Saved! Every letter you check helps a family's words arrive clearly.",
    "Got it! Your call helps us learn where the AI can be trusted.",
    "One more done! Thank you for lending your expertise.",
    "Saved! Your read keeps these letters faithful to their senders.",
    "Thank you! Careful work like yours is a true blessing.",
    "Noted! Each answer sharpens the picture of what the AI gets right.",
    "Thank you! Your work is making a difference in children's life.",
    "Done! Your attention to detail makes this evaluation meaningful.",
]


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


def _persist_evaluation(
    conn,
    *,
    session_id,
    letter_id,
    ai_response_id,
    preference,
    a_is_ai,
    preference_comment,
    alert_verdict,
    alert_comment,
    missed_yes,
    missed_category,
    missed_reason,
) -> bool:
    """Atomically record the vote + (alert verdict when present) + missed-issue.

    Returns True if a new vote was written, False if it was a duplicate — the
    ``(session_id, letter_id)`` unique constraint makes a resubmit (back button
    after the PRG redirect) a silent no-op rather than an error. The ``with conn``
    block commits on success and rolls back on any partial failure.
    """
    with conn:
        cur = conn.execute(
            "INSERT INTO votes"
            " (session_id, letter_id, ai_response_id, preference, a_is_ai, preference_comment)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(session_id, letter_id) DO NOTHING",
            (session_id, letter_id, ai_response_id, preference, a_is_ai, preference_comment),
        )
        if cur.rowcount == 0:
            return False  # duplicate vote for this (session, letter) -> idempotent
        vote_id = cur.lastrowid
        if alert_verdict is not None:
            conn.execute(
                "INSERT INTO alert_evaluations (vote_id, ai_response_id, verdict, comment)"
                " VALUES (?, ?, ?, ?)",
                (vote_id, ai_response_id, alert_verdict, alert_comment),
            )
        conn.execute(
            "INSERT INTO missed_issues (vote_id, missed_yes_no, category, reason)"
            " VALUES (?, ?, ?, ?)",
            (vote_id, missed_yes, missed_category, missed_reason),
        )
        return True


def _reject(request, message: str):
    """422 with the shared friendly error page. Submit validation should rarely
    fire — the UI constrains these fields — so this is a defensive backstop."""
    return templates.TemplateResponse(
        request=request,
        name="session_error.html",
        context={"message": message},
        status_code=422,
    )


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
        all_letter_langs = conn.execute(
            "SELECT source_lang, target_lang FROM letters"
        ).fetchall()
    finally:
        conn.close()

    chosen = selection.select_next_letter(
        session["id"], candidates, voted_ids, source_langs, target_langs
    )
    if chosen is None:
        # Distinguish a language dead-end (no letter in the corpus is in a pair this
        # volunteer can handle) from genuine completion. Keyed on language ONLY —
        # ignoring votes and safety — so an all-voted or all-safety-filtered corpus
        # still lands on the normal done page, while a language mismatch gets the
        # distinct "no letters for your languages" state.
        lang_matchable = any(
            selection.matches_session_langs(row, source_langs, target_langs)
            for row in all_letter_langs
        )
        if not lang_matchable:
            response = templates.TemplateResponse(
                request=request, name="evaluate_empty.html", context={}
            )
            set_session_cookie(response, token)  # sliding refresh
            return response
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
    n_done = len(voted_ids & matching_ids)
    alert_category = ai["alert_category"] or "no_alert"
    saved = request.query_params.get("saved") == "1"

    # `a_is_ai` is deliberately NOT in the context: the page must never reveal which
    # side is the AI (parity). Internal ids (ai_response_id / prompt_version / model)
    # are omitted too — the volunteer UI doesn't show them and the submit recomputes
    # the response server-side from `display_ref`.
    context = {
        "display_ref": letter["display_ref"],
        "pdf_url": f"/letters/{letter['display_ref']}.pdf",
        "child_official": letter["child_official"],
        "child_preferred": letter["child_preferred"],
        "child_sex": letter["child_sex"],
        "child_age": letter["child_age"],
        "country": letter["country"],
        "sponsor_first": letter["sponsor_first"],
        "sponsor_sex": letter["sponsor_sex"],
        "sponsor_age": letter["sponsor_age"],
        "source_lang": letter["source_lang"],
        "target_lang": letter["target_lang"],
        "show_ab_card": show_ab,
        "translation_a": translation_a,
        "translation_b": translation_b,
        "alert_category": alert_category,
        "alert_reason": ai["alert_reason"],
        "alert_label": categories.label_for(alert_category),
        "missed_categories": categories.selectable_for_missed(),
        "n_done": n_done,
        "n_total": len(matching_ids),
        # Rotating thank-you for base.html's flash slot, only right after a save.
        "flash": THANKS_MESSAGES[n_done % len(THANKS_MESSAGES)] if saved else None,
    }
    response = templates.TemplateResponse(request=request, name="evaluate.html", context=context)
    set_session_cookie(response, token)  # sliding refresh
    return response


@router.post("/evaluate/submit")
async def evaluate_submit(
    request: Request,
    display_ref: str = Form(...),
    preference: str | None = Form(default=None),
    preference_comment: str | None = Form(default=None),
    alert_verdict: str | None = Form(default=None),
    alert_comment: str | None = Form(default=None),
    missed_yes_no: str = Form(...),
    missed_category: str | None = Form(default=None),
    missed_reason: str | None = Form(default=None),
):
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(request)  # also bumps last_seen_at (sliding window)
    if session is None:
        response = RedirectResponse(url="/", status_code=303)
        if token:
            clear_session_cookie(response)
        return response

    conn = connect()
    try:
        active = _active_prompt_version(conn)
        letter = conn.execute(
            "SELECT * FROM letters WHERE display_ref = ?", (display_ref,)
        ).fetchone()
        if letter is None:
            return Response(status_code=404)  # opaque: unknown ref, like the PDF route
        ai = _select_ai_row(conn, letter["id"], active)
        if ai is None:
            return Response(status_code=404)  # no servable response to vote on

        is_real = letter["human_translation_text"] is not None
        has_alert = (ai["alert_category"] or "no_alert") != "no_alert"

        # Preference: required on real letters (A/B card shown); absent on synthetics.
        if is_real:
            if preference not in ("A", "B", "Equivalent"):
                return _reject(request, "Please choose which translation you prefer.")
            preference_val = preference
            a_is_ai_val = 1 if selection.a_is_ai(session["id"], letter["id"]) else 0
        else:
            preference_val = None
            a_is_ai_val = None

        # Alert verdict: required iff the served response raised an alert.
        if has_alert:
            if alert_verdict not in ("Correct", "Incorrect", "Mixed"):
                return _reject(request, "Please tell us whether the alert is correct.")
        elif alert_verdict is not None:
            return _reject(request, "This letter has no alert to evaluate.")

        # Missed-issue: a required yes/no; details required (+ validated) on "yes".
        if missed_yes_no not in ("yes", "no"):
            return _reject(request, "Please tell us whether the AI missed an issue.")
        if missed_yes_no == "yes":
            if missed_category not in categories.selectable_for_missed_ids():
                return _reject(request, "Please choose a valid issue category.")
            if not (missed_reason and missed_reason.strip()):
                return _reject(request, "Please describe the issue the AI missed.")
            missed_category_val, missed_reason_val = missed_category, missed_reason
        else:
            missed_category_val = missed_reason_val = None

        recorded = _persist_evaluation(
            conn,
            session_id=session["id"],
            letter_id=letter["id"],
            ai_response_id=ai["id"],
            preference=preference_val,
            a_is_ai=a_is_ai_val,
            preference_comment=(preference_comment or "").strip() or None,
            alert_verdict=alert_verdict,
            alert_comment=(alert_comment or "").strip() or None,
            missed_yes=1 if missed_yes_no == "yes" else 0,
            missed_category=missed_category_val,
            missed_reason=missed_reason_val,
        )

        # PRG: a fresh vote shows the rotating thank-you (saved=1); an idempotent
        # resubmit (back button) silently advances without re-thanking.
        target = "/evaluate?saved=1" if recorded else "/evaluate"
        response = RedirectResponse(url=target, status_code=303)
        set_session_cookie(response, token)  # sliding refresh
        return response
    finally:
        conn.close()


@router.get("/evaluate/done")
async def evaluate_done(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(request)
    if session is None:
        response = RedirectResponse(url="/", status_code=303)
        if token:
            clear_session_cookie(response)
        return response
    conn = connect()
    try:
        evaluated_count = len(_voted_ids(conn, session["id"]))
    finally:
        conn.close()
    response = templates.TemplateResponse(
        request=request,
        name="evaluate_done.html",
        context={"evaluated_count": evaluated_count},
    )
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
