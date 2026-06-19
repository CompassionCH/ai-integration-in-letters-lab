"""Admin dashboard view-model assembly.

Glue between the pure analysis aggregations and the admin route: fetches the
joined source rows from SQLite, runs all five aggregations under the active
filters, and builds the dropdown option lists. Not pure (it reads the DB), so it
lives here rather than in the ``analysis`` package — and out of the already-busy
admin route module.
"""
from __future__ import annotations

import categories
from analysis.alerts import aggregate_alert_verdicts, aggregate_missed_issues
from analysis.cost import aggregate_cost
from analysis.ground_truth import score_ground_truth
from analysis.participation import aggregate_participation
from analysis.preference import aggregate_preference

# Each aggregation gets the FULL filter dict and honors its own keys= subset, so
# a dimension it does not support (e.g. category on cost) is simply ignored.

# votes ⨝ ai_responses — preference needs preference/a_is_ai + the filter dims.
_PREFERENCE_VOTES = """
    SELECT v.preference, v.a_is_ai, v.session_id AS translator_id, v.letter_id,
           ai.alert_category, ai.prompt_version
    FROM votes v JOIN ai_responses ai ON ai.id = v.ai_response_id
"""

# alert_evaluations ⨝ votes ⨝ ai_responses — grouped by the AI-emitted category.
_ALERT_EVALS = """
    SELECT ae.verdict, ai.alert_category, v.session_id AS translator_id,
           v.letter_id, ai.prompt_version
    FROM alert_evaluations ae
    JOIN votes v ON v.id = ae.vote_id
    JOIN ai_responses ai ON ai.id = ae.ai_response_id
"""

# missed_issues ⨝ votes ⨝ ai_responses — grouped by the missed category, while
# alert_category (AI-emitted) is only a filter dimension.
_MISSED = """
    SELECT mi.missed_yes_no, mi.category, v.session_id AS translator_id,
           v.letter_id, ai.alert_category, ai.prompt_version
    FROM missed_issues mi
    JOIN votes v ON v.id = mi.vote_id
    JOIN ai_responses ai ON ai.id = v.ai_response_id
"""

# votes ⨝ ai_responses — participation needs voted_at + the filter dims.
_PARTICIPATION_VOTES = """
    SELECT v.session_id AS translator_id, v.letter_id, v.voted_at, ai.prompt_version
    FROM votes v JOIN ai_responses ai ON ai.id = v.ai_response_id
"""


def build_metrics(conn, filters):
    """Run all five aggregations over the current ``filters`` and return the
    reports keyed for the template."""
    ai_rows = conn.execute("SELECT * FROM ai_responses").fetchall()
    letters = conn.execute("SELECT id, ground_truth_category FROM letters").fetchall()
    sessions = conn.execute(
        "SELECT id, first_name, last_name, source_langs_csv, target_langs_csv FROM sessions"
    ).fetchall()
    return {
        "preference": aggregate_preference(conn.execute(_PREFERENCE_VOTES).fetchall(), filters),
        "alert_verdicts": aggregate_alert_verdicts(conn.execute(_ALERT_EVALS).fetchall(), filters),
        "missed": aggregate_missed_issues(conn.execute(_MISSED).fetchall(), filters),
        "cost": aggregate_cost(ai_rows, filters=filters),
        "ground_truth": score_ground_truth(letters, ai_rows, filters),
        "participation": aggregate_participation(
            sessions, conn.execute(_PARTICIPATION_VOTES).fetchall(), filters
        ),
    }


def _full_name(row):
    parts = [row["first_name"], row["last_name"]]
    return " ".join(p for p in parts if p) or "(unnamed)"


def dropdown_options(conn, active_version):
    """Option lists for the settings + filter dropdowns. Translators/letters are
    limited to those that have votes; versions carry a (covered/total) coverage
    count for the settings badge."""
    translators = [
        {"id": r["id"], "name": _full_name(r)}
        for r in conn.execute(
            "SELECT DISTINCT s.id, s.first_name, s.last_name FROM sessions s"
            " JOIN votes v ON v.session_id = s.id"
            " ORDER BY s.first_name, s.last_name, s.id"
        )
    ]
    letters = [
        {"id": r["id"], "label": r["display_ref"] or f"letter {r['id']}"}
        for r in conn.execute(
            "SELECT DISTINCT l.id, l.display_ref FROM letters l"
            " JOIN votes v ON v.letter_id = l.id ORDER BY l.id"
        )
    ]
    cats = [
        {"id": r["alert_category"], "label": categories.label_for(r["alert_category"])}
        for r in conn.execute(
            "SELECT DISTINCT alert_category FROM ai_responses"
            " WHERE alert_category IS NOT NULL ORDER BY alert_category"
        )
    ]
    total_letters = conn.execute("SELECT COUNT(*) AS n FROM letters").fetchone()["n"]
    versions = []
    for r in conn.execute(
        "SELECT DISTINCT prompt_version FROM ai_responses ORDER BY prompt_version"
    ):
        version = r["prompt_version"]
        covered = conn.execute(
            "SELECT COUNT(DISTINCT letter_id) AS n FROM ai_responses WHERE prompt_version = ?",
            (version,),
        ).fetchone()["n"]
        versions.append({"version": version, "covered": covered, "total": total_letters})
    return {
        "translators": translators,
        "letters": letters,
        "categories": cats,
        "versions": versions,
        "active_version": active_version,
    }


def _maybe_int(value):
    return int(value) if value.isdigit() else value


def parse_filters(params, active_version):
    """Map the dashboard query params to the analysis filter dict. Empty/absent
    values mean "no constraint" on that dimension; ``translator``/``letter`` are
    coerced to int to match the integer ids in the DB. The version filter defaults
    to the active version, and "All versions" arrives as the ``"__all__"`` sentinel
    the aggregations already understand."""
    filters = {}
    translator = params.get("translator")
    if translator:
        filters["translator_id"] = _maybe_int(translator)
    letter = params.get("letter")
    if letter:
        filters["letter_id"] = _maybe_int(letter)
    category = params.get("category")
    if category:
        filters["alert_category"] = category
    version = params.get("version")
    if version:
        filters["prompt_version"] = version  # may be the "__all__" sentinel
    elif active_version is not None:
        filters["prompt_version"] = active_version  # default to the active version
    return filters
