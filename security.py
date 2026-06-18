"""Application perimeter: response security headers + the invite-token gate.

Both are registered as middleware in ``main``. The security-headers middleware is
the outermost layer so its headers land on *every* response, including the gate's
stub page and redirects.
"""
from __future__ import annotations

import hmac
import logging

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

import config
from templating import templates

logger = logging.getLogger(__name__)

INVITE_COOKIE = "invite"
# ~60 days; the invite token is set once and never rotated.
INVITE_COOKIE_MAX_AGE = 60 * 60 * 24 * 60


def _is_allowlisted(path: str) -> bool:
    """Paths reachable without an invite token."""
    if path in {"/health", "/robots.txt"}:
        return True
    if path.startswith("/static/"):
        return True
    # /admin carries its own, stronger ADMIN_TOKEN gate (added by a later task).
    if path == "/admin" or path.startswith("/admin/"):
        return True
    return False


def _serve_stub(request: Request) -> Response:
    """Friendly page shown when no valid invite is present. No app function here."""
    return templates.TemplateResponse(
        request=request, name="invite_stub.html", context={}, status_code=200
    )


async def invite_gate(request: Request, call_next):
    """Gate every non-allowlisted route behind the shared invite token.

    Valid access is ``?invite=<ACCESS_TOKEN>`` in the query (which we then move
    into an HttpOnly cookie and 303-redirect to strip from the URL) or a prior
    ``invite`` cookie equal to ``ACCESS_TOKEN``. Tokens are compared in constant
    time. Anything else gets the stub page.
    """
    path = request.url.path
    if _is_allowlisted(path):
        return await call_next(request)

    try:
        expected = config.access_token()
    except RuntimeError:
        # Misconfiguration: fail closed rather than expose the app.
        logger.error("ACCESS_TOKEN is not set; denying access to %s", path)
        return _serve_stub(request)

    # 1) Token in the query string -> set the cookie, then redirect to the clean
    #    path so the token leaves the URL bar / history / access logs.
    query_token = request.query_params.get("invite")
    if query_token is not None and hmac.compare_digest(query_token, expected):
        redirect = RedirectResponse(url=path, status_code=303)
        redirect.set_cookie(
            key=INVITE_COOKIE,
            value=expected,
            max_age=INVITE_COOKIE_MAX_AGE,
            httponly=True,
            secure=config.cookie_secure(),
            samesite="lax",
            path="/",
        )
        return redirect

    # 2) Token already in the cookie.
    cookie_token = request.cookies.get(INVITE_COOKIE)
    if cookie_token is not None and hmac.compare_digest(cookie_token, expected):
        return await call_next(request)

    # No valid access.
    return _serve_stub(request)


async def security_headers(request: Request, call_next):
    """Add no-index + privacy/clickjacking headers to every response.

    HSTS is intentionally NOT set here; the TLS-terminating reverse proxy owns it.
    """
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response
