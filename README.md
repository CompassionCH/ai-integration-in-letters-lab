# ai-integration-in-letters-lab

## Stack

FastAPI · Jinja2 · HTMX 2 · Tailwind CSS (standalone CLI) · Pydantic v2 · SQLite (stdlib) · `google-genai` (Gemini API) · pytest · httpx · python-dotenv.

## Quick start

```bash
cp .env.example .env  # then fill in GEMINI_API_KEY and ADMIN_TOKEN
# Implementation tasks will land here progressively
```

## Confidentiality

This repository never contains real letter data: the live corpus (`letters/corpus.json`), the letter PDFs and the AI outputs are all gitignored. The only corpus file tracked here, [`letters/corpus.example.json`](./letters/corpus.example.json), is **entirely fictional** — invented names, invented letter texts — and exists solely to document the corpus schema.

## License

MIT — see [LICENSE](./LICENSE).
