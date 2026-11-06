CREATE TABLE exit_audit (
    code TEXT, isin TEXT, listed TEXT, delisted TEXT, reason TEXT, category TEXT,
    status TEXT, missing_sessions INTEGER, last_observed TEXT, liquidation_start TEXT,
    liquidation_end TEXT, settlement_status TEXT, PRIMARY KEY(code, delisted)
) WITHOUT ROWID;
CREATE TABLE listing_discrepancies (
    code TEXT, day TEXT, issue TEXT, expected TEXT, observed TEXT,
    PRIMARY KEY(code,day,issue)
) WITHOUT ROWID;
CREATE TABLE action_identity_audit (
    source TEXT, event_id TEXT, code TEXT, reference_day TEXT, candidate_isin TEXT,
    status TEXT, PRIMARY KEY(source,event_id)
) WITHOUT ROWID;
-- Forward price-return diagnostics, distinct from a published total-return signal.
CREATE TABLE signal_segments (
    day TEXT, isin TEXT, close REAL NOT NULL, observations INTEGER NOT NULL,
    status TEXT NOT NULL, reported_reference INTEGER,
    PRIMARY KEY(day,isin), FOREIGN KEY(day,isin) REFERENCES membership
) WITHOUT ROWID;
