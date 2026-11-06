PRAGMA foreign_keys=ON;
PRAGMA user_version=1;

CREATE TABLE provenance (
    source TEXT PRIMARY KEY, role TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE expected_sessions (day TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE sessions (
    day TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES provenance
) WITHOUT ROWID;
CREATE TABLE membership (
    day TEXT REFERENCES sessions, isin TEXT, code TEXT NOT NULL, name TEXT NOT NULL,
    listing_date TEXT NOT NULL, group_name TEXT NOT NULL, share_class TEXT NOT NULL,
    common INTEGER NOT NULL CHECK (common IN (0,1)),
    PRIMARY KEY (day, isin), UNIQUE (day, code), CHECK (listing_date<=day)
) WITHOUT ROWID;
CREATE TABLE ohlcv (
    day TEXT, isin TEXT, open INTEGER, high INTEGER, low INTEGER, close INTEGER,
    volume INTEGER, state TEXT NOT NULL, PRIMARY KEY(day, isin),
    FOREIGN KEY (day, isin) REFERENCES membership
) WITHOUT ROWID;
CREATE TABLE vendor_panel (
    day TEXT, code TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (day, code)
) WITHOUT ROWID;
CREATE TABLE corporate_actions (
    source TEXT REFERENCES provenance, event_id TEXT, code TEXT NOT NULL, isin TEXT,
    kind TEXT NOT NULL, status TEXT NOT NULL, announcement_date TEXT, effective_date TEXT,
    record_date TEXT, payment_or_delivery TEXT, terms TEXT NOT NULL,
    PRIMARY KEY (source, event_id)
) WITHOUT ROWID;
-- A separate published signal layer is populated only after PIT continuity is verified.
CREATE TABLE signal_prices (
    day TEXT, isin TEXT, close REAL NOT NULL CHECK(close>0),
    available_day TEXT NOT NULL CHECK(available_day=day),
    source TEXT NOT NULL REFERENCES provenance, PRIMARY KEY(day, isin),
    FOREIGN KEY (day, isin) REFERENCES membership
) WITHOUT ROWID;
