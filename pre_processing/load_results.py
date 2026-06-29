"""Load pre-computed Gemini results into the webapp's SQLite DB.

Reads the corpus (letters + their human reference + source paragraphs) and the result
JSONs produced by `pre_processing.run_gemini`, and upserts them into `letters`,
`letter_paragraphs`, `ai_responses`, and `ai_response_paragraphs`. The JSON files stay
the archival source; the DB is the runtime view the evaluation endpoints serve.

Idempotent: re-running upserts (no duplicate rows). Scans **every** prompt-version dir
under the results root (so multiple versions coexist in `ai_responses`; the active one is
selected at serve time). Always safe to run at startup.

  python -m pre_processing.load_results                      # corpus.json + pre_processing/results
  python -m pre_processing.load_results --corpus a.json,b.json --results-root pre_processing/results

The app reads the joined `translation_text` (AI) vs `human_translation_text` (human) in the
A/B card as `whitespace-pre-wrap` blocks, so both are normalized to the same separator
(blank line) — `#PAGE#` markers are turned into blank lines — to keep the two boxes
visually identical (parity: the volunteer must not spot the AI by formatting).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import config
from db import connect
from db.init import init_db
from data.corpus import load_corpus

_RESULTS_ROOT = "pre_processing/results"


# --------------------------------------------------------------------------- pure transforms (TDD)

def display_ref(letter_id: str) -> str:
    """Opaque client-facing ref: sha1('ref:<id>')[:8] (matches the webapp's letter ref)."""
    return hashlib.sha1(f"ref:{letter_id}".encode()).hexdigest()[:8]


def clean_block(text) -> str | None:
    """Normalize a human reference block for the A/B card: `#PAGE#` -> blank line, trim.
    Returns None for absent/empty text (None drives the 'no A/B card' rule for synthetics)."""
    if not text:
        return None
    out = text.replace("#PAGE#", "\n\n").strip()
    return out or None


def join_translations(translations) -> str:
    """Join the AI's per-paragraph texts (ordered by sequence) into one block, same
    blank-line separator as the human text for A/B parity."""
    ordered = sorted(translations, key=lambda t: t.get("sequence", 0))
    return "\n\n".join((t.get("text") or "").strip() for t in ordered).strip()


# --------------------------------------------------------------------------- DB upserts

_LETTER_COLS = [
    "display_ref", "corpus_id", "type", "pdf_path", "direction", "source_lang", "target_lang", "country",
    "child_official", "child_preferred", "child_sex", "child_age",
    "sponsor_first", "sponsor_other_first_names_csv", "sponsor_sex", "sponsor_age",
    "human_translation_text", "ground_truth_category", "ground_truth_rationale",
]


def _letter_row(letter) -> dict:
    gt = getattr(letter, "ground_truth", None)
    q = letter.translation_queue
    return {
        "display_ref": display_ref(letter.id),
        "corpus_id": letter.id,
        "type": letter.type,
        "pdf_path": letter.pdf_path,
        "direction": letter.direction,
        "source_lang": q.source,
        "target_lang": q.target,
        "country": letter.country,
        "child_official": letter.child.official_first_name,
        "child_preferred": letter.child.preferred_first_name,
        "child_sex": letter.child.sex,
        "child_age": letter.child.age,
        "sponsor_first": letter.sponsor.first_name,
        "sponsor_other_first_names_csv": ",".join(letter.sponsor.other_sponsored_first_names or []),
        "sponsor_sex": letter.sponsor.sex,
        "sponsor_age": letter.sponsor.age,
        "human_translation_text": clean_block(letter.human_translation),
        "ground_truth_category": getattr(gt, "expected_category", None),
        "ground_truth_rationale": getattr(gt, "rationale", None),
    }


def _upsert_letter(conn, letter) -> int:
    row = _letter_row(letter)
    cols = ", ".join(_LETTER_COLS)
    ph = ", ".join(f":{c}" for c in _LETTER_COLS)
    sets = ", ".join(f"{c}=excluded.{c}" for c in _LETTER_COLS if c != "display_ref")
    conn.execute(f"INSERT INTO letters ({cols}) VALUES ({ph}) "
                 f"ON CONFLICT(display_ref) DO UPDATE SET {sets}", row)
    letter_id = conn.execute("SELECT id FROM letters WHERE display_ref=?", (row["display_ref"],)).fetchone()[0]
    for p in (letter.paragraphs or []):
        conn.execute(
            "INSERT INTO letter_paragraphs (letter_id, page_index, sequence, source_text, human_translation) "
            "VALUES (?,?,?,?,?) ON CONFLICT(letter_id, page_index, sequence) DO UPDATE SET "
            "source_text=excluded.source_text, human_translation=excluded.human_translation",
            (letter_id, p.page_index, p.sequence, p.source_text, p.human_translation),
        )
    return letter_id


def _upsert_response(conn, letter_db_id: int, record: dict) -> int:
    alert = record.get("alert") or {}
    conn.execute(
        "INSERT INTO ai_responses (letter_id, prompt_version, model, translation_text, alert_category, "
        "alert_reason, tokens_in, tokens_out, cost_usd, safety_filter_status, processed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(letter_id, prompt_version, model) DO UPDATE SET "
        "translation_text=excluded.translation_text, alert_category=excluded.alert_category, "
        "alert_reason=excluded.alert_reason, tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out, "
        "cost_usd=excluded.cost_usd, safety_filter_status=excluded.safety_filter_status, "
        "processed_at=excluded.processed_at",
        (letter_db_id, record["prompt_version"], record["model"], join_translations(record.get("translations") or []),
         alert.get("category"), alert.get("reason"), record.get("tokens_in"), record.get("tokens_out"),
         record.get("cost_usd"), record.get("safety_filter_status"), record.get("processed_at")),
    )
    ai_id = conn.execute(
        "SELECT id FROM ai_responses WHERE letter_id=? AND prompt_version=? AND model=?",
        (letter_db_id, record["prompt_version"], record["model"]),
    ).fetchone()[0]
    # Replace the per-paragraph rows wholesale (idempotent). page_index 0: the model returns
    # only a 1-based `sequence`; the app's A/B card uses translation_text, this table is the
    # structured archival copy.
    conn.execute("DELETE FROM ai_response_paragraphs WHERE ai_response_id=?", (ai_id,))
    for t in (record.get("translations") or []):
        conn.execute(
            "INSERT INTO ai_response_paragraphs (ai_response_id, page_index, sequence, text) VALUES (?,?,?,?)",
            (ai_id, 0, t.get("sequence"), t.get("text")),
        )
    return ai_id


# --------------------------------------------------------------------------- orchestration

def load(db_path: str, corpus_paths, results_root: str = _RESULTS_ROOT) -> dict:
    """Upsert letters from the corpus file(s) + AI responses from every version dir under
    `results_root`. Returns counts. A result whose letter is not in the corpus is skipped."""
    conn = connect(db_path)
    try:
        ids = {}  # corpus letter id -> db letters.id
        for path in corpus_paths:
            for letter in load_corpus(path):
                ids[letter.id] = _upsert_letter(conn, letter)
        n_resp, skipped = 0, []
        root = Path(results_root)
        for version_dir in sorted(p for p in root.glob("*") if p.is_dir()):
            for result_file in sorted(version_dir.glob("*.json")):
                record = json.loads(result_file.read_text(encoding="utf-8"))
                lid = record.get("letter_id")
                if lid not in ids:
                    skipped.append(f"{version_dir.name}/{result_file.name}")
                    continue
                _upsert_response(conn, ids[lid], record)
                n_resp += 1
        conn.commit()
        return {"letters": len(ids), "responses": n_resp, "skipped": skipped}
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Load pre-computed Gemini results into SQLite")
    ap.add_argument("--corpus", default=str(Path(config.letters_dir()) / "corpus.json"),
                    help="comma-separated corpus JSON path(s) (letters source)")
    ap.add_argument("--results-root", default=_RESULTS_ROOT, help="root holding <prompt_version>/<letter>.json")
    ap.add_argument("--db", default=None, help="DB path (default: config.db_path())")
    args = ap.parse_args()
    db = args.db or config.db_path()
    init_db(db)
    counts = load(db, [p.strip() for p in args.corpus.split(",") if p.strip()], args.results_root)
    print(f"loaded {counts['letters']} letters, {counts['responses']} AI responses into {db}"
          + (f"; skipped {len(counts['skipped'])} result(s) with no matching letter: {counts['skipped']}"
             if counts['skipped'] else ""))


if __name__ == "__main__":
    main()
