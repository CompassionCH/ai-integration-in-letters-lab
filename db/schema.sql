-- Persistent state of the webapp. Applied idempotently by db/init.py.
-- sqlite3 stdlib, no ORM. Timestamps are ISO-8601 text (UTC) via CURRENT_TIMESTAMP.

-- Corpus snapshot --------------------------------------------------------------

CREATE TABLE IF NOT EXISTS letters (
    id                            INTEGER PRIMARY KEY,
    display_ref                   TEXT UNIQUE,          -- opaque client-facing ref (computed later); NULL until set
    type                          TEXT,                 -- experimental stratum; server-side only, never sent to clients
    pdf_path                      TEXT,
    direction                     TEXT,
    source_lang                   TEXT,
    target_lang                   TEXT,
    country                       TEXT,
    child_official                TEXT,
    child_preferred               TEXT,
    child_sex                     TEXT,
    child_age                     INTEGER,
    sponsor_first                 TEXT,
    sponsor_other_first_names_csv TEXT,
    sponsor_sex                   TEXT,
    sponsor_age                   INTEGER,
    human_translation_text        TEXT,
    ground_truth_category         TEXT,
    ground_truth_rationale        TEXT,
    source_letter_id              INTEGER REFERENCES letters(id)
);

CREATE TABLE IF NOT EXISTS letter_paragraphs (
    id                INTEGER PRIMARY KEY,
    letter_id         INTEGER NOT NULL REFERENCES letters(id),
    page_index        INTEGER NOT NULL,
    sequence          INTEGER NOT NULL,
    source_text       TEXT,
    human_translation TEXT,
    UNIQUE (letter_id, page_index, sequence)
);

-- AI side ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ai_responses (
    id                   INTEGER PRIMARY KEY,
    letter_id            INTEGER NOT NULL REFERENCES letters(id),
    prompt_version       TEXT NOT NULL,
    model                TEXT NOT NULL,
    translation_text     TEXT,
    alert_category       TEXT,
    alert_reason         TEXT,
    tokens_in            INTEGER,
    tokens_out           INTEGER,
    cost_usd             REAL,
    safety_filter_status TEXT,
    processed_at         TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (letter_id, prompt_version, model)
);

CREATE TABLE IF NOT EXISTS ai_response_paragraphs (
    id             INTEGER PRIMARY KEY,
    ai_response_id INTEGER NOT NULL REFERENCES ai_responses(id),
    page_index     INTEGER NOT NULL,
    sequence       INTEGER NOT NULL,
    text           TEXT,
    UNIQUE (ai_response_id, page_index, sequence)
);

-- Participant side -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY,
    session_token    TEXT NOT NULL UNIQUE,
    first_name       TEXT,
    last_name        TEXT,
    source_langs_csv TEXT,
    target_langs_csv TEXT,
    started_at       TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_at     TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS votes (
    id                 INTEGER PRIMARY KEY,
    session_id         INTEGER NOT NULL REFERENCES sessions(id),
    letter_id          INTEGER NOT NULL REFERENCES letters(id),
    ai_response_id     INTEGER NOT NULL REFERENCES ai_responses(id),
    -- preference / a_is_ai are NULL for synthetic letters (no human translation -> no
    -- A/B card); set for real letters. The CHECK still constrains the non-NULL values.
    preference         TEXT CHECK (preference IN ('A', 'B', 'Equivalent')),
    a_is_ai            INTEGER CHECK (a_is_ai IN (0, 1)),
    preference_comment TEXT,
    voted_at           TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (session_id, letter_id)
);

CREATE TABLE IF NOT EXISTS alert_evaluations (
    id             INTEGER PRIMARY KEY,
    vote_id        INTEGER NOT NULL REFERENCES votes(id),
    ai_response_id INTEGER NOT NULL REFERENCES ai_responses(id),
    verdict        TEXT CHECK (verdict IN ('Correct', 'Incorrect', 'Mixed')),
    comment        TEXT
);

CREATE TABLE IF NOT EXISTS missed_issues (
    id            INTEGER PRIMARY KEY,
    vote_id       INTEGER NOT NULL REFERENCES votes(id),
    missed_yes_no INTEGER CHECK (missed_yes_no IN (0, 1)),
    category      TEXT,
    reason        TEXT
);

-- Generic key/value store (e.g. active_prompt_version) -------------------------

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indices on foreign-key / filter columns --------------------------------------

CREATE INDEX IF NOT EXISTS idx_letter_paragraphs_letter      ON letter_paragraphs(letter_id);
CREATE INDEX IF NOT EXISTS idx_ai_responses_letter           ON ai_responses(letter_id);
CREATE INDEX IF NOT EXISTS idx_ai_response_paragraphs_response ON ai_response_paragraphs(ai_response_id);
CREATE INDEX IF NOT EXISTS idx_votes_session                 ON votes(session_id);
CREATE INDEX IF NOT EXISTS idx_votes_letter                  ON votes(letter_id);
CREATE INDEX IF NOT EXISTS idx_votes_ai_response             ON votes(ai_response_id);
CREATE INDEX IF NOT EXISTS idx_alert_evaluations_vote        ON alert_evaluations(vote_id);
CREATE INDEX IF NOT EXISTS idx_missed_issues_vote            ON missed_issues(vote_id);
