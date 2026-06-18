"""Smoke tests for the application skeleton."""
import os

# The perimeter gate needs an invite token, and the ASGI test client speaks plain
# HTTP — so make Secure cookies round-trip. Set these before importing the app;
# config reads the environment lazily, and load_dotenv() will not override them.
os.environ.setdefault("ACCESS_TOKEN", "test-invite-token")
os.environ.setdefault("COOKIE_SECURE", "false")

import httpx
import pytest

from main import app

BASE_URL = "http://testserver"


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_security_headers_present(client):
    resp = await client.get("/health")
    assert resp.headers["x-robots-tag"] == "noindex, nofollow"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-frame-options"] == "SAMEORIGIN"


async def test_robots_txt(client):
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.text.startswith("User-agent: *")
    assert "Disallow: /" in resp.text


async def test_landing_without_invite_serves_stub(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "translation platform" in resp.text.lower()


async def test_invite_query_sets_cookie_and_redirects(client):
    resp = await client.get(
        "/", params={"invite": "test-invite-token"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "invite" in resp.cookies
    # The client now holds the cookie; the next request reaches the real landing.
    landing = await client.get("/")
    assert landing.status_code == 200
    assert "Open Letter Lab" in landing.text
    assert "translation platform" not in landing.text.lower()


async def test_invalid_invite_serves_stub(client):
    resp = await client.get("/", params={"invite": "wrong"}, follow_redirects=False)
    assert resp.status_code == 200
    assert "translation platform" in resp.text.lower()
