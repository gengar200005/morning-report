"""Derive point-in-time price segments and audit evidence in a private DB copy."""
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
from datetime import timedelta
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile

from foundation import MONTHS, digest, integer, provenance, stamp

FLOOR = '20160104'
END = '20261030'
# This dated decision and completed listing are both evidenced in the preserved V1 sources.
SAMSUNG = ('KR7005930003', '20180504')
ANNOUNCED = '20180131'


def pit_candidates(db, signal_day, lookback=252):
    """End-of-session inputs only; an observed security must be common that day."""
    stamp(signal_day)
    if lookback < 1:
        raise ValueError('Positive number of preceding sessions required')
    return db.execute("""
        SELECT m.isin, m.code, p.close, p.observations
        FROM membership m JOIN signal_segments p USING(day, isin)
        WHERE m.day=? AND m.common=1 AND p.observations>?
          AND p.status<>'SPAC_EXCLUDED'
        ORDER BY m.isin
    """, (signal_day, lookback)).fetchall()


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def day(text):
    return text.replace('-', '')


def classify_reason(reason):
    if 'SPAC' in reason:
        return 'SPAC'
    if '완전자회사' in reason:
        return 'BUYOUT_OR_EXCHANGE'
    if '해산' in reason:
        return 'DISSOLUTION_OR_MERGER'
    if '신청' in reason:
        return 'VOLUNTARY'
    return 'REGULATORY_OR_OTHER'


def audit_membership(db, metadata):
    paths = {key: metadata / f'{key}_2026-10-30.csv' for key in ('delisting','desc','krx')}
    for path in paths.values():
        provenance(db, path, 'Preserved V1 KRX listing-history snapshot')
    closed = [r for r in read_csv(paths['delisting']) if
              r['Market']=='KOSPI' and (r['SecuGroup'],r['Kind'])==('주권','보통주')
              and FLOOR <= day(r['DelistingDate']) <= END]
    sessions = [r[0] for r in db.execute('SELECT day FROM sessions ORDER BY day')]
    by_code = defaultdict(list)
    for code, isin, when, listing in db.execute(
            'SELECT code, isin, day, listing_date FROM membership WHERE common=1 ORDER BY day'):
        by_code[code].append((isin, when, listing))
    results, stats = [], Counter()
    for r in closed:
        code = r['Symbol']
        start, end = day(r['ListingDate']), day(r['DelistingDate'])
        recorded = [x for x in by_code[code] if start <= x[1] < end]
        observed = {x[1] for x in recorded}
        expected = {d for d in sessions if start <= d < end}
        status = 'MATCH' if observed == expected else ('ABSENT_EPISODE' if not observed else 'DATE_GAPS')
        stats[status] += 1
        isin_set = {x[0] for x in recorded}
        results.append((code, next(iter(isin_set)) if len(isin_set)==1 else None, start, end,
                        r['Reason'], classify_reason(r['Reason']), status, len(expected-observed),
                        max(observed, default=None), r['ArrantEnforceDate'] or None,
                        r['ArrantEndDate'] or None, 'SETTLEMENT_UNVERIFIED'))
    db.executemany('INSERT INTO exit_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', results)
    snapshot = {r['Code']:r['ISU_CD'] for r in read_csv(paths['krx']) if r['Market']=='KOSPI'}
    actual = dict(db.execute('SELECT code,isin FROM membership WHERE day=?', (END,)))
    for code in snapshot.keys() | actual.keys():
        if snapshot.get(code) != actual.get(code):
            db.execute('INSERT INTO listing_discrepancies VALUES (?,?,?,?,?)',
                       (code,END,'ENDPOINT_DIFFERENCE',snapshot.get(code),actual.get(code)))
    matched_isins = {r[1] for r in results}
    for isin, last in db.execute('SELECT isin,last_seen FROM securities WHERE ever_common=1 AND last_seen<?', (END,)):
        if isin not in matched_isins:
            code, = db.execute('SELECT code FROM membership WHERE day=? AND isin=?',(last,isin)).fetchone()
            db.execute('INSERT INTO listing_discrepancies VALUES (?,?,?,?,?)',
                       (code,last,'EXIT_WITHOUT_HISTORY',None,isin))
    for r in read_csv(paths['desc']):
        if r['Market']!='KOSPI' or r['Code'] not in actual:
            continue
        code, listed = r['Code'], day(r['ListingDate'])
        rows = by_code.get(code, [])
        if not rows or not listed:
            continue
        # Listing-date gaps can reflect an earlier listing on a different market.
        # Preserve the discrepancy for independent market-transfer confirmation.
        first, reported = rows[0][1:]
        if listed != reported:
            db.execute('INSERT INTO listing_discrepancies VALUES (?,?,?,?,?)',
                       (code,first,'LISTING_DATE_DIFFERENCE',listed,reported))
        if first>max(FLOOR,listed):
            db.execute('INSERT INTO listing_discrepancies VALUES (?,?,?,?,?)',
                       (code,first,'ENTRY_LATER_THAN_LISTING',listed,first))
        observed = {x[1] for x in rows}
        for missing in (d for d in sessions if max(first,listed)<=d<=END and d not in observed):
            db.execute('INSERT INTO listing_discrepancies VALUES (?,?,?,?,?)',
                       (code,missing,'INTERNAL_COMMON_GAP',listed,reported))
    return stats


