-- Canonical schema. `python -m src.db.init` drops the file and replays this script.
-- JSON columns are TEXT; callers encode/decode with json.dumps/loads.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS company (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    website TEXT,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS launch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    posted_at TEXT NOT NULL,
    engagement_score REAL NOT NULL DEFAULT 0,
    engagement_breakdown TEXT NOT NULL DEFAULT '{}',
    raw_payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_launch_company ON launch(company_id);
CREATE INDEX IF NOT EXISTS idx_launch_posted_at ON launch(posted_at);
CREATE INDEX IF NOT EXISTS idx_launch_source ON launch(source);

CREATE TABLE IF NOT EXISTS funding_round (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    amount_usd INTEGER,
    round_type TEXT,
    announced_at TEXT NOT NULL,
    investors TEXT NOT NULL DEFAULT '[]',
    raw_payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_funding_company ON funding_round(company_id);
CREATE INDEX IF NOT EXISTS idx_funding_announced_at ON funding_round(announced_at);

CREATE TABLE IF NOT EXISTS contact (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    x_handle TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contact_company ON contact(company_id);

CREATE TABLE IF NOT EXISTS dm_draft (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    launch_id INTEGER NOT NULL REFERENCES launch(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    tone TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    prompt_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dm_launch ON dm_draft(launch_id);
