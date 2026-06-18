"""Session lifecycle: start and sign-out."""
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


def _has_supported_lang(langs: list[str]) -> bool:
    return any(lang in SUPPORTED_LANGS for lang in langs)


@router.post("/session/start")
async def session_start(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    source_langs: list[str] = Form(default=[]),
    target_langs: list[str] = Form(default=[]),
):
    if not _has_supported_lang(source_langs) or not _has_supported_lang(target_langs):
        return templates.TemplateResponse(
            request=request,
            name="session_error.html",
            context={
                "message": (
                    "Please choose at least one source and one target language "
                    "from French, German, Italian or English."
                )
            },
            status_code=422,
        )

    token = str(uuid.uuid4())
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO sessions"
            " (session_token, first_name, last_name, source_langs_csv, target_langs_csv)"
            " VALUES (?, ?, ?, ?, ?)",
            (token, first_name, last_name, ",".join(source_langs), ",".join(target_langs)),
        )
        conn.commit()
    finally:
        conn.close()

    # Log languages only — never the participant's name.
    logger.info("Session started (langs %s -> %s)", source_langs, target_langs)

    response = RedirectResponse(url="/evaluate", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        secure=config.cookie_secure(),
        samesite="lax",
        path="/",
    )
    return response


@router.post("/session/signout")
async def session_signout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return response
