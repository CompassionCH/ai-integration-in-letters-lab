# ai-integration-in-letters-lab

A workspace for volunteer translators to review AI-assisted translations of
sponsor–child letters.

## Stack

FastAPI · Jinja2 · HTMX 2 · Tailwind CSS v4 (standalone CLI, self-hosted) ·
Pydantic v2 · SQLite (stdlib) · `google-genai` (Gemini API) · pytest · httpx ·
python-dotenv. Python ≥ 3.11.

## Local setup

```bash
# 1. Virtual environment + dependencies (Python >= 3.11)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Secrets
cp .env.example .env
```

Then edit `.env`:

- **`ACCESS_TOKEN`** and **`ADMIN_TOKEN`**, pick any two strings. Both are
  required: the app refuses to start without `ADMIN_TOKEN`, and the whole site
  sits behind `ACCESS_TOKEN`.
- **`COOKIE_SECURE=false`**, **required for local HTTP.** The session / invite /
  admin cookies are `Secure`-only by default, so over `http://localhost` they
  would not round-trip and you'd be stuck on the invite notice page.
- `GEMINI_API_KEY`, only used by the offline pre-processing; leave it blank for
  local UI work.

```bash
# 3. Frontend assets (fetches the pinned Tailwind binary, vendors HTMX + Alpine +
#    Inter fonts, then compiles the CSS).
make install-assets
make build-assets

# 4. Local sample data
python -m scripts.seed_dev
```

`seed_dev.py` populates the database with fictional letters + AI responses
(and a couple of sample votes) so both flows work end to end; it resets the local
DB on each run and writes placeholder PDFs under `letters/dev/`. The real corpus
and the Gemini pre-processing that normally fills these tables are separate and
not run here. (For a bare, empty database instead, use `python -m db.init`.)

```bash
# 5. Run (in a second terminal, `make watch-css` rebuilds CSS on change)
uvicorn main:app --reload --port 8000
```

Then open, with the tokens from your `.env`:

- **Volunteer flow:** `http://localhost:8000/?invite=<ACCESS_TOKEN>`, the token is
  consumed once into a cookie and stripped from the URL; later visits just need
  the cookie.
- **Admin dashboard:** `http://localhost:8000/admin?token=<ADMIN_TOKEN>`.

Without a valid invite you get a short notice page instead of the application.

## Tests

```bash
pytest
```

## Assets

The frontend is fully self-hosted, no CDN at runtime. HTMX and Alpine are
vendored and the CSS is compiled from `static/css/app.src.css` by the Tailwind
standalone binary. Visual-identity assets (logo, favicon) live in
`static/branding/`.

## Confidentiality

This repository never contains real letter data: the live corpus (`letters/corpus.json`), the letter PDFs and the AI outputs are all gitignored. The only corpus file tracked here, [`letters/corpus.example.json`](./letters/corpus.example.json), is **entirely fictional** — invented names, invented letter texts — and exists solely to document the corpus schema.

## License

MIT — see [LICENSE](./LICENSE).
