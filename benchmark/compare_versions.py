"""Compare prompt-version production runs into one progression report.

Scans the per-version result dirs (by default both ``pre_processing/results`` and
``pre_processing/results_archive``) plus the corpus, and prints, as Markdown:

  1. a version-progression scorecard (coverage, recall / precision / exact, TP/FN/FP/TN, cost), and
  2. the per-letter prediction changes between consecutive versions.

Each version's scorecard is computed over the letters that version actually processed
(honest coverage for partial runs), reusing the scoring in ``benchmark.report``
(``build_report`` -> ``summary``, via ``benchmark.score_screening.tally``), so the numbers
match the per-run reviews. Output is Markdown so it can be pasted straight into a write-up.
It contains only letter ids, gold labels, and alert categories — never translations.

  PYTHONPATH=. python -m benchmark.compare_versions
  PYTHONPATH=. python -m benchmark.compare_versions --versions v2,v3,v4
  PYTHONPATH=. python -m benchmark.compare_versions --roots pre_processing/results_archive,pre_processing/results
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data.corpus import load_corpus
from benchmark.report import build_report, _discover_production_columns, _normalize_envelope

_DEFAULT_ROOTS = ("pre_processing/results", "pre_processing/results_archive")


# --------------------------------------------------------------------------- discovery + reads

def discover_versions(roots) -> dict:
    """Map ``version name -> results dir`` by scanning each root's immediate subdirs
    that hold at least one result JSON. First root wins on a name collision. Returns
    the mapping sorted by version name."""
    found: dict = {}
    for root in roots:
        rp = Path(root)
        if not rp.is_dir():
            continue
        for d in sorted(p for p in rp.glob("*") if p.is_dir()):
            if d.name in found:
                continue
            if any(f.name != "_failures.jsonl" for f in d.glob("*.json")):
                found[d.name] = d
    return dict(sorted(found.items()))


def version_preds(results_dir) -> dict:
    """``letter_id -> alert category`` for one version dir (envelope-agnostic)."""
    out = {}
    for f in sorted(Path(results_dir).glob("*.json")):
        if f.name.startswith("_"):
            continue
        raw = json.loads(f.read_text(encoding="utf-8"))
        out[raw["letter_id"]] = (_normalize_envelope(raw).get("alert") or {}).get("category")
    return out


def version_cost(results_dir) -> float:
    """Sum of ``cost_usd`` across a version's result files."""
    total = 0.0
    for f in sorted(Path(results_dir).glob("*.json")):
        if f.name.startswith("_"):
            continue
        raw = json.loads(f.read_text(encoding="utf-8"))
        total += (_normalize_envelope(raw).get("telemetry") or {}).get("cost_usd") or 0.0
    return total


def changes_between(old_preds, new_preds) -> list:
    """Letters present in **both** versions whose predicted category differs. Returns a
    sorted list of ``(letter_id, old_category, new_category)`` — genuine prediction flips,
    not coverage differences."""
    both = sorted(set(old_preds) & set(new_preds))
    return [(i, old_preds[i], new_preds[i]) for i in both if old_preds[i] != new_preds[i]]


# --------------------------------------------------------------------------- scorecard (reuses tested build_report)

def version_scorecard(corpus, results_dir) -> dict:
    """Ground-truth scorecard for one version, computed only over the letters that
    version processed (so a partial run isn't unfairly penalised for uncovered letters)."""
    covered_ids = set(version_preds(results_dir))
    covered = [l for l in corpus if l.id in covered_ids]
    models, strategies = _discover_production_columns(Path(results_dir))
    report = build_report(covered, Path(results_dir), models, strategies)
    key = f"{models[0]}/{strategies[0]}" if models and strategies else None
    m = report.summary.get(key) if key else None
    base = {"coverage": len(covered), "cost": version_cost(results_dir)}
    if not m:
        return {**base, "n": 0, "recall": None, "precision": None, "exact": None,
                "tp": None, "fn": None, "fp": None, "tn": None}
    d = m["detection"]
    return {**base, "n": m["n"], "recall": d["recall"], "precision": d["precision"],
            "exact": m["exact_accuracy"], "tp": d["tp"], "fn": d["fn"], "fp": d["fp"], "tn": d["tn"]}


# --------------------------------------------------------------------------- Markdown render

def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_markdown(corpus, versions) -> str:
    total = len(corpus)
    gold = {l.id: getattr(l.ground_truth, "expected_category", None) for l in corpus}
    lines = ["## Prompt-version comparison", ""]
    lines.append("| version | coverage | GT n | recall | precision | exact | TP/FN/FP/TN | cost (USD) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, d in versions.items():
        s = version_scorecard(corpus, d)
        tffn = "—" if s["tp"] is None else f"{s['tp']}/{s['fn']}/{s['fp']}/{s['tn']}"
        lines.append(
            f"| {name} | {s['coverage']}/{total} | {s['n']} | {_pct(s['recall'])} | "
            f"{_pct(s['precision'])} | {_pct(s['exact'])} | {tffn} | ${s['cost']:.4f} |"
        )
    names = list(versions)
    for a, b in zip(names, names[1:]):
        ch = changes_between(version_preds(versions[a]), version_preds(versions[b]))
        lines += ["", f"### Changes {a} → {b} ({len(ch)})", ""]
        if not ch:
            lines.append("_No prediction changed._")
            continue
        lines.append(f"| letter | gold | {a} | {b} |")
        lines.append("|---|---|---|---|")
        for lid, old, new in ch:
            lines.append(f"| {lid} | {gold.get(lid) or '—'} | {old or '—'} | {new or '—'} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Compare prompt-version production runs (Markdown out)")
    ap.add_argument("--corpus", default="letters/corpus.json", help="corpus JSON (letters source)")
    ap.add_argument("--roots", default=",".join(_DEFAULT_ROOTS),
                    help="comma-separated result roots to scan for <version>/ dirs")
    ap.add_argument("--versions", default=None,
                    help="comma-separated subset of versions to include (default: all found)")
    args = ap.parse_args()

    roots = [r.strip() for r in args.roots.split(",") if r.strip()]
    versions = discover_versions(roots)
    if args.versions:
        want = [v.strip() for v in args.versions.split(",") if v.strip()]
        missing = [v for v in want if v not in versions]
        if missing:
            raise SystemExit(f"versions not found under {roots}: {missing} (found: {list(versions)})")
        versions = {k: versions[k] for k in want}
    if not versions:
        raise SystemExit(f"no version dirs with results found under {roots}")

    print(render_markdown(load_corpus(args.corpus), versions))


if __name__ == "__main__":
    main()
