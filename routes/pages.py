"""Public pages: the landing page and robots.txt."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from templating import templates

router = APIRouter()


@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="home.html", context={})


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    # The tool serves real correspondence on a public host: never index it.
    return "User-agent: *\nDisallow: /\n"
