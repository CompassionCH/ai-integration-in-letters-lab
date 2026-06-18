# ai-integration-in-letters-lab

A workspace for volunteer translators to review AI-assisted translations of
sponsor–child letters.

## Stack

FastAPI · Jinja2 · HTMX 2 · Tailwind CSS v4 (standalone CLI, self-hosted) ·
Pydantic v2 · SQLite (stdlib) · `google-genai` (Gemini API) · pytest · httpx ·
python-dotenv. Python ≥ 3.11.

## Quick start

Requires **Python ≥ 3.11**.

```bash
# 1. Virtual environment + dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Secrets
cp .env.example .env          # then fill in GEMINI_API_KEY, ADMIN_TOKEN, ACCESS_TOKEN

# 3. Frontend assets (fetches the pinned Tailwind binary + HTMX, then compiles CSS)
make install-assets
make build-assets

# 4. Run
uvicorn main:app --reload --port 8000
```

The frontend is fully self-hosted — no CDN at runtime. HTMX is vendored and the
CSS is compiled from `static/css/app.src.css` by the Tailwind standalone binary
(no Node.js required). During CSS work, run `make watch-css` in a second
terminal. Run the tests with `pytest`.

Open the app via its invite link (`/?invite=<ACCESS_TOKEN>`); without a valid
invite you get a short notice page instead of the application.

## Confidentiality

This repository never contains real letter data: the live corpus (`letters/corpus.json`), the letter PDFs and the AI outputs are all gitignored. The only corpus file tracked here, [`letters/corpus.example.json`](./letters/corpus.example.json), is **entirely fictional** — invented names, invented letter texts — and exists solely to document the corpus schema.

## License

MIT — see [LICENSE](./LICENSE).
