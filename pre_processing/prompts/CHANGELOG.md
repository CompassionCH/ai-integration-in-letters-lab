# Prompt artefacts — changelog

This folder holds the language-model contract for the offline
translation-and-screening pass: the structured-output schema the model is
constrained to return, the alert category set, and supporting data files.

## v2 — 2026-07-01

Editorial pass over v1: shorter and less repetitive, with the screening policy carried over unchanged.

- Consolidated the translation guidance so "the PDF page is the source of truth" is stated once, and
  removed wording that duplicated the per-letter source-paragraph block the assembler injects at run
  time.
- Generalised two letter-specific examples (a stray routing code, a named form sheet) into the
  underlying rule, and compressed the `invalid_layout` note and other prose.
- Screening rules are carried over from v1: the child-protection rules, the content do-not-flag
  carve-outs, the name rules, and the sensitive-country block are unchanged. The only screening edit
  is cosmetic — one over-enumerated imagery line was tightened without changing what it flags.
- Translation layout (2026-07-01): the AI now gives each translation a clean, human-like layout —
  reorganising the often-block-y English pivot into natural paragraphs (greeting / paragraphs /
  closing on their own lines), **layout only, content unchanged** — replacing the earlier rule that
  flattened translations into one block. Pure prompt change (the schema `text` field carries real
  newlines; the A/B box renders them via `whitespace-pre-wrap`).

Target model: `gemini-3.5-flash` (provisional — to be confirmed once the production model is
finalized).

## v1 — 2026-06-18

Initial version of the structured-output contract.

- `response_schema.json` — the JSON shape the model must return: one
  `translations` entry per source paragraph (`{sequence, text}`) plus a single
  `alert` object (`{category, reason}`).
- `categories.json` — the single source of truth for the alert category set
  (nine platform issue codes plus `no_alert` and `safety_filter_triggered`).
  Each entry carries `selectable_for_missed`, marking whether a reviewer may
  choose it when reporting an issue the model missed; the two model-output-only
  states are excluded from that list.
- `sensitive_countries.json` — countries for which the sponsor-to-child
  screening applies an extra child-protection check.

Target model: `gemini-3.5-flash` (provisional — to be confirmed once the
production model is finalized).
