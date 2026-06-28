"""Screening scorecard for the offline benchmark.

Compares each result's alert.category to the corpus ground-truth
expected_category, for the letters that carry one. No network, no key — it only
reads the corpus JSON and the result files written by `benchmark.run`.

The headline metric is binary detection (was an alert raised when one was due),
because for child-protection / content screening a MISS (false negative) is the
costly error; exact-category accuracy is reported alongside it.

Run from the repo root, after a real run that produced result files:
  python -m benchmark.score_screening \\
    --corpus <synthetic_entries.json> --results-dir benchmark/results/screening \\
    --models gemini-3.5-flash,gemini-3.1-pro-preview --strategy F
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from data.corpus import load_corpus


def _is_alert(category) -> bool:
    return bool(category) and category != "no_alert"


def tally(rows):
    """Score (letter_id, gold_category, pred_category|None) triples.

    Only rows with a gold category are scored (other corpus letters have no
    ground truth). A `pred` of None means no result file / no category, and is
    treated as "no alert raised". Returns a metrics dict.
    """
    scored = [(i, g, p) for (i, g, p) in rows if g]
    tp = fn = fp = tn = exact = 0
    false_negatives, false_positives, category_mismatches = [], [], []
    per_category: dict[str, dict] = {}
    for i, g, p in scored:
        if p == g:
            exact += 1
        gold_alert, pred_alert = _is_alert(g), _is_alert(p)
        if gold_alert and pred_alert:
            tp += 1
            if g != p:
                category_mismatches.append((i, g, p))
        elif gold_alert and not pred_alert:
            fn += 1
            false_negatives.append((i, g, p))
        elif pred_alert:  # gold is no_alert
            fp += 1
            false_positives.append((i, p))
        else:
            tn += 1
        d = per_category.setdefault(g, {"n": 0, "caught": 0, "exact": 0})
        d["n"] += 1
        d["caught"] += int(pred_alert)
        d["exact"] += int(p == g)

    n = len(scored)

    def rate(num, den):
        return (num / den) if den else None

    return {
        "n": n,
        "exact_accuracy": rate(exact, n),
        "detection": {
            "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "recall": rate(tp, tp + fn),
            "precision": rate(tp, tp + fp),
            "specificity": rate(tn, tn + fp),
        },
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "category_mismatches": category_mismatches,
        "per_category": per_category,
    }


def _predictions(results_dir, model, strategy, ids):
    """Read each letter's predicted alert.category from its result file (or None)."""
    preds = {}
    for i in ids:
        f = Path(results_dir) / model / strategy / f"{i}.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            preds[i] = (r.get("response") or {}).get("alert", {}).get("category")
        else:
            preds[i] = None
    return preds


def _pct(x):
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def _print_card(model, m):
    d = m["detection"]
    print(f"\n=== {model} ===")
    print(f"letters scored (with ground truth): {m['n']}")
    print(f"exact-category accuracy           : {_pct(m['exact_accuracy'])}")
    print(f"alert detection  recall={_pct(d['recall'])}  precision={_pct(d['precision'])}  specificity={_pct(d['specificity'])}")
    print(f"  TP={d['tp']}  FN={d['fn']} (missed alerts)  FP={d['fp']} (false alarms)  TN={d['tn']}")
    if m["false_negatives"]:
        print("  MISSED ALERTS (gold -> said no_alert) — the costly errors:")
        for i, g, p in m["false_negatives"]:
            print(f"    {i}: expected {g}, got {p or 'no result'}")
    if m["false_positives"]:
        print("  FALSE ALARMS (benign -> flagged):")
        for i, p in m["false_positives"]:
            print(f"    {i}: got {p}")
    if m["category_mismatches"]:
        print("  CAUGHT BUT WRONG CATEGORY:")
        for i, g, p in m["category_mismatches"]:
            print(f"    {i}: expected {g}, got {p}")
    print("  per expected category:   category                     n  caught  exact")
    for cat, c in sorted(m["per_category"].items()):
        print(f"    {cat:28} {c['n']:3} {c['caught']:7} {c['exact']:6}")


def score(corpus_path, results_dir, models, strategy="F"):
    """Load gold categories + predictions and print a scorecard per model."""
    corpus = load_corpus(corpus_path)
    gold = {l.id: getattr(getattr(l, "ground_truth", None), "expected_category", None) for l in corpus}
    ids = [i for i, g in gold.items() if g]
    if not ids:
        raise SystemExit(f"no letters with ground_truth.expected_category in {corpus_path}")
    report = {}
    for model in models:
        preds = _predictions(results_dir, model, strategy, ids)
        report[model] = tally([(i, gold[i], preds.get(i)) for i in ids])
        _print_card(model, report[model])
    return report


def main():
    ap = argparse.ArgumentParser(description="Screening scorecard: alert.category vs ground truth")
    ap.add_argument("--corpus", required=True, help="corpus JSON carrying ground_truth.expected_category")
    ap.add_argument("--results-dir", default="benchmark/results")
    ap.add_argument("--models", default="gemini-3.5-flash,gemini-3.1-pro-preview")
    ap.add_argument("--strategy", default="F")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    score(args.corpus, args.results_dir, models, args.strategy)


if __name__ == "__main__":
    main()
