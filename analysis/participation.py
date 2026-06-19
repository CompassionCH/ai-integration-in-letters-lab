"""Participation aggregation: who evaluated, how much, and on which letters.

Produces the dashboard's participation block — distinct sessions, total votes, a
votes-per-letter histogram — and the per-translator breakdown table.

PURE function over caller-supplied rows (dict / sqlite3.Row); it never reads the
database. ``sessions`` is the id -> name/languages lookup; ``votes`` carry
``translator_id`` (the session id), ``letter_id``, ``voted_at`` and (joined from
ai_responses) ``prompt_version``.

The per-translator table DEDUPES by name: a volunteer who started several
sessions is one row, aggregating their votes / timestamps / language pairs.
``n_sessions`` by contrast counts distinct sessions (not people).
"""
from __future__ import annotations

from dataclasses import dataclass

from analysis._common import get_value, passes_filters

_PARTICIPATION_FILTERS = ("translator_id", "letter_id", "prompt_version")


@dataclass(frozen=True)
class TranslatorStats:
    first_name: str | None
    last_name: str | None
    n_votes: int
    first_vote_at: str | None
    last_vote_at: str | None
    language_pairs: list[tuple[str, str]]  # sorted (source, target), declared


@dataclass(frozen=True)
class ParticipationReport:
    n_sessions: int
    n_votes: int
    votes_per_letter: dict  # letter_id -> vote count (the histogram)
    per_translator: list[TranslatorStats]  # ordered by n_votes desc


def _csv_set(csv) -> set[str]:
    return {item for item in (csv or "").split(",") if item}


def _language_pairs(session) -> set[tuple[str, str]]:
    """Declared (source, target) pairs = Cartesian product of the session's
    source × target language selections."""
    sources = _csv_set(get_value(session, "source_langs_csv"))
    targets = _csv_set(get_value(session, "target_langs_csv"))
    return {(s, t) for s in sources for t in targets}


def aggregate_participation(sessions, votes, filters=None) -> ParticipationReport:
    """Roll up participation over the (filtered) votes. ``filters`` honors
    ``translator_id`` (the session id), ``letter_id`` and ``prompt_version``
    (``"__all__"`` or an absent key disables a dimension). per_translator dedupes
    by (first_name, last_name); n_sessions counts the distinct sessions that cast
    a matching vote."""
    filters = filters or {}
    session_lookup = {get_value(s, "id"): s for s in sessions}

    n_votes = 0
    voting_session_ids = set()
    votes_per_letter: dict = {}
    by_name: dict = {}  # (first, last) -> mutable accumulator

    for vote in votes:
        if not passes_filters(vote, filters, keys=_PARTICIPATION_FILTERS):
            continue
        n_votes += 1
        session_id = get_value(vote, "translator_id")
        voting_session_ids.add(session_id)

        letter_id = get_value(vote, "letter_id")
        votes_per_letter[letter_id] = votes_per_letter.get(letter_id, 0) + 1

        session = session_lookup.get(session_id)
        first = get_value(session, "first_name") if session is not None else None
        last = get_value(session, "last_name") if session is not None else None
        acc = by_name.setdefault(
            (first, last),
            {"n_votes": 0, "first_at": None, "last_at": None, "pairs": set()},
        )
        acc["n_votes"] += 1
        voted_at = get_value(vote, "voted_at")
        if voted_at is not None:
            acc["first_at"] = voted_at if acc["first_at"] is None else min(acc["first_at"], voted_at)
            acc["last_at"] = voted_at if acc["last_at"] is None else max(acc["last_at"], voted_at)
        if session is not None:
            acc["pairs"] |= _language_pairs(session)

    per_translator = [
        TranslatorStats(
            first_name=first,
            last_name=last,
            n_votes=acc["n_votes"],
            first_vote_at=acc["first_at"],
            last_vote_at=acc["last_at"],
            language_pairs=sorted(acc["pairs"]),
        )
        for (first, last), acc in by_name.items()
    ]
    # Most-active translators first; name as a deterministic tiebreak.
    per_translator.sort(key=lambda t: (-t.n_votes, t.first_name or "", t.last_name or ""))

    return ParticipationReport(
        n_sessions=len(voting_session_ids),
        n_votes=n_votes,
        votes_per_letter=votes_per_letter,
        per_translator=per_translator,
    )
