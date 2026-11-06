CREATE INDEX membership_isin_day ON membership(isin, day);
CREATE INDEX membership_code_day ON membership(code, day);
CREATE INDEX actions_isin_effective ON corporate_actions(isin, effective_date);
CREATE VIEW securities AS
SELECT isin, min(day) AS first_seen, max(day) AS last_seen, max(common) AS ever_common
FROM membership GROUP BY isin;
CREATE VIEW execution_bars AS
SELECT p.*, m.code FROM ohlcv p JOIN membership m USING(day, isin) WHERE m.common=1;
CREATE VIEW tradability AS
SELECT day, isin, state AS bar_state, 'UNKNOWN' AS official_halt_status FROM ohlcv;
CREATE VIEW vendor_comparison AS
SELECT p.day, p.isin,
    CASE WHEN v.code IS NULL THEN 'NO_VENDOR_ROW'
         WHEN p.open=v.open AND p.high=v.high AND p.low=v.low AND p.close=v.close
              AND p.volume=v.volume THEN 'EXACT_OHLCV'
         ELSE 'DIFFERENT_OHLCV' END AS status
FROM execution_bars p LEFT JOIN vendor_panel v USING(day, code);
CREATE VIEW large_raw_jumps AS
WITH previous AS (
    SELECT day, isin, close, lag(close) OVER (PARTITION BY isin ORDER BY day) AS prior_close
    FROM execution_bars WHERE state='POSITIVE_VOLUME_VALID_BAR'
)
SELECT * FROM previous WHERE close>prior_close*1.35 OR close<prior_close*0.65;
CREATE VIEW data_quality AS
SELECT day, isin, state AS issue FROM ohlcv WHERE state<>'POSITIVE_VOLUME_VALID_BAR'
UNION ALL
SELECT day, isin, 'RAW_CLOSE_JUMP_REVIEW' FROM large_raw_jumps
UNION ALL
SELECT e.day, NULL, 'MISSING_KRX_SESSION' FROM expected_sessions e
LEFT JOIN sessions s USING(day) WHERE s.day IS NULL;
