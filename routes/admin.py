"""Admin perimeter: the read-only dashboard, the non-blind admin PDF route, and
the active-prompt-version settings endpoints.

Auth is a deliberately simple shared-secret scheme (one admin, behind a private
HTTPS subdomain). The admin token is accepted ONCE via ``?token=`` or an
``Authorization: Bearer`` header, then an HttpOnly ``admin_session`` cookie
carries auth on later requests — so the secret lands in the access log at most
once per cookie lifetime. The cookie payload is a constant HMAC of ``"admin"``
keyed by the admin token: unguessable, but constant for anyone who knows the
token (an accepted risk for a PoC with a single admin user). The ``/admin``
paths are allow-listed out of the invite-token gate in ``security``; this
module is their only protection.

The metric blocks arrive with the analysis layer and the real template; this
endpoint ships a minimal, context-complete stub so it stands alone.
"""
from __future__ import annotations

import hmac
import logging
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

import config
from db import connect
from templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

ADMIN_COOKIE = "admin_session"
ADMIN_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days, like the session cookie
# One-shot flash (e.g. a coverage warning after a version switch): set on the POST
# redirect, consumed + cleared by the next /admin render.
ADMIN_FLASH_COOKIE = "admin_flash"
ADMIN_FLASH_MAX_AGE = 30  # seconds — just long enough to survive the redirect
ACTIVE_VERSION_KEY = "active_prompt_version"


def _expected_cookie() -> str:
    """The constant value a valid ``admin_session`` cookie must carry."""
    return hmac.new(config.admin_token().encode(), b"admin", "sha256").hexdigest()


def _has_admin_cookie(request: Request) -> bool:
    cookie = request.cookies.get(ADMIN_COOKIE)
    # hmac.compare_digest is secrets.compare_digest — constant-time comparison.
    return cookie is not None and hmac.compare_digest(cookie, _expected_cookie())


def _token_matches(candidate: str | None) -> bool:
    """Constant-time comparison of a presented token against ADMIN_TOKEN."""
    return candidate is not None and hmac.compare_digest(candidate, config.admin_token())


def _bearer_token(request: Request) -> str | None:
    """The token from an ``Authorization: Bearer <token>`` header, if present."""
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def _set_admin_cookie(response: Response) -> None:
    response.set_cookie(
        key=ADMIN_COOKIE,
        value=_expected_cookie(),
        max_age=ADMIN_COOKIE_MAX_AGE,
        httponly=True,
        secure=config.cookie_secure(),
        samesite="lax",
        path="/",
    )


def resolve_active_prompt_version(conn) -> str | None:
    """The active prompt_version for admin/display: the explicit ``app_settings``
    value if set, else the lazy default = the most-recently processed ai_response's
    version, else None. Computed on every read — never cached, since the loader may
    populate ai_responses after the first read. Distinct from the serving selection
    in ``routes.evaluate`` (whose per-letter fallback is unchanged)."""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?", (ACTIVE_VERSION_KEY,)
    ).fetchone()
    if row is not None and row["value"]:
        return row["value"]
    row = conn.execute(
        "SELECT prompt_version FROM ai_responses ORDER BY processed_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return row["prompt_version"] if row else None


def _version_exists(conn, version) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM ai_responses WHERE prompt_version = ? LIMIT 1", (version,)
        ).fetchone()
        is not None
    )


def _coverage(conn, version) -> tuple[int, int]:
    """(# letters with an ai_response of this version, total corpus letters)."""
    covered = conn.execute(
        "SELECT COUNT(DISTINCT letter_id) AS n FROM ai_responses WHERE prompt_version = ?",
        (version,),
    ).fetchone()["n"]
    total = conn.execute("SELECT COUNT(*) AS n FROM letters").fetchone()["n"]
    return covered, total


def _active_model(conn, active_version) -> str | None:
    """The Gemini model to display: the model of the active prompt_version's
    responses if any exist, else the most-recently processed response's model."""
    if active_version is not None:
        row = conn.execute(
            "SELECT model FROM ai_responses WHERE prompt_version = ?"
            " ORDER BY processed_at DESC, id DESC LIMIT 1",
            (active_version,),
        ).fetchone()
        if row is not None:
            return row["model"]
    row = conn.execute(
        "SELECT model FROM ai_responses ORDER BY processed_at DESC, id DESC LIMIT 1"
    ).fetchone()
    return row["model"] if row else None


