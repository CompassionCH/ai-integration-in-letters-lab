"""Unit tests for the pure letter-selection + hashing logic."""
import hashlib

from selection import (
    a_is_ai,
    letter_sort_key,
    matches_session_langs,
    select_next_letter,
    served_set,
    show_ab_card,
)


def _letter(letter_id, source="en", target="fr"):
    return {"id": letter_id, "source_lang": source, "target_lang": target}


def test_sort_key_matches_sha1_formula():
    expected = int(hashlib.sha1(b"7:5").hexdigest(), 16)
    assert letter_sort_key(7, 5) == expected


def test_sort_key_deterministic():
    assert letter_sort_key(7, 5) == letter_sort_key(7, 5)


def test_a_is_ai_matches_sha1_formula():
    expected = int(hashlib.sha1(b"7:5:ab").hexdigest(), 16) % 2 == 0
    assert a_is_ai(7, 5) is expected


def test_a_is_ai_deterministic():
    assert a_is_ai(7, 5) == a_is_ai(7, 5)


def test_show_ab_card():
    assert show_ab_card("Bonjour") is True
    assert show_ab_card(None) is False


def test_matches_session_langs():
    letter = _letter(1, source="en", target="fr")
    assert matches_session_langs(letter, {"en"}, {"fr"}) is True
    assert matches_session_langs(letter, {"de"}, {"fr"}) is False  # source not handled
    assert matches_session_langs(letter, {"en"}, {"de"}) is False  # target not handled


def test_select_next_letter_orders_by_sort_key():
    letters = [_letter(1), _letter(2), _letter(3)]
    expected = min(letters, key=lambda l: letter_sort_key(7, l["id"]))
    nxt = select_next_letter(7, letters, set(), {"en"}, {"fr"})
    assert nxt["id"] == expected["id"]


def test_select_next_letter_skips_voted():
    letters = [_letter(1), _letter(2), _letter(3)]
    first = min(letters, key=lambda l: letter_sort_key(7, l["id"]))
    nxt = select_next_letter(7, letters, {first["id"]}, {"en"}, {"fr"})
    assert nxt["id"] != first["id"]


def test_select_next_letter_filters_langs():
    letters = [_letter(1, source="de", target="fr")]
    assert select_next_letter(7, letters, set(), {"en"}, {"fr"}) is None


def test_select_next_letter_none_when_all_voted():
    letters = [_letter(1), _letter(2)]
    assert select_next_letter(7, letters, {1, 2}, {"en"}, {"fr"}) is None


def test_served_set_is_voted_plus_current_next():
    letters = [_letter(1), _letter(2), _letter(3)]
    voted = {2}
    nxt = select_next_letter(7, letters, voted, {"en"}, {"fr"})
    assert served_set(7, letters, voted, {"en"}, {"fr"}) == {2, nxt["id"]}


def test_served_set_is_just_voted_when_no_more():
    letters = [_letter(1), _letter(2)]
    assert served_set(7, letters, {1, 2}, {"en"}, {"fr"}) == {1, 2}
