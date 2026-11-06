"""Cross-check KRX reference returns and build forward-only price momentum."""
import argparse
from collections import deque
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from foundation import MONTHS, digest, stamp
from validate_stage import ANNOUNCED, SAMSUNG


def signed(text):
    token = str(text).replace(',', '').strip()
    return int(token) if re.fullmatch(r'[+-]?[0-9]+', token) else None


def reference_check(close, change, rate):
    try:
        reported = Decimal(rate)
    except (InvalidOperation, TypeError):
        return None, 'MISSING_RATE'
    if not reported.is_finite() or change is None:
        return None, 'MISSING_INPUT'
    reference = close-change
    if reference <= 0:
        return reference, 'NONPOSITIVE_REFERENCE'
    # Compare percentage points with the published two-decimal rounding interval.
    if abs(100*change-reported*reference) > Decimal('.005')*reference:
        return reference, 'RATE_DISAGREES'
    if change and reported and (change>0)!=(reported>0):
        return reference, 'SIGN_DISAGREES'
    return reference, 'PASS'


def advance(history, ordinal, day, isin, close, reference, quality):
    if quality!='PASS':
        history.clear()
        return None,None,None,'UNVERIFIED_KRX_RETURN'
    prior = history[-1] if history else None
    index, reason = 100.0,'ANCHOR'
    if prior:
        prev_ord, _, prev_close, prev_index = prior
        if (isin,day)==SAMSUNG and ANNOUNCED<day and prev_close==reference*50:
            # Keep known factor separate from raw prices. The halt breaks a
            # contiguous 252-session signal window.
            history.clear()
            reason = 'VERIFIED_SPLIT_REANCHOR'
        elif ordinal==prev_ord+1 and reference==prev_close and abs(close-reference)*100<=35*reference:
            index = prev_index*(close/reference)
            reason = 'CONTIGUOUS_RAW_RETURN'
        else:
            history.clear()
            reason = 'UNVERIFIED_LINK_REANCHOR'
    history.append((ordinal,day,close,index))
    lag = history[0] if len(history)==253 else None
    return index,lag[1] if lag else None,index/lag[3]-1 if lag else None,reason


SCHEMA = """
CREATE TABLE krx_return_checks (
    day TEXT, isin TEXT, signed_change INTEGER, fluc_rt TEXT, implied_reference_krw INTEGER,
    rate_status TEXT NOT NULL, PRIMARY KEY(day,isin),
    FOREIGN KEY(day,isin) REFERENCES membership
) WITHOUT ROWID;
CREATE TABLE economic_momentum (
    day TEXT, isin TEXT, price_index REAL, window_start TEXT, momentum_252 REAL,
    link_status TEXT NOT NULL, PRIMARY KEY(day,isin),
    FOREIGN KEY(day,isin) REFERENCES membership
) WITHOUT ROWID;
CREATE TABLE confirmed_price_adjustments (
    day TEXT, isin TEXT, known_before_day TEXT, prior_raw_close_krw INTEGER,
    adjusted_prior_close_krw INTEGER, ratio INTEGER,
    PRIMARY KEY(day,isin), FOREIGN KEY(day,isin) REFERENCES membership
) WITHOUT ROWID;
CREATE VIEW momentum_candidates AS
SELECT m.day,m.isin,m.code,p.price_index,p.window_start,p.momentum_252
FROM economic_momentum p JOIN membership m USING(day,isin)
WHERE m.common=1 AND p.momentum_252 IS NOT NULL;
"""


def candidates(db, signal_day):
    stamp(signal_day)
    return db.execute("""SELECT isin,code,price_index,window_start,momentum_252
        FROM momentum_candidates WHERE day=? ORDER BY isin""",(signal_day,)).fetchall()