def resolution(db):
    rows = db.execute('SELECT source,event_id,code,effective_date,kind,terms FROM corporate_actions WHERE isin IS NULL')
    for source, event, code, effective, kind, payload in rows:
        terms = json.loads(payload)
        reference = effective or terms.get('inventory_date')
        near = []
        # Candidate identity is retrospective evidence and cannot drive signals.
        if reference:
            d = stamp(reference)
            near = db.execute('SELECT DISTINCT isin FROM membership WHERE code=? AND day BETWEEN ? AND ?',
                              (code, (d-timedelta(days=14)).strftime('%Y%m%d'),
                               (d+timedelta(days=14)).strftime('%Y%m%d'))).fetchall()
        ever = db.execute('SELECT 1 FROM membership WHERE code=? LIMIT 1', (code,)).fetchone()
        status = ('NEARBY_ISIN_UNVERIFIED' if len(near)==1 else 'AMBIGUOUS_NEARBY_ISIN' if near
                  else 'NO_NEARBY_PIT_MEMBERSHIP' if ever else 'OUTSIDE_PIT_CODE')
        db.execute('INSERT INTO action_identity_audit VALUES (?,?,?,?,?,?)',
                   (source,event,code,reference,near[0][0] if len(near)==1 else None,status))


def bridge(isin, when, ordinal, close, reference, prior, blocked):
    if close is None:
        return None
    status = 'ANCHOR'
    value, count = 100.0, 1
    if blocked:
        status = 'SPAC_EXCLUDED'
    elif prior:
        prev_ord, prev_close, prev_value, prev_count = prior
        if (isin,when)==SAMSUNG and when>ANNOUNCED and reference and Fraction(prev_close,50)==reference:
            status = 'VERIFIED_50_FOR_1'
        elif ordinal==prev_ord+1 and reference==prev_close and abs(close-reference)*100 <= 35*reference:
            status = 'RAW_PRICE_RETURN'
        else:
            status = 'RESET_UNVERIFIED_REFERENCE_OR_GAP'
        if status in ('VERIFIED_50_FOR_1','RAW_PRICE_RETURN'):
            value, count = prev_value*(close/reference), prev_count+1
    return value, count, status


def signal_segments(db, krx):
    seen = {}
    ordinal = -1
    processed = []
    for year, month in MONTHS:
        path = krx / f'KRX_PIT_{year}_{month:02d}_v1.json.gz'
        sha = db.execute('SELECT sha256 FROM provenance WHERE source=?',(path.name,)).fetchone()
        if sha is None or sha[0]!=digest(path):
            raise ValueError(f'Input hash changed: {path.name}')
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            records = json.load(stream)['records']
        for record in records:
            ordinal += 1
            when = record['date']
            processed.append(when)
            changes = {r['ISU_CD']:integer(r['CMPPREVDD_PRC']) for r in record['daily']}
            rows = db.execute("""SELECT p.isin,p.code,p.close,p.state,m.name
                                 FROM execution_bars p JOIN membership m USING(day,isin)
                                 WHERE p.day=?""", (when,))
            out = []
            for isin, code, close, state, name in rows:
                if state!='POSITIVE_VOLUME_VALID_BAR':
                    continue
                change = changes[code]
                reference = close-change if change is not None else None
                value, count, status = bridge(isin,when,ordinal,close,reference,seen.get(isin),
                                              '스팩' in name or 'SPAC' in name.upper())
                if status!='SPAC_EXCLUDED':
                    seen[isin] = (ordinal,close,value,count)
                else:
                    seen.pop(isin,None)
                out.append((when,isin,value,count,status,reference))
            db.executemany('INSERT INTO signal_segments VALUES (?,?,?,?,?,?)',out)
        db.commit()
    expected = [r[0] for r in db.execute('SELECT day FROM sessions ORDER BY day')]
    if processed != expected:
        raise ValueError('Signal source session coverage mismatch')
    missing = db.execute("""SELECT count(*) FROM execution_bars p
        LEFT JOIN signal_segments s USING(day,isin)
        WHERE p.state='POSITIVE_VOLUME_VALID_BAR' AND s.isin IS NULL""").fetchone()[0]
    if missing:
        raise ValueError(f'Signal diagnostic is missing {missing} valid raw observations')


