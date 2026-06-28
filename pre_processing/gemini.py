"""Shared Gemini access for the offline pipeline (production runner + benchmark).

ZERO DATA RETENTION posture (real children's letters): PDFs are sent INLINE (no File
API, which is not auto-purged under ZDR); no `cached_content`; no tools / Search / Maps
grounding. Calls go via VERTEX AI ("Agent Platform API") on the ZDR-approved Cloud
project (the prompt-logging exception is per project). Auth is configured in `.env` and
consumed by the SDK; this module inspects only the PRESENCE of the auth env vars and
never reads, prints, or persists any key or credential value.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from data.corpus import LetterMetadata

_PDF_ROOTS = (Path("letters"), Path("."))

# The locked Gemini output contract. One source for every caller.
SCHEMA = json.loads(Path("pre_processing/prompts/response_schema.json").read_text(encoding="utf-8"))


def resolve_pdf(letter: LetterMetadata) -> str | None:
    """Resolve a letter's PDF under letters/ (covers real/ and synthetic/); None if missing."""
    for root in _PDF_ROOTS:
        p = root / letter.pdf_path
        if p.exists():
            return str(p)
    return None


def pdf_bytes(letter: LetterMetadata) -> bytes:
    path = resolve_pdf(letter)
    if path is None:
        raise FileNotFoundError(
            f"PDF not found for {letter.id}; tried {[str(r / letter.pdf_path) for r in _PDF_ROOTS]}")
    return Path(path).read_bytes()


def client():
    """Vertex AI client; auth from `.env` (express API key OR ADC + project/location).

    The two modes are mutually exclusive: the SDK silently ignores the key when
    project/location are also set, so we refuse that combination up front.
    """
    from dotenv import load_dotenv
    load_dotenv()
    has_key = bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    has_project = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    has_location = bool(os.environ.get("GOOGLE_CLOUD_LOCATION"))
    if has_key and (has_project or has_location):
        raise SystemExit("Both an API key and GOOGLE_CLOUD_PROJECT/LOCATION are set in .env; the SDK "
                         "ignores the key when project/location are present. Clear the GOOGLE_CLOUD_* "
                         "lines for express mode. Aborting — no call made.")
    if not has_key and not has_project:
        raise SystemExit("No Vertex auth in .env. Set GOOGLE_API_KEY (express) or GOOGLE_CLOUD_PROJECT "
                         "+ `gcloud auth application-default login` (ADC). Aborting — no call made.")
    from google import genai
    return genai.Client(vertexai=True)


def call(client, prompt: str, pdf: bytes, model: str, *, temperature: float, schema=SCHEMA):
    """One generate_content call: prompt text + the PDF inline, with the locked schema."""
    from google.genai import types
    contents = [types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=pdf, mime_type="application/pdf")]
    cfg = types.GenerateContentConfig(response_mime_type="application/json",
                                      response_schema=schema, temperature=temperature)
    return client.models.generate_content(model=model, contents=contents, config=cfg)


def count_tokens(client, prompt: str, pdf: bytes, model: str) -> int:
    """Input token count (count_tokens; no generation, no charge)."""
    from google.genai import types
    contents = [types.Part.from_text(text=prompt),
                types.Part.from_bytes(data=pdf, mime_type="application/pdf")]
    return client.models.count_tokens(model=model, contents=contents).total_tokens or 0


def parse_response(text: str) -> dict:
    """Parse + minimally validate the structured JSON. Raises ValueError if malformed."""
    if not text:
        raise ValueError("empty response text")
    data = json.loads(text)  # json.JSONDecodeError is a ValueError subclass
    if not isinstance(data, dict) or "translations" not in data or "alert" not in data:
        raise ValueError("response missing required 'translations' / 'alert'")
    return {"translations": data["translations"], "alert": data["alert"]}
