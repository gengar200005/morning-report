CREATE TABLE jump_review AS
SELECT j.*, s.reported_reference, CASE
    WHEN s.reported_reference=j.prior_close THEN 'SAME_AS_PRIOR_CLOSE'
    WHEN s.reported_reference>0 THEN 'REFERENCE_DIFFERS'
    ELSE 'NO_POSITIVE_REFERENCE' END AS reference_status, CASE
    WHEN s.status='VERIFIED_50_FOR_1' THEN 'VERIFIED_SPLIT_BRIDGE'
    WHEN EXISTS(SELECT 1 FROM corporate_actions a
                WHERE a.isin=j.isin AND a.effective_date=j.day) THEN 'ACTION_EVIDENCE_SAME_DAY'
    WHEN EXISTS(SELECT 1 FROM corporate_actions a
                WHERE a.isin=j.isin AND a.effective_date BETWEEN
                replace(date(substr(j.day,1,4)||'-'||substr(j.day,5,2)||'-'||substr(j.day,7,2),'-7 days'),'-','') AND
                replace(date(substr(j.day,1,4)||'-'||substr(j.day,5,2)||'-'||substr(j.day,7,2),'+7 days'),'-',''))
        THEN 'ACTION_EVIDENCE_NEARBY'
    ELSE 'UNRESOLVED_CAUSE' END AS classification
FROM large_raw_jumps j LEFT JOIN signal_segments s USING(day,isin);