def audit_bonuses(db):
    results = []
    for isin, code, when, announced, payload in db.execute("""SELECT isin,code,effective_date,
            announcement_date,terms FROM corporate_actions WHERE kind='bonus' ORDER BY effective_date"""):
        terms = json.loads(payload)
        price = db.execute('SELECT reported_reference FROM signal_segments WHERE day=? AND isin=?',
                           (when,isin)).fetchone()
        previous = db.execute("""SELECT p.close FROM membership m JOIN ohlcv p USING(day,isin)
            WHERE m.isin=? AND m.day<? AND p.state='POSITIVE_VOLUME_VALID_BAR'
            ORDER BY m.day DESC LIMIT 1""",(isin,when)).fetchone()
        expected = Fraction(previous[0],1)/(1+Fraction(terms['ratio'])) if previous else None
        results.append(dict(code=code, effective=when, announced=announced,
                            expected_unrounded=float(expected) if expected else None,
                            observed_reference=price[0] if price else None,
                            settlement='PLANNED_DELIVERY_ONLY',
                            signal='WITHHELD_ROUNDING_AND_ECONOMIC_TREATMENT_UNVERIFIED'))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('base','krx','metadata','output'):
        parser.add_argument('--'+flag,type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new private path')
    with tempfile.TemporaryDirectory(dir=args.output.parent) as folder:
        staged = Path(folder)/'staged.sqlite'
        db = sqlite3.connect(staged)
        with sqlite3.connect(args.base.resolve().as_uri()+'?mode=ro',uri=True) as source:
            source.backup(db)
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(Path(__file__).with_name('validation_schema.sql').read_text())
        result = {'base_sha256':digest(args.base),'membership':audit_membership(db,args.metadata)}
        resolution(db)
        signal_segments(db,args.krx)
        db.executescript(Path(__file__).with_name('validation_views.sql').read_text())
        for key,sql in {
            'exit_types': 'SELECT category,count(*) FROM exit_audit GROUP BY category',
            'listing_discrepancies': 'SELECT issue,count(*) FROM listing_discrepancies GROUP BY issue',
            'unresolved_action_identity': 'SELECT status,count(*) FROM action_identity_audit GROUP BY status',
            'signal_segments': 'SELECT status,count(*) FROM signal_segments GROUP BY status',
            'jump_review': 'SELECT classification,count(*) FROM jump_review GROUP BY classification',
            'jump_reference': 'SELECT reference_status,count(*) FROM jump_review GROUP BY reference_status',
        }.items():
            result[key] = dict(db.execute(sql))
        result['bonus_reference_checks'] = audit_bonuses(db)
        result['jumps_in_liquidation_windows'] = db.execute("""SELECT count(*) FROM jump_review j
            WHERE EXISTS (SELECT 1 FROM exit_audit e WHERE e.isin=j.isin
            AND j.day BETWEEN replace(e.liquidation_start,'-','') AND replace(e.liquidation_end,'-',''))""").fetchone()[0]
        result['price_only_252'] = db.execute("""SELECT min(day),max(day),count(*),count(DISTINCT isin)
            FROM signal_segments WHERE observations>252""").fetchone()
        result['exit_gap_days'] = db.execute('SELECT sum(missing_sessions) FROM exit_audit').fetchone()[0]
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',):
            raise ValueError('Database integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('Database foreign key check failed')
        db.commit()
        db.close()
        staged.replace(args.output)
    result['sha256'] = digest(args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
