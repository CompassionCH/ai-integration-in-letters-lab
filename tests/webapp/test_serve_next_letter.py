"""Tests for the serve-next-letter endpoint + the session-bound PDF route."""
import re

import selection
from db import connect


def _insert_letter(
    db_path,
    display_ref,
    *,
    source="en",
    target="fr",
    human: str | None = "Human translation",
    safety: str | None = "ok",
    ai_text="AI translation",
    alert: str | None = None,
    prompt_version="v1",
    letter_type="real",
):
    """Insert a letter + its ai_response; returns the new letter id."""
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO letters (display_ref, type, pdf_path, direction, source_lang,"
            " target_lang, country, child_official, child_preferred, child_sex, child_age,"
            " sponsor_first, sponsor_sex, sponsor_age, human_translation_text)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                display_ref, letter_type, f"{letter_type}/{display_ref}.pdf", "child_to_sponsor",
                source, target, "Testland", "Mira", "Mira", "F", 9, "Tom", "M", 40, human,
            ),
        )
        letter_id = cur.lastrowid
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " alert_category, safety_filter_status) VALUES (?,?,?,?,?,?)",
            (letter_id, prompt_version, "gemini-test", ai_text, alert, safety),
        )
        conn.commit()
        return letter_id
    finally:
        conn.close()


async def test_serves_next_unrated_letter(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111")
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "aaa11111" in resp.text


async def test_no_language_match_shows_empty_state(logged_in, tmp_db):
    client, _ = logged_in  # session speaks en + fr
    # The only letter is de->it: the volunteer handles neither side, so NO corpus
    # letter matches their languages -> the distinct empty state (NOT the done page,
    # which is reserved for "you evaluated everything you could").
    _insert_letter(tmp_db, "de000001", source="de", target="it")
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "No letters match your languages" in resp.text


async def test_end_of_corpus_redirects_done(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111")
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
            " SELECT ?, ?, id, 'A', 1 FROM ai_responses WHERE letter_id = ?",
            (session_id, letter_id, letter_id),
        )
        conn.commit()
    finally:
        conn.close()
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate/done"


async def test_ordering_is_deterministic_by_sort_key(logged_in, tmp_db):
    client, session_id = logged_in
    ids = {ref: _insert_letter(tmp_db, ref) for ref in ("aaa00001", "bbb00002", "ccc00003")}
    expected_ref = min(ids, key=lambda ref: selection.letter_sort_key(session_id, ids[ref]))
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert expected_ref in resp.text


async def test_ab_mapping_matches_sha1(logged_in, tmp_db):
    client, session_id = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", human="HUMANTEXT", ai_text="AITEXT")
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    text = resp.text
    assert "AITEXT" in text and "HUMANTEXT" in text
    # The template renders the A column before the B column; A holds the AI text
    # exactly when the sha1 mapping says so. (Cross-restart stability comes from
    # the sha1 formula itself, asserted directly in test_selection.)
    if selection.a_is_ai(session_id, letter_id):
        assert text.index("AITEXT") < text.index("HUMANTEXT")
    else:
        assert text.index("HUMANTEXT") < text.index("AITEXT")


async def test_show_ab_card_false_when_no_human_translation(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "syn00001", human=None, ai_text="AITEXT")
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "AITEXT" not in resp.text  # A/B card hidden -> translations not rendered


async def test_missing_session_cookie_redirects_home(invited_client):
    resp = await invited_client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


async def test_unknown_session_clears_cookie_and_redirects(invited_client, tmp_db):
    invited_client.cookies.set("session_id", "no-such-token")
    resp = await invited_client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "session_id=" in set_cookie
    assert "max-age=0" in set_cookie or "expires=" in set_cookie  # cookie cleared


async def test_safety_filtered_letter_is_excluded(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "blk00001", safety="blocked")
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate/done"


async def test_no_corpus_id_in_rendered_page(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", letter_type="synthetic")
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert not re.search(r"\b[RSI]-\d", resp.text)  # no R-/S-/I- corpus stratum ids
    assert "synthetic" not in resp.text.lower()  # the experimental stratum (type) is not leaked


async def test_pdf_404_without_session(invited_client):
    resp = await invited_client.get("/letters/aaa11111.pdf")
    assert resp.status_code == 404


async def test_pdf_bound_to_served_set(logged_in, tmp_db, tmp_path, monkeypatch):
    client, session_id = logged_in
    id_a = _insert_letter(tmp_db, "aaa00001")
    id_b = _insert_letter(tmp_db, "bbb00002")
    # With no votes, the served set = {current next} = the min-sort-key letter only.
    if selection.letter_sort_key(session_id, id_a) < selection.letter_sort_key(session_id, id_b):
        served_ref, unserved_ref = "aaa00001", "bbb00002"
    else:
        served_ref, unserved_ref = "bbb00002", "aaa00001"

    letters_dir = tmp_path / "letters"
    (letters_dir / "real").mkdir(parents=True)
    for ref in (served_ref, unserved_ref):
        (letters_dir / "real" / f"{ref}.pdf").write_bytes(b"%PDF-1.4 test")
    monkeypatch.setenv("LETTERS_DIR", str(letters_dir))

    served = await client.get(f"/letters/{served_ref}.pdf")
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"

    unserved = await client.get(f"/letters/{unserved_ref}.pdf")
    assert unserved.status_code == 404  # valid ref, but not in this session's served set


async def test_null_safety_status_excluded_from_serving(logged_in, tmp_db):
    client, _ = logged_in
    _insert_letter(tmp_db, "nul00001", safety=None)  # NULL status -> not 'ok' -> excluded
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate/done"


def test_warn_safety_filtered_lists_excluded(tmp_db, caplog):
    import logging

    from routes.evaluate import warn_safety_filtered

    _insert_letter(tmp_db, "okk00001", safety="ok")
    _insert_letter(tmp_db, "blk00001", safety="blocked")
    _insert_letter(tmp_db, "nul00001", safety=None)
    with caplog.at_level(logging.WARNING):
        warn_safety_filtered()
    assert "blk00001" in caplog.text  # explicit non-ok -> warned
    assert "nul00001" in caplog.text  # NULL -> warned (matches the serving exclusion)
    assert "okk00001" not in caplog.text  # ok -> served, not warned


async def test_active_prompt_version_is_chosen(logged_in, tmp_db):
    client, _ = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="OLD AI")
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " safety_filter_status) VALUES (?, 'v2', 'gemini-test', 'NEW AI', 'ok')",
            (letter_id,),
        )
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v2')")
        conn.commit()
    finally:
        conn.close()
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    # The chosen translation proves the active version was selected; the volunteer
    # UI no longer surfaces the internal prompt_version string.
    assert "NEW AI" in resp.text and "OLD AI" not in resp.text  # active version chosen