def populate(db, archives):
    db.executescript(SCHEMA)
    histories = {}
    dates = []
    for year,month in MONTHS:
        path = archives/f'KRX_PIT_{year}_{month:02d}_v1.json.gz'
        expected, = db.execute('SELECT sha256 FROM provenance WHERE source=?',(path.name,)).fetchone()
        if digest(path)!=expected:
            raise ValueError(f'Archive hash mismatch: {path.name}')
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            records = json.load(stream)['records']
        for record in records:
            day = record['date']
            ordinal = len(dates)
            dates.append(day)
            by_code = {r['ISU_CD']:r for r in record['daily']}
            rows = db.execute("""SELECT p.isin,p.code,p.close,m.name FROM execution_bars p
                JOIN membership m USING(day,isin) WHERE p.day=? AND p.state='POSITIVE_VOLUME_VALID_BAR'""",(day,))
            checks, indexes = [], []
            for isin,code,close,name in rows:
                raw = by_code[code]
                if signed(raw['TDD_CLSPRC'])!=close:
                    raise ValueError('Raw close differs from stage 1.5 database')
                change,rate = signed(raw['CMPPREVDD_PRC']),raw['FLUC_RT']
                reference,status = reference_check(close,change,rate)
                checks.append((day,isin,change,rate,reference,status))
                if '스팩' in name or 'SPAC' in name.upper():
                    histories.pop(isin,None)
                    indexes.append((day,isin,None,None,None,'SPAC_EXCLUDED'))
                    continue
                history = histories.setdefault(isin,deque(maxlen=253))
                prior_close = history[-1][2] if history else None
                index,start,momentum,reason = advance(history,ordinal,day,isin,close,reference,status)
                if reason=='VERIFIED_SPLIT_REANCHOR':
                    db.execute('INSERT INTO confirmed_price_adjustments VALUES (?,?,?,?,?,?)',
                               (day,isin,ANNOUNCED,prior_close,reference,50))
                indexes.append((day,isin,index,start,momentum,reason))
            db.executemany('INSERT INTO krx_return_checks VALUES (?,?,?,?,?,?)',checks)
            db.executemany('INSERT INTO economic_momentum VALUES (?,?,?,?,?,?)',indexes)
        db.commit()
    if dates!=[r[0] for r in db.execute('SELECT day FROM sessions ORDER BY day')]:
        raise ValueError('Session coverage mismatch')
    expected = db.execute("SELECT count(*) FROM execution_bars WHERE state='POSITIVE_VOLUME_VALID_BAR'").fetchone()[0]
    for table in ('krx_return_checks','economic_momentum'):
        if db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]!=expected:
            raise ValueError(f'{table} coverage mismatch')
    return dict(
        checks=dict(db.execute('SELECT rate_status,count(*) FROM krx_return_checks GROUP BY rate_status')),
        signs=dict(db.execute('SELECT sign(signed_change),count(*) FROM krx_return_checks GROUP BY 1')),
        links=dict(db.execute('SELECT link_status,count(*) FROM economic_momentum GROUP BY link_status')),
        eligible=db.execute('SELECT min(day),max(day),count(*),count(DISTINCT isin) FROM momentum_candidates').fetchone(),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('base','krx','output'):
        p.add_argument('--'+flag,type=Path,required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('Output path already exists')
    with tempfile.TemporaryDirectory(dir=args.output.parent) as folder:
        staged = Path(folder)/'db.sqlite'
        source = sqlite3.connect(args.base.resolve().as_uri()+'?mode=ro',uri=True)
        db = sqlite3.connect(staged)
        source.backup(db)
        source.close()
        db.execute('PRAGMA foreign_keys=ON')
        result = populate(db,args.krx)
        if (db.execute('PRAGMA quick_check').fetchone()!=('ok',) or
                db.execute('PRAGMA foreign_key_check').fetchone() is not None):
            raise ValueError('Database integrity check failed')
        db.close()
        staged.replace(args.output)
    result.update(base_sha256=digest(args.base),sha256=digest(args.output))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
