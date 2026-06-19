"""Smoke tests for the start page (GET /start) and its inline error path."""


async def test_start_page_renders_form(invited_client):
    resp = await invited_client.get("/start")
    assert resp.status_code == 200
    text = resp.text
    # Posts to the session-start endpoint with the expected field names.
    assert 'action="/session/start"' in text
    assert 'name="first_name"' in text
    assert 'name="last_name"' in text
    assert 'name="source_langs"' in text
    assert 'name="target_langs"' in text
    # The four supported language codes are offered as options.
    for code in ("fr", "de", "it", "en"):
        assert f'value="{code}"' in text


async def test_invalid_languages_rerender_form_inline(invited_client):
    resp = await invited_client.post(
        "/session/start",
        data={"first_name": "Mira", "last_name": "T", "source_langs": ["en"], "target_langs": []},
        follow_redirects=False,
    )
    assert resp.status_code == 422
    text = resp.text
    # The error renders inline on the form (not a separate page) and keeps input.
    assert 'action="/session/start"' in text
    assert "at least one source and one target" in text
    assert 'value="Mira"' in text