async def test_falls_back_and_warns_when_active_version_missing(logged_in, tmp_db, caplog):
    import logging

    client, _ = logged_in
    _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="V1 AI")
    conn = connect(tmp_db)
    try:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v9')")
        conn.commit()
    finally:
        conn.close()
    with caplog.at_level(logging.WARNING):
        resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "V1 AI" in resp.text  # fell back to the only existing response
    assert "v9" in caplog.text or "fall" in caplog.text.lower()  # fallback warned


async def test_pdf_served_for_voted_past_letter(logged_in, tmp_db, tmp_path, monkeypatch):
    client, session_id = logged_in
    ids = {ref: _insert_letter(tmp_db, ref) for ref in ("aaa00001", "bbb00002", "ccc00003")}
    ordered = sorted(ids, key=lambda ref: selection.letter_sort_key(session_id, ids[ref]))
    voted_ref, _, unserved_ref = ordered
    # Vote on the first letter: it becomes a 'voted (past)' member; the current
    # next advances to the second; the third is never served.
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
            " SELECT ?, ?, id, 'A', 1 FROM ai_responses WHERE letter_id = ?",
            (session_id, ids[voted_ref], ids[voted_ref]),
        )
        conn.commit()
    finally:
        conn.close()

    letters_dir = tmp_path / "letters"
    (letters_dir / "real").mkdir(parents=True)
    for ref in ordered:
        (letters_dir / "real" / f"{ref}.pdf").write_bytes(b"%PDF-1.4 test")
    monkeypatch.setenv("LETTERS_DIR", str(letters_dir))

    # voted (past) letter still serves — via the voted branch of the served set
    assert (await client.get(f"/letters/{voted_ref}.pdf")).status_code == 200
    # never-served letter 404s even though its ref is valid
    assert (await client.get(f"/letters/{unserved_ref}.pdf")).status_code == 404


async def test_safety_warning_matches_serving_for_multiversion(logged_in, tmp_db, caplog):
    import logging

    from routes.evaluate import warn_safety_filtered

    client, _ = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="OLD", safety="blocked")
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " safety_filter_status) VALUES (?, 'v2', 'gemini-test', 'NEW', 'ok')",
            (letter_id,),
        )
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v2')")
        conn.commit()
    finally:
        conn.close()
    # chosen response (active v2) is ok -> served, and NOT falsely warned despite the stale blocked v1
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "NEW" in resp.text
    with caplog.at_level(logging.WARNING):
        warn_safety_filtered()
    assert "aaa11111" not in caplog.text