def _render_dashboard(request: Request) -> Response:
    """Render the dashboard — for now the active prompt_version + model header,
    plus any one-shot flash (e.g. a coverage warning after a version switch). The
    metric blocks land with the analysis layer and the real template (which
    replaces this stub)."""
    conn = connect()
    try:
        active_version = resolve_active_prompt_version(conn)
        model = _active_model(conn, active_version)
    finally:
        conn.close()
    raw_flash = request.cookies.get(ADMIN_FLASH_COOKIE)
    response = templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "active_prompt_version": active_version,
            "model": model,
            "flash": unquote(raw_flash) if raw_flash else None,
        },
    )
    if raw_flash:
        response.delete_cookie(ADMIN_FLASH_COOKIE, path="/")
    return response


@router.get("/admin")
async def admin_dashboard(request: Request):
    # 1) Already authenticated via the cookie -> render straight away.
    if _has_admin_cookie(request):
        return _render_dashboard(request)
    # 2) Bearer header, then 3) ?token query. First match wins; on success set the
    #    cookie and 302 to the clean path so the secret leaves the URL and the logs.
    if _token_matches(_bearer_token(request)) or _token_matches(
        request.query_params.get("token")
    ):
        redirect = RedirectResponse(url="/admin", status_code=302)
        _set_admin_cookie(redirect)
        return redirect
    # 4) No valid credential.
    return Response("Unauthorized", status_code=401)


@router.get("/admin/letters/{letter_id}.pdf")
async def admin_letter_pdf(letter_id: int, request: Request):
    """Serve ANY letter's PDF by its real id, gated by the admin cookie only —
    no served-set binding (admin review is non-blind by design). A physically
    separate handler from the volunteer ``/letters/<display_ref>.pdf`` route; it
    never relaxes that route's per-session binding. Lets the dashboard link the
    artefact behind each statistic."""
    if not _has_admin_cookie(request):
        return Response(status_code=401)
    conn = connect()
    try:
        letter = conn.execute(
            "SELECT pdf_path FROM letters WHERE id = ?", (letter_id,)
        ).fetchone()
    finally:
        conn.close()
    if letter is None or not letter["pdf_path"]:
        return Response(status_code=404)
    pdf_path = Path(config.letters_dir()) / letter["pdf_path"]
    if not pdf_path.is_file():
        return Response(status_code=404)
    return FileResponse(str(pdf_path), media_type="application/pdf")


@router.post("/admin/settings/active_prompt_version")
async def set_active_prompt_version(request: Request, prompt_version: str = Form(...)):
    """Set the active prompt_version (admin only). Validates the version exists,
    upserts it into app_settings, and on partial corpus coverage attaches a
    one-shot warning flash to the /admin redirect — the switch is still allowed
    (serving falls back per the selection logic)."""
    if not _has_admin_cookie(request):
        return Response(status_code=401)
    conn = connect()
    try:
        if not _version_exists(conn, prompt_version):
            return Response("Unknown prompt_version", status_code=400)
        with conn:
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at)"
                " VALUES (?, ?, CURRENT_TIMESTAMP)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at = CURRENT_TIMESTAMP",
                (ACTIVE_VERSION_KEY, prompt_version),
            )
        covered, total = _coverage(conn, prompt_version)
    finally:
        conn.close()
    response = RedirectResponse(url="/admin", status_code=303)
    if total > 0 and covered < total:
        warning = (
            f"{prompt_version} covers {covered}/{total} letters — switching will fall"
            f" back to the most recent older version for the other {total - covered}."
        )
        response.set_cookie(
            key=ADMIN_FLASH_COOKIE,
            value=quote(warning),
            max_age=ADMIN_FLASH_MAX_AGE,
            httponly=True,
            secure=config.cookie_secure(),
            samesite="lax",
            path="/",
        )
    return response


@router.get("/admin/settings/active_prompt_version")
async def get_active_prompt_version(request: Request):
    """Current active prompt_version as JSON (helper for the dashboard dropdown).
    Lazily resolved; null when no responses exist yet."""
    if not _has_admin_cookie(request):
        return Response(status_code=401)
    conn = connect()
    try:
        value = resolve_active_prompt_version(conn)
    finally:
        conn.close()
    return {"active_prompt_version": value}
