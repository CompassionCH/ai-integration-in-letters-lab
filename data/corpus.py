"""Canonical schema + strict loader for letters/corpus.json.

Single-sourced contract consumed by the pre-processing pipeline and the DB
loader. See letters/corpus.example.json for an annotated template.
"""
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)

VOLUNTEER_LANGS = {"en", "fr", "de", "it"}
MAX_OTHER_SPONSORED = 16


class Child(BaseModel):
    official_first_name: str
    preferred_first_name: str
    sex: Literal["M", "F"]
    age: int


class Sponsor(BaseModel):
    first_name: str
    other_sponsored_first_names: list[str] = []
    # Salutation / addressee form as extracted from the source system (e.g. "Madam",
    # "Mister", "Family", "Mister and Madam"). A sponsor may be a couple or a family,
    # so unlike a child this is not a binary M/F. Age is frequently unavailable.
    sex: str
    age: int | None = None


class TranslationQueue(BaseModel):
    source: str
    target: str

    @field_validator("source", "target")
    @classmethod
    def _within_volunteer_set(cls, value: str) -> str:
        if value not in VOLUNTEER_LANGS:
            raise ValueError(
                f"language {value!r} is outside the volunteer set {sorted(VOLUNTEER_LANGS)}"
            )
        return value


class Paragraph(BaseModel):
    page_index: int
    sequence: int
    source_text: str
    human_translation: str | None = None
    comments: str | None = None


class PageLevel(BaseModel):
    original_text: str | None = None
    english_text: str | None = None
    translated_text: str | None = None


class GroundTruth(BaseModel):
    expected_category: str
    rationale: str
    source_letter_id: str | None = None


class LetterMetadata(BaseModel):
    id: str
    type: Literal["real", "synthetic"]
    pdf_path: str
    direction: Literal["child_to_sponsor", "sponsor_to_child"]
    translation_queue: TranslationQueue
    country: str
    child: Child
    sponsor: Sponsor
    page_level: PageLevel
    paragraphs: list[Paragraph] | None = None
    human_translation: str | None = None
    human_translation_origin_field: str | None = None
    ground_truth: GroundTruth | None = None
    notes: str | None = None


def load_corpus(path: str = "letters/corpus.json") -> list[LetterMetadata]:
    """Load and validate the corpus, returning one LetterMetadata per entry.

    Raises ValueError naming the offending letter id + field on the first
    invalid entry. Logs a warning (does not reject) when a sponsor lists more
    than 16 other sponsored children.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        entries = raw["letters"]
    except (TypeError, KeyError) as exc:
        raise ValueError(f"{path}: missing top-level 'letters' array") from exc

    letters: list[LetterMetadata] = []
    for index, entry in enumerate(entries):
        ident = entry.get("id", f"index {index}") if isinstance(entry, dict) else f"index {index}"
        try:
            letter = LetterMetadata.model_validate(entry)
        except ValidationError as exc:
            raise ValueError(f"Invalid letter {ident}: {exc}") from exc

        extra = len(letter.sponsor.other_sponsored_first_names)
        if extra > MAX_OTHER_SPONSORED:
            logger.warning(
                "Letter %s: sponsor lists %d other_sponsored_first_names (>%d) — kept",
                letter.id,
                extra,
                MAX_OTHER_SPONSORED,
            )
        letters.append(letter)
    return letters
