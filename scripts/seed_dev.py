"""Reset the local database to a small, fictional sample so the app can be tried
end to end without the (separate, not-yet-wired) Gemini pre-processing pipeline.

This is a LOCAL DEV CONVENIENCE, not a data loader: every name, letter and AI
response below is invented. It is re-runnable — each run clears the data tables
and re-inserts the sample, plus writes gitignored placeholder PDFs under
``letters/dev/`` so the evaluation page's PDF pane shows something.

    python -m scripts.seed_dev

Uses the same database as the app (``DB_PATH`` from ``.env``, else ``poc.db``).
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # so DB_PATH / LETTERS_DIR match the running app

import config  # noqa: E402
from db import connect  # noqa: E402
from db.init import init_db  # noqa: E402

MODEL = "gemini-2.5-pro"

# Child→parent order so the per-connection foreign keys stay satisfied on reset.
_DATA_TABLES = (
    "alert_evaluations", "missed_issues", "votes",
    "ai_response_paragraphs", "ai_responses",
    "letter_paragraphs", "letters", "sessions", "app_settings",
)


def _placeholder_pdf(title: str) -> bytes:
    """A minimal but valid single-page PDF showing ``title`` (parens-free)."""
    text = f"BT /F1 16 Tf 72 720 Td ({title}) Tj ET".encode()
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1, xref,
    )
    return bytes(out)


def _letter(conn, display_ref, *, ltype, human, ground_truth, pdf_title):
    pdf_path = f"dev/{display_ref}.pdf"
    cur = conn.execute(
        "INSERT INTO letters (display_ref, type, pdf_path, direction, source_lang,"
        " target_lang, country, child_official, child_preferred, child_sex, child_age,"
        " sponsor_first, sponsor_sex, sponsor_age, human_translation_text,"
        " ground_truth_category) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (display_ref, ltype, pdf_path, "child_to_sponsor", "en", "fr", "Kenya",
         "Amara", "Amara", "F", 10, "Robin", "F", 41, human, ground_truth),
    )
    pdf_file = Path(config.letters_dir()) / pdf_path
    pdf_file.parent.mkdir(parents=True, exist_ok=True)
    pdf_file.write_bytes(_placeholder_pdf(pdf_title))
    return cur.lastrowid


def _response(conn, letter_id, version, *, alert):
    cur = conn.execute(
        "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text,"
        " alert_category, alert_reason, tokens_in, tokens_out, cost_usd, safety_filter_status)"
        " VALUES (?,?,?,?,?,?,?,?,?,'ok')",
        (letter_id, version, MODEL, "Chere famille, merci pour votre lettre... (IA)",
         alert, ("Sample alert reason." if alert else None), 1500, 300, 0.05),
    )
    return cur.lastrowid


def _session(conn, token, first, last, source, target):
    cur = conn.execute(
        "INSERT INTO sessions (session_token, first_name, last_name, source_langs_csv,"
        " target_langs_csv) VALUES (?,?,?,?,?)",
        (token, first, last, source, target),
    )
    return cur.lastrowid


def _vote(conn, sid, lid, aid, *, preference, a_is_ai, verdict=None, missed=None):
    cur = conn.execute(
        "INSERT INTO votes (session_id, letter_id, ai_response_id, preference, a_is_ai,"
        " preference_comment) VALUES (?,?,?,?,?,?)",
        (sid, lid, aid, preference, a_is_ai, "Reads naturally." if preference else None),
    )
    vid = cur.lastrowid
    if verdict:
        conn.execute(
            "INSERT INTO alert_evaluations (vote_id, ai_response_id, verdict, comment)"
            " VALUES (?,?,?,?)",
            (vid, aid, verdict, "Matches the letter."),
        )
    conn.execute(
        "INSERT INTO missed_issues (vote_id, missed_yes_no, category, reason)"
        " VALUES (?,?,?,?)",
        (vid, 1 if missed else 0, missed, "An issue the AI did not flag." if missed else None),
    )


def seed():
    init_db(config.db_path())
    conn = connect()
    try:
        for table in _DATA_TABLES:
            conn.execute(f"DELETE FROM {table}")

        # Two real letters (A/B card), one issue letter, one false-positive trap.
        l1 = _letter(conn, "rea0a001", ltype="real",
                     human="Dear sponsor, thank you for your kind letter...",
                     ground_truth=None, pdf_title="Sample real letter 1 - local dev")
        l2 = _letter(conn, "rea0b002", ltype="real",
                     human="Hello, I am doing well at school this term...",
                     ground_truth=None, pdf_title="Sample real letter 2 - local dev")
        l3 = _letter(conn, "syn0c003", ltype="synthetic", human=None,
                     ground_truth="child_protection",
                     pdf_title="Sample issue letter - local dev")
        l4 = _letter(conn, "trp0d004", ltype="synthetic", human=None,
                     ground_truth="no_alert", pdf_title="Sample trap letter - local dev")

        # v1 covers all four; v2 only the real pair -> a partial-coverage badge.
        r1 = _response(conn, l1, "v1", alert=None)
        _response(conn, l1, "v2", alert=None)
        r2 = _response(conn, l2, "v1", alert="wrong_child_name")
        _response(conn, l2, "v2", alert="wrong_child_name")
        r3 = _response(conn, l3, "v1", alert="child_protection")  # ground truth -> TP
        _response(conn, l4, "v1", alert=None)                     # FP-trap -> trap passed
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('active_prompt_version', 'v1')")

        # A couple of sample votes so the dashboard isn't empty; your own session
        # (created via /start) is separate, so all four letters stay unvoted for you.
        # Placeholder surnames — all sample data here is fictional.
        s1 = _session(conn, "dev-mara", "Mara", "Example", "en", "fr")
        s2 = _session(conn, "dev-luc", "Luc", "Sample", "en", "fr,de")
        _vote(conn, s1, l1, r1, preference="A", a_is_ai=1)
        _vote(conn, s1, l2, r2, preference="B", a_is_ai=0, verdict="Correct")
        _vote(conn, s2, l3, r3, preference=None, a_is_ai=None, verdict="Mixed",
              missed="wrong_sponsor_name")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
    print(
        "Seeded the local database with fictional sample data "
        f"(DB={config.db_path()}, letters under {config.letters_dir()}/dev/).\n"
        "Start the server, then open  /?invite=<ACCESS_TOKEN>  to evaluate, "
        "or  /admin?token=<ADMIN_TOKEN>  for the dashboard."
    )
