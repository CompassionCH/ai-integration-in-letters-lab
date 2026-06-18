# Prompt artefacts — changelog

This folder holds the language-model contract for the offline
translation-and-screening pass: the structured-output schema the model is
constrained to return, the alert category set, and supporting data files.

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
