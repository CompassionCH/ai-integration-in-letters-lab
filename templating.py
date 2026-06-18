"""Shared Jinja2 templates instance.

Kept in its own module so both the route handlers and the perimeter middleware
(which renders the invite stub) can import it without importing ``main``.
"""
from __future__ import annotations

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
