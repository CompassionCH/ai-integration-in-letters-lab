"""Strategy-aware prompt assembler for the translation + screening pipeline.

Builds the per-letter prompt for one strategy (A / D / F, with an optional
per-paragraph length budget) from the static `system_prompt_v1.md` template plus
the letter metadata. Pure string assembly; no IO beyond reading the prompt files.

Canonical assembler for both the production runner (`pre_processing.run_gemini`,
strategy F) and the benchmark (`benchmark.run`). A and D are research-only (the
benchmark chose F); production uses F. The strategies:

- **A** — translate the whole letter as one block; the scorer re-splits it to N
  source paragraphs afterwards. The known-weak baseline.
- **D** — the model segments the letter into paragraphs itself.
- **F** — the source paragraphs are enumerated in the prompt and the model returns
  one translation per index (alignment guaranteed by construction). Falls back to
  D-style when the letter has no machine-readable source text (scan-only letters).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from data.corpus import LetterMetadata

_PROMPTS = Path("pre_processing/prompts")
_SYSTEM_PROMPT = _PROMPTS / "system_prompt_v1.md"
_SENSITIVE = _PROMPTS / "sensitive_countries.json"

_LANG_NAMES = {"en": "English", "fr": "French", "de": "German", "it": "Italian"}
_DIRECTION = {"child_to_sponsor": "child to sponsor", "sponsor_to_child": "sponsor to child"}
_BUDGET_FACTOR = 1.15
_STRATEGIES = {"A", "D", "F"}

# The conditional faith-content region, delimited in the template.
_BLOCK_RE = re.compile(
    r"<!-- BEGIN sensitive-country-block -->\n(?P<body>.*?)\n<!-- END sensitive-country-block -->\n?",
    re.DOTALL,
)
_COMMENT_RE = re.compile(r"<!--.*?-->\n?", re.DOTALL)


def _sensitive_countries() -> set[str]:
    return set(json.loads(_SENSITIVE.read_text(encoding="utf-8"))["countries"])


def _lang(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def _has_source_text(letter: LetterMetadata) -> bool:
    return bool(letter.paragraphs) and any((p.source_text or "").strip() for p in letter.paragraphs)


def _source_block(letter: LetterMetadata, strategy: str, *, budget: bool) -> str:
    """Render the per-strategy `{{source_paragraphs}}` region."""
    if strategy == "A":
        return (
            "Translate the **entire letter** as one continuous piece, using the attached PDF. "
            "Return the whole translation as a single entry with `sequence` 1."
        )
    if strategy == "D" or (strategy == "F" and not _has_source_text(letter)):
        extra = (
            " (this letter has no machine-readable source paragraphs, so rely on the attached PDF)"
            if strategy == "F"
            else ""
        )
        return (
            f"Segment the letter into its natural paragraphs yourself{extra}. Return one "
            "translation per paragraph, numbered sequentially from 1 in reading order. Keep "
            "segments at the natural paragraph level — do not break a paragraph into individual "
            "sentences or list items."
        )
    # F with usable source paragraphs: enumerate them for one-to-one alignment.
    n = len(letter.paragraphs or [])
    lines = [
        f"Translate each of the {n} source paragraphs listed below. Return **exactly {n} "
        f"translations** — one per `sequence`, keeping the same numbers and order. Do **not** split "
        "a source paragraph into several entries (even when it is long or contains multiple "
        "sentences, list items, or line breaks), and do **not** merge paragraphs. The listed text is "
        "an alignment anchor and may be an incomplete transcription: treat the attached PDF as the "
        "source of truth and, for each `sequence`, translate the complete content visible on that "
        "part of the page (including pre-printed form questions and checkbox answers), not merely the "
        "text shown here.",
        "",
    ]
    for i, para in enumerate(letter.paragraphs or [], start=1):
        hint = ""
        if budget:
            ref = max(len(para.source_text or ""), len(para.human_translation or ""))
            hint = f" _(aim for roughly {round(ref * _BUDGET_FACTOR)} characters)_"
        lines.append(f"{i}. (page {para.page_index + 1}) {(para.source_text or '').strip()}{hint}")
    return "\n".join(lines)


def build_prompt(letter: LetterMetadata, strategy: str, *, budget: bool = False) -> str:
    """Assemble the full prompt for `letter` under `strategy`.

    The faith-content block is kept only for sponsor->child letters whose recipient
    country is on the sensitive list; it is dropped otherwise. `budget=True` adds
    per-paragraph length hints (strategy F only).
    """
    if strategy not in _STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r} (expected one of {sorted(_STRATEGIES)})")

    text = _SYSTEM_PROMPT.read_text(encoding="utf-8")

    keep_block = letter.direction == "sponsor_to_child" and letter.country in _sensitive_countries()
    text = _BLOCK_RE.sub((lambda m: m.group("body") + "\n") if keep_block else "", text)
    text = _COMMENT_RE.sub("", text)  # strip all remaining template comments

    others = letter.sponsor.other_sponsored_first_names
    for key, value in {
        "{{translation_queue}}": f"{_lang(letter.translation_queue.source)} → {_lang(letter.translation_queue.target)}",
        "{{direction}}": _DIRECTION.get(letter.direction, letter.direction),
        "{{child_official_name}}": letter.child.official_first_name,
        "{{child_preferred_name}}": letter.child.preferred_first_name,
        "{{sponsor_first_name}}": letter.sponsor.first_name,
        "{{other_sponsored_first_names}}": ", ".join(others) if others else "none on file",
        "{{country}}": letter.country,
        "{{source_paragraphs}}": _source_block(letter, strategy, budget=budget),
    }.items():
        text = text.replace(key, value)

    text = re.sub(r"\n{3,}", "\n\n", text)  # tidy blank runs left by stripped comments
    return text.strip() + "\n"
