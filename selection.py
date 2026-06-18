"""Pure letter-selection + A/B-assignment logic (no I/O, no FastAPI).

Deterministic per session: the ordering and the A/B side mapping are seeded with
sha1 (NOT Python's hash(), which is salted per process via PYTHONHASHSEED and
would flip the A/B chips on a server restart).
"""
import hashlib


def letter_sort_key(session_id: int, letter_id: int) -> int:
    """Stable, per-session, cross-session-uncorrelated ordering key for a letter."""
    return int(hashlib.sha1(f"{session_id}:{letter_id}".encode()).hexdigest(), 16)


def a_is_ai(session_id: int, letter_id: int) -> bool:
    """Whether side A is the AI translation for this (session, letter)."""
    digest = hashlib.sha1(f"{session_id}:{letter_id}:ab".encode()).hexdigest()
    return int(digest, 16) % 2 == 0


def show_ab_card(human_translation) -> bool:
    """A/B comparison only applies when a human translation exists."""
    return human_translation is not None


def matches_session_langs(letter, source_langs, target_langs) -> bool:
    """The volunteer must be able to read the letter's source and write its target."""
    return letter["source_lang"] in source_langs and letter["target_lang"] in target_langs


def select_next_letter(session_id, letters, voted_ids, source_langs, target_langs):
    """The next unrated, language-matching letter in per-session order, or None.

    ``letters`` are the servable candidates — already filtered by the caller's
    query to those with a usable, non-safety-filtered AI response.
    """
    candidates = [
        letter
        for letter in letters
        if letter["id"] not in voted_ids
        and matches_session_langs(letter, source_langs, target_langs)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda letter: letter_sort_key(session_id, letter["id"]))


def served_set(session_id, letters, voted_ids, source_langs, target_langs):
    """{letters this session has voted on} union {its current next-unrated letter}."""
    result = set(voted_ids)
    nxt = select_next_letter(session_id, letters, voted_ids, source_langs, target_langs)
    if nxt is not None:
        result.add(nxt["id"])
    return result
