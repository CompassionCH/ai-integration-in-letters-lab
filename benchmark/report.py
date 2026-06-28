"""Self-contained HTML review report for one offline benchmark run.

Turns a results directory (`<results-dir>/<model>/<strategy>/<letter>.json`) into a
single static `.html` page that opens via `file://` with no server and no network:
inline CSS, PDFs embedded as base64 `data:` URIs. Per letter it shows the source PDF,
the human reference translation when present, and one column per (model, strategy) with
the paragraph-aligned translations, the call's alert category + reason, and telemetry.
When the corpus carries a ground-truth `expected_category`, each prediction is shown
against the gold label with pass/fail colouring and the per-letter rationale, so the
page doubles as a label-adjudication surface.

This is local-only research tooling. The generated HTML embeds real letter content, so
it must stay under the gitignored `benchmark/results/...` path and must never be
committed, pushed, or uploaded anywhere. Only this generator is shared; each user runs
it against their own local results.

Run from the repo root, e.g.:
  PYTHONPATH=. .venv/bin/python -m benchmark.report \\
    --corpus letters/corpus.json --results-dir benchmark/results/v1c \\
    --models gemini-3.5-flash,gemini-3.1-pro-preview --strategies F \\
    --out benchmark/results/v1c/report.html
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from data.corpus import LetterMetadata, load_corpus
from benchmark.score_screening import tally  # reuse the screening scoring, do not reimplement

# Mirrors benchmark/run.py PDF resolution. Replicated (not imported) because importing
# run.py has import-time side effects (it reads the response schema + pricing files).
_PDF_ROOTS = (Path("letters"), Path("."))


# --------------------------------------------------------------------------- view model

@dataclass
class Cell:
    """One (model, strategy) call for one letter."""
    model: str
    strategy: str
    found: bool                       # was there a result file?
    translations: dict                # {sequence: text}; {} when not found
    alert_category: str | None
    alert_reason: str | None
    telemetry: dict | None
    verdict: str | None               # exact | wrong_category | missed | false_alarm | correct_no_alert | None
    verdict_class: str                # pass | partial | fail | neutral


@dataclass
class AlignedRow:
    """One source-paragraph sequence number across every model cell.

    Only the model columns are aligned by sequence: strategy F enumerates the
    source paragraphs, so the models share a sequence convention. The human
    reference is shown as a full block (its paragraph segmentation does not
    reliably match the model sequence numbering in the corpus).
    """
    sequence: int
    cell_texts: dict                  # {"model/strategy": text|None}


@dataclass
class LetterView:
    id: str
    metadata: LetterMetadata
    pdf_path: str | None              # resolved existing path, or None (render reads bytes)
    human_translation: str | None     # full reference block, shown alongside the table
    gold_category: str | None
    rationale: str | None
    rows: list                        # list[AlignedRow]
    cells: list                       # list[Cell], in (model, strategy) request order


@dataclass
class ReportView:
    models: list
    strategies: list
    letter_count: int
    letters: list                     # list[LetterView]
    summary: dict = field(default_factory=dict)   # {"model/strategy": tally(...) dict}
    has_ground_truth: bool = False


# --------------------------------------------------------------------------- assembly

def _resolve_pdf(letter: LetterMetadata) -> str | None:
    for root in _PDF_ROOTS:
        p = root / letter.pdf_path
        if p.exists():
            return str(p)
    return None  # missing PDF must not crash; render shows a placeholder


def _result_path(results_dir: Path, model: str, strategy: str, letter_id: str) -> Path:
    return Path(results_dir) / model / strategy / f"{letter_id}.json"


def _read_result(results_dir: Path, model: str, strategy: str, letter_id: str) -> dict | None:
    f = _result_path(results_dir, model, strategy, letter_id)
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _pred_category(raw: dict | None) -> str | None:
    if not raw:
        return None
    resp = raw.get("response") or {}
    return (resp.get("alert") or {}).get("category")


def _verdict(letter_id: str, gold: str | None, pred: str | None) -> tuple[str | None, str]:
    """Classify one (gold, pred) cell by reusing tally on a single row.

    A missing prediction (pred is None) is treated as "no alert raised", exactly as
    score_screening does. Returns (verdict_label_or_None, css_class); no gold yields
    (None, "neutral").
    """
    r = tally([(letter_id, gold, pred)])
    if r["n"] == 0:
        return None, "neutral"
    d = r["detection"]
    if d["fn"]:
        return "missed", "fail"
    if d["fp"]:
        return "false_alarm", "fail"
    if r["category_mismatches"]:
        return "wrong_category", "partial"
    if d["tp"]:
        return "exact", "pass"
    return "correct_no_alert", "pass"  # true negative


def _build_cell(results_dir: Path, model: str, strategy: str, letter: LetterMetadata) -> Cell:
    gold = getattr(letter.ground_truth, "expected_category", None)
    raw = _read_result(results_dir, model, strategy, letter.id)
    if raw is None:
        verdict, vclass = _verdict(letter.id, gold, None)
        return Cell(model, strategy, False, {}, None, None, None, verdict, vclass)
    resp = raw.get("response") or {}
    translations = {t["sequence"]: t.get("text", "") for t in (resp.get("translations") or [])}
    alert = resp.get("alert") or {}
    pred = alert.get("category")
    verdict, vclass = _verdict(letter.id, gold, pred)
    return Cell(model, strategy, True, translations, pred, alert.get("reason"),
                raw.get("telemetry"), verdict, vclass)


def _aligned_rows(cells: list) -> list:
    """Sequence-aligned rows across the model cells (union of their sequences, sorted)."""
    seqs = set()
    for c in cells:
        seqs |= set(c.translations)
    return [AlignedRow(s, {f"{c.model}/{c.strategy}": c.translations.get(s) for c in cells})
            for s in sorted(seqs)]


def _build_summary(letters: list, results_dir: Path, models: list, strategies: list) -> tuple[dict, bool]:
    gold = {l.id: getattr(l.ground_truth, "expected_category", None) for l in letters}
    gold_ids = [i for i, g in gold.items() if g]
    if not gold_ids:
        return {}, False
    summary = {}
    for m in models:
        for s in strategies:
            rows = [(i, gold[i], _pred_category(_read_result(results_dir, m, s, i))) for i in gold_ids]
            summary[f"{m}/{s}"] = tally(rows)
    return summary, True


def build_report(letters: list, results_dir, models: list, strategies: list) -> ReportView:
    """Assemble the per-letter view model from a loaded corpus + a results directory.

    `letters` is a list[LetterMetadata] (load_corpus output). Touches the filesystem
    only to read result JSON and check PDF existence; PDF bytes are read later, at
    render time. A missing result file for a (model, strategy, letter) cell yields a
    not-found cell rather than an error.
    """
    results_dir = Path(results_dir)
    models = list(models)
    strategies = list(strategies)
    views = []
    for letter in letters:
        cells = [_build_cell(results_dir, m, s, letter) for m in models for s in strategies]
        gt = letter.ground_truth
        views.append(LetterView(
            id=letter.id,
            metadata=letter,
            pdf_path=_resolve_pdf(letter),
            human_translation=letter.human_translation,
            gold_category=getattr(gt, "expected_category", None),
            rationale=getattr(gt, "rationale", None),
            rows=_aligned_rows(cells),
            cells=cells,
        ))
    summary, has_gt = _build_summary(letters, results_dir, models, strategies)
    return ReportView(models, strategies, len(views), views, summary, has_gt)


# --------------------------------------------------------------------------- render (UI layer)

_CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.45 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       color: #202124; margin: 0; padding: 1.5rem; background: #fafafa; }
h1 { font-size: 1.4rem; margin: 0 0 .3rem; }
h2 { font-size: 1.1rem; margin: 0 0 .2rem; }
h3 { font-size: .85rem; text-transform: uppercase; letter-spacing: .04em; color: #5f6368; margin: 1rem 0 .3rem; }
header { background: #fff; border: 1px solid #dadce0; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1.5rem; }
.letter { background: #fff; border: 1px solid #dadce0; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1.5rem; }
.meta { color: #5f6368; margin: 0 0 .5rem; }
.gold { border-left: 4px solid #1a73e8; background: #e8f0fe; padding: .5rem .75rem; margin: .5rem 0; border-radius: 0 4px 4px 0; }
.gold .cat { font-weight: 600; }
.rationale { color: #3c4043; margin-top: .25rem; }
embed.pdf { width: 100%; height: 480px; border: 1px solid #dadce0; border-radius: 4px; }
details.pdf-wrap { margin: .3rem 0; }
details.pdf-wrap > summary { cursor: pointer; color: #1a73e8; font-weight: 600; padding: .3rem 0; }
.placeholder { color: #9aa0a6; font-style: italic; border: 1px dashed #dadce0; border-radius: 4px; padding: 1rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0; }
.scroll { overflow-x: auto; }
th, td { border: 1px solid #e0e0e0; padding: .4rem .55rem; text-align: left; vertical-align: top; }
th { background: #f1f3f4; font-weight: 600; }
td.seq { text-align: right; color: #5f6368; width: 3rem; }
table.aligned td { white-space: pre-wrap; }
td.empty { background: #fbfbfb; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.badge { display: inline-block; padding: .05rem .45rem; border-radius: 10px; font-size: .8rem; font-weight: 600; }
.pass { background: #e6f4ea; }
.partial { background: #fef7e0; }
.fail { background: #fce8e6; }
.neutral { background: #f1f3f4; }
.pass .badge { color: #137333; }
.partial .badge { color: #b06000; }
.fail .badge { color: #c5221f; }
.muted { color: #9aa0a6; }
pre { white-space: pre-wrap; background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 4px; padding: .6rem; margin: 0; }
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _pdf_data_uri(pdf_path: str) -> str:
    b64 = base64.b64encode(Path(pdf_path).read_bytes()).decode("ascii")
    return f"data:application/pdf;base64,{b64}"


def _render_summary(report: ReportView) -> str:
    head = (f"<p class='meta'>Models: {_esc(', '.join(report.models))} &middot; "
            f"Strategies: {_esc(', '.join(report.strategies))} &middot; "
            f"Letters: {report.letter_count}</p>")
    if not report.has_ground_truth:
        return head + "<p class='muted'>No ground-truth labels in this corpus; screening scorecard omitted.</p>"
    rows = []
    for key, m in report.summary.items():
        d = m["detection"]
        missed = ", ".join(f"{i} (expected {g}, got {p or 'no result'})" for i, g, p in m["false_negatives"])
        missed_cell = _esc(missed) if missed else "<span class='muted'>none</span>"
        rows.append(
            "<tr>"
            f"<td>{_esc(key)}</td>"
            f"<td class='num'>{m['n']}</td>"
            f"<td class='num'>{_pct(d['recall'])}</td>"
            f"<td class='num'>{_pct(d['precision'])}</td>"
            f"<td class='num'>{_pct(m['exact_accuracy'])}</td>"
            f"<td class='num'>{d['tp']}/{d['fn']}/{d['fp']}/{d['tn']}</td>"
            f"<td>{missed_cell}</td>"
            "</tr>"
        )
    return head + (
        "<h3>Screening scorecard</h3>"
        "<div class='scroll'><table>"
        "<thead><tr><th>model/strategy</th><th>n</th><th>recall</th><th>precision</th>"
        "<th>exact</th><th>TP/FN/FP/TN</th><th>missed alerts (false negatives)</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


# Above this many letters, PDFs render collapsed so the browser does not spin up one
# PDF viewer per letter on load (a self-contained report of N heavy PDFs gets large fast).
_PDF_OPEN_MAX = 10


def _render_pdf(letter: LetterView, open_by_default: bool, pdf_mode: str, out_dir) -> str:
    if letter.pdf_path is None:
        return f"<p class='placeholder'>PDF not found ({_esc(letter.metadata.pdf_path)})</p>"
    if pdf_mode == "embed":
        src = _pdf_data_uri(letter.pdf_path)                              # base64: portable but large
    else:
        src = Path(os.path.relpath(letter.pdf_path, out_dir)).as_posix()  # relative link: tiny HTML
    open_attr = " open" if open_by_default else ""
    return (f"<details class='pdf-wrap'{open_attr}><summary>source PDF</summary>"
            f"<embed class='pdf' type='application/pdf' src='{_esc(src)}'>"
            "</details>")


def _render_aligned(letter: LetterView) -> str:
    keys = [f"{c.model}/{c.strategy}" for c in letter.cells]
    header = "<th>seq</th>" + "".join(f"<th>{_esc(k)}</th>" for k in keys)
    body = []
    for row in letter.rows:
        cells = [f"<td class='seq'>{row.sequence}</td>"]
        cells += [_render_aligned_cell(row.cell_texts.get(k)) for k in keys]
        body.append(f"<tr>{''.join(cells)}</tr>")
    return ("<h3>Translations (aligned by source paragraph)</h3>"
            "<div class='scroll'><table class='aligned'>"
            f"<thead><tr>{header}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def _render_aligned_cell(text) -> str:
    if text is None:
        return "<td class='empty'></td>"
    return f"<td>{_esc(text)}</td>"


def _render_alerts(letter: LetterView) -> str:
    show_verdict = letter.gold_category is not None
    rows = []
    for c in letter.cells:
        if not c.found:
            rows.append(f"<tr><td>{_esc(c.model)}/{_esc(c.strategy)}</td>"
                        f"<td colspan='{3 if show_verdict else 2}' class='muted'>no result</td></tr>")
            continue
        verdict_cell = (f"<td><span class='badge'>{_esc(c.verdict)}</span></td>") if show_verdict else ""
        rows.append(
            f"<tr class='{c.verdict_class}'>"
            f"<td>{_esc(c.model)}/{_esc(c.strategy)}</td>"
            f"<td>{_esc(c.alert_category)}</td>"
            f"<td>{_esc(c.alert_reason)}</td>"
            f"{verdict_cell}</tr>"
        )
    gold_header = "<th>gold: " + _esc(letter.gold_category) + "</th>" if show_verdict else ""
    return ("<h3>Alert vs gold</h3>" if show_verdict else "<h3>Alert</h3>") + (
        "<div class='scroll'><table>"
        f"<thead><tr><th>model/strategy</th><th>predicted</th><th>reason</th>{gold_header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _render_telemetry(letter: LetterView) -> str:
    fields = ["tokens_in", "tokens_out", "tokens_thought", "total_tokens", "cost_usd"]
    rows = []
    for c in letter.cells:
        t = c.telemetry or {}
        nums = "".join(f"<td class='num'>{_esc(t.get(f, 'n/a'))}</td>" for f in fields)
        rows.append(f"<tr><td>{_esc(c.model)}/{_esc(c.strategy)}</td>{nums}</tr>")
    head = "".join(f"<th>{f}</th>" for f in fields)
    return ("<h3>Telemetry</h3>"
            "<div class='scroll'><table>"
            f"<thead><tr><th>model/strategy</th>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _render_letter(letter: LetterView, pdf_open: bool, pdf_mode: str, out_dir) -> str:
    md = letter.metadata
    q = md.translation_queue
    parts = [
        "<section class='letter'>",
        f"<h2>{_esc(letter.id)} &middot; {_esc(md.type)} &middot; {_esc(md.direction)} &middot; {_esc(md.country)}</h2>",
        (f"<p class='meta'>child {_esc(md.child.preferred_first_name)} ({_esc(md.child.age)}) &middot; "
         f"sponsor {_esc(md.sponsor.first_name)} &middot; {_esc(q.source)} &rarr; {_esc(q.target)}</p>"),
    ]
    if letter.gold_category is not None:
        parts.append(f"<div class='gold'><span class='cat'>gold: {_esc(letter.gold_category)}</span>"
                     f"<div class='rationale'>{_esc(letter.rationale)}</div></div>")
    parts.append(_render_pdf(letter, pdf_open, pdf_mode, out_dir))
    if letter.human_translation:
        parts.append(f"<h3>Human reference</h3><pre>{_esc(letter.human_translation)}</pre>")
    parts.append(_render_aligned(letter))
    parts.append(_render_alerts(letter))
    parts.append(_render_telemetry(letter))
    parts.append("</section>")
    return "".join(parts)


def render_html(report: ReportView, pdf_mode: str = "link", out_dir=Path(".")) -> str:
    pdf_open = report.letter_count <= _PDF_OPEN_MAX
    body = [
        "<header><h1>Benchmark review</h1>",
        _render_summary(report),
        "</header>",
    ]
    body += [_render_letter(l, pdf_open, pdf_mode, out_dir) for l in report.letters]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Benchmark review</title>"
        f"<style>{_CSS}</style></head><body>"
        + "".join(body)
        + "</body></html>"
    )


# --------------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="Self-contained HTML benchmark review report")
    ap.add_argument("--corpus", required=True, help="corpus JSON ({version, letters:[...]})")
    ap.add_argument("--results-dir", required=True, help="run dir holding <model>/<strategy>/<letter>.json")
    ap.add_argument("--models", required=True, help="comma-separated model names")
    ap.add_argument("--strategies", default="F", help="comma-separated strategies (default F)")
    ap.add_argument("--letters", default=None,
                    help="comma-separated letter ids to include; 'all' for every corpus letter; "
                         "default: letters with a result in this run (plus any carrying ground truth)")
    ap.add_argument("--out", required=True, help="output .html path (keep under gitignored benchmark/results/)")
    ap.add_argument("--pdf", choices=["link", "embed"], default="link",
                    help="source PDFs: 'link' (relative path, tiny HTML; needs the PDFs present locally) "
                         "or 'embed' (base64, one portable file but large). Default link.")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    results_dir = Path(args.results_dir)
    corpus = load_corpus(args.corpus)

    if args.letters and args.letters.strip().lower() == "all":
        selected = corpus
    elif args.letters:
        wanted = {x.strip() for x in args.letters.split(",") if x.strip()}
        selected = [l for l in corpus if l.id in wanted]
    else:
        selected = [
            l for l in corpus
            if l.ground_truth is not None
            or any(_result_path(results_dir, m, s, l.id).exists() for m in models for s in strategies)
        ]
        skipped = len(corpus) - len(selected)
        if skipped:
            print(f"skipped {skipped} corpus letter(s) with no result in {results_dir} "
                  f"(use --letters all to include them)")

    report = build_report(selected, results_dir, models, strategies)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(report, args.pdf, out.parent), encoding="utf-8")
    print(f"wrote report to {out}  "
          f"({report.letter_count} letters, {len(models)}x{len(strategies)} cells/letter, pdf={args.pdf})")


if __name__ == "__main__":
    main()
