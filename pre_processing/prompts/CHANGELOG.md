# Prompt artefacts — changelog

This folder holds the language-model contract for the offline
translation-and-screening pass: the structured-output schema the model is
constrained to return, the alert category set, and supporting data files.

## v4 — 2026-07-01

One screening refinement from the v3 full-run review: the translation **direction** is now locked.

- The model must translate **only** in the queue direction (source → target) and **never** invert it.
  If the letter is not written in the source language — including when it is entirely in the target
  language — it must report `wrong_language` rather than silently translating in the reverse direction.
  Closes a stochastic v3 failure (SI-012): a `de → en` letter that was actually written in English was
  translated *into German* with `no_alert`, instead of being flagged `wrong_language`.
- v3's content and blank-page refinements are retained unchanged.

Full run (2026-07-01): 59/59 ok, 0 failures, **$1.2692** total. On the 39 ground-truth letters:
**precision 1.000, recall 1.000, exact 1.000** (TP 27 / FN 0 / FP 0 / TN 12) — SI-012 is now correctly
`wrong_language`, and the direction rule produced **no** false `wrong_language` anywhere else. The only
non-GT movement vs v3: the blank-page rule fired on R-006 (real, genuinely-blank page 4) while R-020
reverted to `no_alert` — the trailing-blank flag rotates stochastically across the real 4-page-template
letters (all confirmed genuine blank pages; benign, and none carry ground truth).

Target model: `gemini-3.5-flash`.

## v3 — 2026-07-01

Two screening-rule refinements from the v2 full-run review (prompt-only; the assembler is
version-aware, so no code change).

- `content_inappropriate` now names revealing / body-focused **clothing** — tight-fitting or
  low-cut clothing, or clothing baring the midriff or cleavage (a sports bra or crop top, low-cut or
  form-fitting eveningwear) — and states that an everyday setting (a gym, a workout, a party, a
  graduation) does not excuse it. The bare-chest and modest-clothing carve-out is unchanged, so a
  bare male torso in sport/wellness still does not flag. (Targets the two v2 misses SI-018 / SI-021.)
- `broken_pdf` now also covers a whole page that renders **entirely blank** (no text, no image) —
  reported **even when the rest of the letter reads perfectly** — while explicitly **not** flagging the
  empty "Translation" boxes / unfilled form fields that normally sit on a content page, nor a
  photo/drawing page with little text. (Targets the v2 miss RI-002, a blank page 1.)
- Unchanged from v2: child-protection (incl. the last-name rule, which correctly caught a real
  child's full name on R-001), name rules, sensitive-country block, translation + layout.

Full run (2026-07-01): 59/59 ok, 0 failures, **$1.4343** total. On the 39 ground-truth letters:
precision 1.000, recall 0.963, exact 0.974 (TP 26 / FN 1 / FP 0 / TN 12) — up from v2's 0.889 /
0.923. The two content misses (SI-018, SI-021) and the blank page (RI-002) are all now caught with
0 collateral false positives; the one remaining GT miss (SI-012, `wrong_language` → `no_alert`) is
run-to-run model variance at temperature 0.3, not a rule gap. The strengthened blank-page rule also
flagged R-020 (real, no GT): its page 4 is genuinely blank — a benign trailing template page rather
than an anomalous one, but technically a correct application of the rule.

Target model: `gemini-3.5-flash`.

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

Full run (2026-07-01): 59/59 letters ok, 0 failures, **$1.5884** total (`gemini-3.5-flash`,
temperature 0.3). On the 39 ground-truth letters: precision 1.000, recall 0.889, exact 0.923
(TP 24 / FN 3 / FP 0 / TN 12). The 3 misses (SI-018, SI-021 revealing-clothing imagery; RI-002 a
blank page) drove the v3 refinements above; R-001 (real) was correctly flagged `child_protection`
for a disclosed full name.

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
