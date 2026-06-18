"""Application entrypoint.

Load the ``.env`` file into ``os.environ`` first, configure logging once, then
build and wire the FastAPI app. Nothing above ``load_dotenv()`` may read config.
"""
from __future__ import annotations

# 1) Load .env BEFORE anything reads configuration.
from dotenv import load_dotenv

load_dotenv()

# 2) Configure logging once, for the whole process.
import logging

import config

logging.basicConfig(
    level=config.log_level(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 3) Build the app.
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import security
from routes import evaluate, health, pages, session


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warn about letters a safety filter excludes from serving (best-effort).
    evaluate.warn_safety_filtered()
    yield


app = FastAPI(title="Open Letter Lab", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Middleware registration order matters: Starlette runs the LAST-added middleware
# outermost. Add the gate first (inner) and the header layer last (outer) so the
# headers apply to every response, including the gate's stub page and redirects.
app.add_middleware(BaseHTTPMiddleware, dispatch=security.invite_gate)
app.add_middleware(BaseHTTPMiddleware, dispatch=security.security_headers)

app.include_router(health.router)
app.include_router(pages.router)
app.include_router(session.router)
app.include_router(evaluate.router)

logger.info("Application configured (cookie_secure=%s)", config.cookie_secure())
