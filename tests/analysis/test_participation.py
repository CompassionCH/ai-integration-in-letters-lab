"""Tests for analysis.participation — sessions/votes participation metrics (pure)."""
from analysis.participation import (
    ParticipationReport,
    aggregate_participation,
)


def _session(session_id, first, last, *, source="en", target="fr"):
    return {
        "id": session_id,
        "first_name": first,
        "last_name": last,
        "source_langs_csv": source,
        "target_langs_csv": target,
    }


def _vote(translator_id, letter_id, *, voted_at="2026-01-01 00:00:00", prompt_version="v1"):
    return {
        "translator_id": translator_id,
        "letter_id": letter_id,
        "voted_at": voted_at,
        "prompt_version": prompt_version,
    }


def test_empty_input():
    r = aggregate_participation([], [])
    assert r == ParticipationReport(n_sessions=0, n_votes=0, votes_per_letter={}, per_translator=[])


def test_dedupes_translators_by_name_but_counts_sessions():
    sessions = [
        _session(1, "Alex", "Ng", source="en", target="fr"),
        _session(2, "Alex", "Ng", source="en", target="de"),  # same person, 2nd session
        _session(3, "Bo", "Li", source="fr", target="de"),
    ]
    votes = [_vote(1, 10), _vote(1, 11), _vote(2, 12), _vote(3, 10)]
    r = aggregate_participation(sessions, votes)
    assert r.n_sessions == 3  # distinct sessions that voted (NOT deduped by name)
    assert r.n_votes == 4
    assert [(t.first_name, t.last_name, t.n_votes) for t in r.per_translator] == [
        ("Alex", "Ng", 3),  # two sessions merged into one person -> 3 votes
        ("Bo", "Li", 1),
    ]
    assert set(r.per_translator[0].language_pairs) == {("en", "fr"), ("en", "de")}


def test_votes_per_letter_histogram():
    r = aggregate_participation([_session(1, "A", "Z")], [_vote(1, 10), _vote(1, 10), _vote(1, 11)])
    assert r.votes_per_letter == {10: 2, 11: 1}


def test_per_translator_ordered_by_votes_desc():
    sessions = [_session(1, "Few", "X"), _session(2, "Many", "Y")]
    votes = [_vote(1, 10), _vote(2, 10), _vote(2, 11), _vote(2, 12)]
    r = aggregate_participation(sessions, votes)
    assert [t.first_name for t in r.per_translator] == ["Many", "Few"]


def test_first_and_last_vote_timestamps():
    sessions = [_session(1, "A", "Z")]
    votes = [
        _vote(1, 10, voted_at="2026-03-02 10:00:00"),
        _vote(1, 11, voted_at="2026-03-01 09:00:00"),
        _vote(1, 12, voted_at="2026-03-03 11:00:00"),
    ]
    t = aggregate_participation(sessions, votes).per_translator[0]
    assert t.first_vote_at == "2026-03-01 09:00:00"
    assert t.last_vote_at == "2026-03-03 11:00:00"


def test_language_pairs_cartesian_product():
    sessions = [_session(1, "A", "Z", source="en,fr", target="de,it")]
    r = aggregate_participation(sessions, [_vote(1, 10)])
    assert set(r.per_translator[0].language_pairs) == {
        ("en", "de"), ("en", "it"), ("fr", "de"), ("fr", "it"),
    }


def test_same_language_pairs_excluded():
    # Spoken-set model: both columns hold the same set, so without filtering
    # (en, en) etc. would appear. Only cross-language pairs are kept.
    sessions = [_session(1, "A", "Z", source="en,fr,de", target="en,fr,de")]
    r = aggregate_participation(sessions, [_vote(1, 10)])
    pairs = set(r.per_translator[0].language_pairs)
    assert ("en", "en") not in pairs
    assert ("fr", "fr") not in pairs
    assert ("de", "de") not in pairs
    assert pairs == {
        ("en", "fr"), ("en", "de"), ("fr", "en"),
        ("fr", "de"), ("de", "en"), ("de", "fr"),
    }


def test_filter_by_dimensions_and_all_sentinel():
    sessions = [_session(1, "A", "Z"), _session(2, "B", "Y")]
    votes = [_vote(1, 10, prompt_version="v1"), _vote(2, 11, prompt_version="v2")]
    assert aggregate_participation(sessions, votes, {"prompt_version": "v1"}).n_votes == 1
    assert aggregate_participation(sessions, votes, {"letter_id": 10}).n_votes == 1
    assert aggregate_participation(sessions, votes, {"translator_id": 2}).n_votes == 1
    assert aggregate_participation(sessions, votes, {"prompt_version": "__all__"}).n_votes == 2
    assert aggregate_participation(sessions, votes, {}).n_votes == 2


def test_filtered_n_sessions_counts_only_matching_voting_sessions():
    sessions = [_session(1, "A", "Z"), _session(2, "B", "Y")]
    votes = [_vote(1, 10), _vote(2, 11)]
    r = aggregate_participation(sessions, votes, {"letter_id": 10})
    assert r.n_sessions == 1  # only session 1 voted on letter 10
    assert r.n_votes == 1


def test_orphan_vote_with_unknown_session():
    # Defensive: a vote whose session isn't in the lookup still counts (name None).
    r = aggregate_participation([], [_vote(99, 10)])
    assert r.n_votes == 1
    assert r.n_sessions == 1
    only = r.per_translator[0]
    assert only.first_name is None and only.last_name is None
    assert only.language_pairs == []
