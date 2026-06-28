"""Translation-strategy benchmark runner (research driver over the shared core).

Runs each pilot letter through strategies A/D/F on one or more Gemini models, with the
locked response schema, and records the translation, alert, token usage, and USD cost
per call. It decides nothing — it produces the data for the human quality/cost call.

Shares the Gemini access (Vertex/ZDR auth, inline PDF, the call), pricing/cost, and the
prompt assembler with the production runner via `pre_processing.gemini` / `cost` /
`assemble`. The ZERO-DATA-RETENTION posture lives in `pre_processing.gemini`.

Modes (run from the repo root):
  python -m benchmark.run --dry-run     # build prompts + load PDFs + rough estimate; NO network, NO key
  python -m benchmark.run --estimate    # exact INPUT tokens via count_tokens; needs auth, NO charge
  python -m benchmark.run               # full run; writes results + telemetry (spends budget)

Useful flags: --models a,b,c  --strategies A,D,F  --letters R-003,...  --budget  --out DIR
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from data.corpus import LetterMetadata, load_corpus
from pre_processing import gemini
from pre_processing.assemble import build_prompt
from pre_processing.cost import compute_cost

_ANNUAL_LETTERS = 77_382  # production volume, for the cost extrapolation

DEFAULT_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.1-pro-preview"]
DEFAULT_STRATEGIES = ["A", "D", "F"]
DEFAULT_LETTERS = ["R-003", "R-002", "R-010", "R-006"]


def _pages(letter: LetterMetadata) -> int:
    if not letter.paragraphs:
        return 1
    return max(p.page_index for p in letter.paragraphs) + 1


def _annual(cost_per_letter: float) -> float:
    return cost_per_letter * _ANNUAL_LETTERS


# --------------------------------------------------------------------------- modes

def dry_run(letters, strategies, budget):
    """No network, no key: validate the pipeline + a ROUGH cost estimate."""
    print("DRY RUN — no API call, no key. Rough estimate only (text chars/4 + ~600 tok/page);")
    print("use --estimate for exact input tokens.\n")
    print(f"{'letter':7} {'strat':5} {'prompt_ch':9} {'pdf_KB':7} {'pages':5} {'~tok_in':8}")
    for letter in letters:
        pdf = gemini.pdf_bytes(letter)
        pages = _pages(letter)
        for strat in strategies:
            prompt = build_prompt(letter, strat, budget=budget)
            tok_in = len(prompt) // 4 + pages * 600
            print(f"{letter.id:7} {strat:5} {len(prompt):9} {len(pdf)//1024:7} {pages:5} {tok_in:8}")
    print("\nPipeline OK: prompts build and PDFs load for every (letter, strategy).")


def estimate(letters, models, strategies, budget):
    """Exact INPUT token counts via count_tokens — needs auth, costs nothing."""
    client = gemini.client()
    print("ESTIMATE — count_tokens only (no generation, no charge).\n")
    print(f"{'model':24} {'letter':7} {'strat':5} {'tok_in':7} {'~in_cost$':10}")
    grand = 0.0
    for model in models:
        for letter in letters:
            pdf = gemini.pdf_bytes(letter)
            for strat in strategies:
                tok_in = gemini.count_tokens(client, build_prompt(letter, strat, budget=budget), pdf, model)
                c = compute_cost(model, tok_in, 0)  # input only; output unknown pre-call
                grand += c
                print(f"{model:24} {letter.id:7} {strat:5} {tok_in:7} {c:10.5f}")
    print(f"\nInput-only projected cost across all calls: ${grand:.4f} (output not included; real run captures it).")


def run(letters, models, strategies, budget, out: Path, temperature: float = 0.0):
    """Full run: generate_content, write results + telemetry. Spends budget."""
    client = gemini.client()
    rollup: dict[tuple[str, str], dict] = {}
    failures = []
    for model in models:
        for letter in letters:
            pdf = gemini.pdf_bytes(letter)
            for strat in strategies:
                try:
                    resp = gemini.call(client, build_prompt(letter, strat, budget=budget), pdf,
                                       model, temperature=temperature)
                    if not resp.text:
                        raise ValueError("empty response text (possible safety block / no candidate)")
                    response_json = json.loads(resp.text)
                    um = resp.usage_metadata
                    tin = getattr(um, "prompt_token_count", 0) or 0
                    tout = getattr(um, "candidates_token_count", 0) or 0
                    tthought = getattr(um, "thoughts_token_count", 0) or 0
                    ttotal = getattr(um, "total_token_count", 0) or 0
                    c = compute_cost(model, tin, tout + tthought)  # thinking tokens bill as output
                    record = {
                        "letter_id": letter.id, "strategy": strat, "model": model,
                        "budget_hints": budget,
                        "response": response_json,
                        "telemetry": {
                            "tokens_in": tin, "tokens_out": tout, "tokens_thought": tthought,
                            "total_tokens": ttotal, "cost_usd": round(c, 6),
                            "processed_at": datetime.now(timezone.utc).isoformat(),
                        },
                    }
                    dest = out / model / strat
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / f"{letter.id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
                    agg = rollup.setdefault((model, strat), {"cost": 0.0, "tin": 0, "tout": 0, "n": 0})
                    agg["cost"] += c; agg["tin"] += tin; agg["tout"] += tout + tthought; agg["n"] += 1
                    print(f"ok  {model:24} {letter.id:7} {strat}  in={tin:6} out={tout + tthought:5} ${c:.5f}")
                except Exception as exc:  # noqa: BLE001 — record and continue per the contract
                    failures.append({"model": model, "letter_id": letter.id, "strategy": strat, "error": repr(exc)})
                    print(f"FAIL {model:24} {letter.id:7} {strat}  {exc!r}")

    if failures:
        out.mkdir(parents=True, exist_ok=True)
        (out / "_failures.jsonl").write_text("\n".join(json.dumps(f) for f in failures) + "\n", encoding="utf-8")

    print(f"\n{'model':24} {'strat':5} {'n':3} {'tok_in':8} {'tok_out':8} {'cost$':9} {'~$/yr@77382':12}")
    for (model, strat), a in sorted(rollup.items()):
        per_letter = a["cost"] / a["n"] if a["n"] else 0.0
        print(f"{model:24} {strat:5} {a['n']:3} {a['tin']:8} {a['tout']:8} {a['cost']:9.5f} {_annual(per_letter):12.0f}")
    print(f"\nResults in {out}/<model>/<strategy>/<letter>.json"
          + (f"  ({len(failures)} failures in _failures.jsonl)" if failures else ""))
    print("Annual figure = avg cost/letter for that (model,strategy) x 77,382 letters/yr.")


def main():
    ap = argparse.ArgumentParser(description="Translation-strategy benchmark runner")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--strategies", default=",".join(DEFAULT_STRATEGIES))
    ap.add_argument("--letters", default=",".join(DEFAULT_LETTERS))
    ap.add_argument("--budget", action="store_true", help="add per-paragraph length hints (strategy F)")
    ap.add_argument("--dry-run", action="store_true", help="no network, no key; validate + rough estimate")
    ap.add_argument("--estimate", action="store_true", help="exact input tokens via count_tokens; no charge")
    ap.add_argument("--out", default=str(Path("benchmark/results")))
    ap.add_argument("--corpus", default="letters/corpus.json",
                    help="corpus JSON ({version, letters:[...]}); e.g. the synthetic set for screening")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="sampling temperature; 0 (default) is most deterministic")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    corpus = load_corpus(args.corpus)
    by = {l.id: l for l in corpus}
    if args.letters.strip().lower() == "all":
        letters = corpus
    else:
        wanted = [x.strip() for x in args.letters.split(",") if x.strip()]
        missing = [x for x in wanted if x not in by]
        if missing:
            raise SystemExit(f"unknown letter ids: {missing}")
        letters = [by[x] for x in wanted]

    if args.dry_run:
        dry_run(letters, strategies, args.budget)
    elif args.estimate:
        estimate(letters, models, strategies, args.budget)
    else:
        run(letters, models, strategies, args.budget, Path(args.out), temperature=args.temperature)


if __name__ == "__main__":
    main()