async def test_active_version_blocked_excludes_letter(logged_in, tmp_db):
    client, _ = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="OLDOK", safety="ok")
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " safety_filter_status) VALUES (?, 'v2', 'gemini-test', 'NEWBLOCKED', 'blocked')",
            (letter_id,),
        )
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v2')")
        conn.commit()
    finally:
        conn.close()
    # chosen response (active v2) is blocked -> excluded, even though an older ok exists
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate/done"


async def test_fallback_picks_most_recent_processed(logged_in, tmp_db):
    client, _ = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="OLDER")
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " safety_filter_status, processed_at)"
            " VALUES (?, 'v2', 'gemini-test', 'NEWER', 'ok', '2030-01-01 00:00:00')",
            (letter_id,),
        )
        conn.execute(
            "UPDATE ai_responses SET processed_at = '2020-01-01 00:00:00'"
            " WHERE letter_id = ? AND prompt_version = 'v1'",
            (letter_id,),
        )
        conn.commit()
    finally:
        conn.close()
    # no active version -> fall back to the most-recent processed_at row
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "NEWER" in resp.text and "OLDER" not in resp.text


async def test_fallback_arm_blocked_excludes_and_warns(logged_in, tmp_db, caplog):
    import logging

    from routes.evaluate import warn_safety_filtered

    client, _ = logged_in
    # only response is v1='blocked'; active points at a missing version -> fallback to v1
    _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="X", safety="blocked")
    conn = connect(tmp_db)
    try:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v9')")
        conn.commit()
    finally:
        conn.close()
    # serving resolves the fallback (v1, blocked) -> excluded
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/evaluate/done"
    # the warning resolves the identical fallback -> warns the same letter
    with caplog.at_level(logging.WARNING):
        warn_safety_filtered()
    assert "aaa11111" in caplog.text


async def test_fallback_tie_break_prefers_higher_id(logged_in, tmp_db):
    client, _ = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", prompt_version="v1", ai_text="FIRST")
    conn = connect(tmp_db)
    try:
        ts = conn.execute(
            "SELECT processed_at FROM ai_responses WHERE letter_id = ?", (letter_id,)
        ).fetchone()["processed_at"]
        # identical processed_at -> tie broken by id DESC (the later-inserted row wins)
        conn.execute(
            "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
            " safety_filter_status, processed_at) VALUES (?, 'v2', 'gemini-test', 'SECOND', 'ok', ?)",
            (letter_id, ts),
        )
        conn.commit()
    finally:
        conn.close()
    resp = await client.get("/evaluate", follow_redirects=False)
    assert resp.status_code == 200
    assert "SECOND" in resp.text and "FIRST" not in resp.text


async def test_voted_letter_pdf_serves_even_after_filtered(logged_in, tmp_db, tmp_path, monkeypatch):
    client, session_id = logged_in
    letter_id = _insert_letter(tmp_db, "aaa11111", safety="ok")
    conn = connect(tmp_db)
    try:
        conn.execute(
            "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
            " SELECT ?, ?, id, 'A', 1 FROM ai_responses WHERE letter_id = ?",
            (session_id, letter_id, letter_id),
        )
        # the letter's chosen response is later safety-filtered -> no longer a serving candidate
        conn.execute("UPDATE ai_responses SET safety_filter_status = 'blocked' WHERE letter_id = ?", (letter_id,))
        conn.commit()
    finally:
        conn.close()
    letters_dir = tmp_path / "letters"
    (letters_dir / "real").mkdir(parents=True)
    (letters_dir / "real" / "aaa11111.pdf").write_bytes(b"%PDF-1.4 test")
    monkeypatch.setenv("LETTERS_DIR", str(letters_dir))
    # served set includes voted letters unconditionally (review-past), so the PDF still serves
    assert (await client.get("/letters/aaa11111.pdf")).status_code == 200


async def test_done_page_shows_evaluated_count(logged_in, tmp_db):
    client, session_id = logged_in
    for ref in ("aaa00001", "bbb00002"):
        lid = _insert_letter(tmp_db, ref)
        conn = connect(tmp_db)
        try:
            conn.execute(
                "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai)"
                " SELECT ?, ?, id, 'A', 1 FROM ai_responses WHERE letter_id = ?",
                (session_id, lid, lid),
            )
            conn.commit()
        finally:
            conn.close()
    resp = await client.get("/evaluate/done")
    assert resp.status_code == 200
    assert "2 letters" in resp.text  # the evaluated count, pluralised
