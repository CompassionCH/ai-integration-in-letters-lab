"""Production pre-compute runner: the locked prompt over the frozen corpus.

Runs strategy F on ONE chosen model for every letter in the corpus and writes one
canonical result record per letter (translation + alert + prompt_version + USD
telemetry) to `pre_processing/results/<prompt_version>/<id>.json`. load_results loads
those into SQLite; the JSON files stay the archival source.

Thin production driver over the shared core (`pre_processing.gemini` / `cost` /
`assemble`); the benchmark (`benchmark.run`) is the research sibling over the same
core. ZERO DATA RETENTION posture + Vertex/`.env` auth all live in `pre_processing.gemini`.

  python -m pre_processing.run_gemini --prompt-version v1 --model gemini-3.5-flash --temperature 0.3
  python -m pre_processing.run_gemini --prompt-version v1 --dry-run     # no network, no key
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from data.corpus import load_corpus
from pre_processing import gemini
from pre_processing.assemble import build_prompt
from pre_processing.cost import compute_cost          # re-exported for callers/tests
from pre_processing.gemini import parse_response       # re-exported for callers/tests

_STRATEGY = "F"  # the locked translation strategy (chosen by the benchmark)


# --------------------------------------------------------------------------- record builders (TDD)

def build_record(letter_id, prompt_version, model, response, tokens_in, tokens_out, processed_at) -> dict:
    """A successful result record (the canonical on-disk contract load_results loads)."""
    return {
        "letter_id": letter_id,
        "prompt_version": prompt_version,
        "model": model,
        "strategy": _STRATEGY,
        "translations": response["translations"],
        "alert": response["alert"],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(compute_cost(model, tokens_in, tokens_out), 6),
        "safety_filter_status": "ok",
        "processed_at": processed_at,
    }


def safety_record(letter_id, prompt_version, model, processed_at) -> dict:
    """Synthesized record for a safety refusal / empty candidate (recorded, not dropped)."""
    return {
        "letter_id": letter_id,
        "prompt_version": prompt_version,
        "model": model,
        "strategy": _STRATEGY,
        "translations": [],
        "alert": {"category": "safety_filter_triggered",
                  "reason": "Model returned no candidate (safety block or empty response)."},
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "safety_filter_status": "blocked",
        "processed_at": processed_at,
    }


# --------------------------------------------------------------------------- per-letter call

def _call(client, letter, model, temperature):
    """Thin wrapper: assemble the prompt + PDF for one letter and call the core."""
    return gemini.call(client, build_prompt(letter, _STRATEGY), gemini.pdf_bytes(letter),
                       model, temperature=temperature)


def process_letter(client, letter, model, prompt_version, temperature, processed_at) -> dict:
    """Call Gemini for one letter and return its result record. Raises on API/parse error."""
    resp = _call(client, letter, model, temperature)
    if not getattr(resp, "text", None):
        return safety_record(letter.id, prompt_version, model, processed_at)
    response = parse_response(resp.text)
    um = resp.usage_metadata
    tin = getattr(um, "prompt_token_count", 0) or 0
    tout = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
    return build_record(letter.id, prompt_version, model, response, tin, tout, processed_at)


# --------------------------------------------------------------------------- CLI

def _select(corpus, letters_arg):
    if letters_arg.strip().lower() == "all":
        return corpus
    by = {l.id: l for l in corpus}
    wanted = [x.strip() for x in letters_arg.split(",") if x.strip()]
    missing = [x for x in wanted if x not in by]
    if missing:
        raise SystemExit(f"unknown letter ids: {missing}")
    return [by[x] for x in wanted]


def _now():
    return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Production pre-compute runner (one model, strategy F)")
    ap.add_argument("--prompt-version", required=True, help="stamped on every result (e.g. v1)")
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--corpus", default="letters/corpus.json")
    ap.add_argument("--letters", default="all")
    ap.add_argument("--out", default="pre_processing/results", help="results root; a per-version dir is created under it")
    ap.add_argument("--dry-run", action="store_true", help="build prompts + load PDFs; no network, no key")
    ap.add_argument("--force", action="store_true", help="re-process letters whose result already exists")
    args = ap.parse_args()

    letters = _select(load_corpus(args.corpus), args.letters)
    out_dir = Path(args.out) / args.prompt_version

    if args.dry_run:
        for letter in letters:
            build_prompt(letter, _STRATEGY)
            gemini.pdf_bytes(letter)
        print(f"DRY RUN ok: prompts build + PDFs load for {len(letters)} letters "
              f"(model={args.model}, prompt_version={args.prompt_version}, strategy={_STRATEGY}). No call made.")
        return

    client = gemini.client()
    out_dir.mkdir(parents=True, exist_ok=True)
    failures, total_cost, n = [], 0.0, 0
    for letter in letters:
        dest = out_dir / f"{letter.id}.json"
        if dest.exists() and not args.force:
            print(f"skip {letter.id} (exists)")
            continue
        try:
            record = process_letter(client, letter, args.model, args.prompt_version, args.temperature, _now())
            dest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            total_cost += record["cost_usd"]
            n += 1
            print(f"ok  {letter.id:8} {record['safety_filter_status']:7} ${record['cost_usd']:.5f}")
        except Exception as exc:  # noqa: BLE001 — record and continue per the contract
            failures.append({"letter_id": letter.id, "error": repr(exc)})
            print(f"FAIL {letter.id:8} {exc!r}")

    if failures:
        (out_dir / "_failures.jsonl").write_text("\n".join(json.dumps(f) for f in failures) + "\n", encoding="utf-8")
    print(f"\n{n} letters processed (model={args.model}, prompt_version={args.prompt_version}), total ${total_cost:.4f}"
          + (f", {len(failures)} failures (_failures.jsonl)" if failures else "")
          + f"\nResults in {out_dir}/<letter>.json  — load into SQLite with load_results. "
          "Record the total in pre_processing/prompts/CHANGELOG.md.")


if __name__ == "__main__":
    main()
