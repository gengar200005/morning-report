"""Build the private KOSPI research database from preserved sources."""
import argparse
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).parent
MONTHS = [(y, m) for y in range(2016, 2027)
          for m in range(1, 11 if y == 2026 else 13)]
FIELDS = ('TDD_OPNPRC', 'TDD_HGPRC', 'TDD_LWPRC', 'TDD_CLSPRC', 'ACC_TRDVOL')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{8}', value):
        raise ValueError('Expected YYYYMMDD')
    return date.fromisoformat(value)


def indexed(rows, field):
    result = {}
    for row in rows:
        key = row[field]
        if not re.fullmatch(r'[A-Z0-9]{6}', key) or key in result:
            raise ValueError('Invalid or duplicated short code')
        result[key] = row
    return result


def integer(value):
    token = str(value).replace(',', '')
    return int(token) if re.fullmatch(r'-?[0-9]+', token) else None


def bar_state(op, hi, lo, cl, volume):
    if volume == 0:
        return 'ZERO_VOLUME'
    if None in (op, hi, lo, cl, volume) or volume < 0:
        return 'INVALID_BAR'
    if volume > 0 and 0 < lo <= min(op, cl) <= max(op, cl) <= hi:
        return 'POSITIVE_VOLUME_VALID_BAR'
    return 'INVALID_BAR'


def provenance(db, path, role):
    key = path.name
    db.execute('INSERT INTO provenance VALUES (?,?,?,?)',
               (key, role, digest(path), path.stat().st_size))
    return key


def load_month(db, path, year, month, expected):
    source = provenance(db, path, 'KRX OPEN API v1')
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        doc = json.load(stream)
    if (doc['year'], doc['month'], doc['schema'], doc['source']) != (
            year, month, 1, 'KRX OPEN API'):
        raise ValueError(f'{source}: provenance mismatch')
    sessions = [r['date'] for r in doc['records']]
    if sessions != expected:
        raise ValueError(f'{source}: trading calendar mismatch')
    for record in doc['records']:
        day = record['date']
        basic = indexed(record['basic'], 'ISU_SRT_CD')
        daily = indexed(record['daily'], 'ISU_CD')
        if not basic or basic.keys() != daily.keys():
            raise ValueError(f'{day}: KRX endpoints disagree')
        db.execute('INSERT INTO sessions VALUES (?,?)', (day, source))
        members, prices = [], []
        for code, b in basic.items():
            d = daily[code]
            isin, listed = b['ISU_CD'], b['LIST_DD']
            if (b['MKT_TP_NM'], d['MKT_NM'], d['BAS_DD']) != ('KOSPI', 'KOSPI', day):
                raise ValueError(f'{day}: endpoint market or date mismatch')
            if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]', isin) or stamp(listed) > stamp(day):
                raise ValueError(f'{day}: invalid ISIN or pre-listing row')
            group, kind = b['SECUGRP_NM'], b['KIND_STKCERT_TP_NM']
            common = int((group, kind) == ('주권', '보통주'))
            members.append((day, isin, code, b['ISU_ABBRV'], listed, group, kind, common))
            values = tuple(integer(d[field]) for field in FIELDS)
            prices.append((day, isin, *values, bar_state(*values)))
        db.executemany('INSERT INTO membership VALUES (?,?,?,?,?,?,?,?)', members)
        db.executemany('INSERT INTO ohlcv VALUES (?,?,?,?,?,?,?,?)', prices)


def load_vendor(db, root):
    import pyarrow.parquet as pq

    columns = ['Date', 'Code', 'Market', 'Open', 'High', 'Low', 'Close', 'Volume']
    for path in sorted(root.glob('[0-9][0-9][0-9][0-9].parquet')):
        year = int(path.stem)
        if not 2015 <= year <= 2026:
            raise ValueError('Unexpected vendor year')
        provenance(db, path, 'V1 evidence: Marcap archival snapshot, diagnostic only')
        for batch in pq.ParquetFile(path).iter_batches(columns=columns):
            def rows():
                for r in batch.to_pylist():
                    if r['Market'] != 'KOSPI':
                        continue
                    day = r['Date'].strftime('%Y%m%d')
                    if int(day[:4]) != year:
                        raise ValueError('Vendor partition year mismatch')
                    yield (day, r['Code'], *(r[c] for c in columns[3:]))
            db.executemany('INSERT INTO vendor_panel VALUES (?,?,?,?,?,?,?)', rows())
    history = root / 'history.json'
    if history.exists():
        provenance(db, history, 'V1 evidence: vendor snapshot history')


def load_actions(db, stage, correction):
    for rel, kind in [('corporate/output/ledger.json', 'cash_dividend'),
                      ('review/split_primary_resolutions.json', 'split')]:
        path = stage / rel
        source = provenance(db, path, 'V1 action inventory')
        doc = json.loads(path.read_text())
        for event in doc if kind == 'cash_dividend' else doc['resolutions']:
            verified = event.get('verified', {})
            if kind == 'cash_dividend':
                status = 'V1_ACCOUNT_TERMS'
                effective = event['ex_date']
                payment = event['payment_date']
            else:
                status = 'V1_ACCOUNT_TERMS' if event['replay_ready'] else 'UNRESOLVED'
                effective = verified.get('legal_effective_date')
                payment = None
            reference = effective or event.get('inventory_date')
            matches = db.execute(
                'SELECT DISTINCT isin FROM membership WHERE day=? AND code=?',
                (reference, event['ticker'])).fetchall()
            isin = matches[0][0] if len(matches) == 1 else None
            db.execute('INSERT INTO corporate_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (source, event['event_id'], event['ticker'], isin, kind, status,
                        None, effective, event.get('record_date'), payment,
                        json.dumps(event, ensure_ascii=False, sort_keys=True)))
    if correction:
        source = provenance(db, correction, 'V1 corrected evidence archive')
        with ZipFile(correction) as archive:
            manifest = json.loads(archive.read('final_manifest.json'))
            for name, sha in manifest['files'].items():
                if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                    raise ValueError('V1 corrected evidence manifest mismatch')
        # Source terms are separated from the conditional replay's assumed delivery dates.
        for code, kind, announced, effective, detail in [
            ('107590', 'spin_off_and_conversion', '20170310', '20170501',
             {'parent_ratio': '53/20', 'child_ratio': '147/20', 'child_code': '268280',
              'first_relisting_session': '20170522', 'filing': '20170310000026'}),
            ('002840', 'bonus', '20190228', '20190329',
             {'ratio': '5.4970488', 'planned_delivery': '20190418', 'filing': '20190228000002'}),
            ('002410', 'third_party_allotment', '20200701', None,
             {'ordinary_holder_entitlement': False, 'filing': '20200701000277'}),
            ('185750', 'bonus', '20201217', '20201229',
             {'ratio': '1/20', 'planned_delivery': '20210120', 'filing': '20201217000226'}),
            ('025560', 'bonus', '20230803', '20230817',
             {'ratio': '5', 'planned_delivery': '20230904', 'filing': '20230803000562'}),
        ]:
            # A filing date is day-level provenance, not proof of availability before that close.
            match = db.execute('SELECT isin FROM membership WHERE day=? AND code=?',
                               (announced, code)).fetchone()
            db.execute('INSERT INTO corporate_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (source, detail['filing'], code, match[0] if match else None, kind,
                        'TERMS_CONFIRMED_SETTLEMENT_UNVERIFIED', announced, effective, None,
                        None, json.dumps(detail, sort_keys=True)))


def trading_calendar():
    import exchange_calendars as xc

    cal = xc.get_calendar('XKRX', start='2016-01-01', end='2026-10-30')
    return [d for d in cal.sessions.strftime('%Y%m%d') if d not in ('20260603', '20260717')]


def build(args):
    args.output.parent.mkdir(parents=True, exist_ok=True)
    calendar = trading_calendar()
    missing = []
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temp:
        staged = Path(temp) / 'foundation.sqlite'
        with sqlite3.connect(staged) as db:
            db.executescript((ROOT / 'schema.sql').read_text())
            for year, month in MONTHS:
                prefix = f'{year}{month:02}'
                path = args.krx / f'KRX_PIT_{year}_{month:02}_v1.json.gz'
                if not path.is_file():
                    missing.append(prefix)
                    continue
                load_month(db, path, year, month, [d for d in calendar if d.startswith(prefix)])
            if len(missing) == len(MONTHS) or (missing and not args.allow_partial):
                raise ValueError(f'Missing KRX months: {missing}')
            db.executemany('INSERT INTO expected_sessions VALUES (?)', [(d,) for d in calendar])
            if args.vendor:
                load_vendor(db, args.vendor)
            if args.actions:
                load_actions(db, args.actions, args.correction)
            db.executescript((ROOT / 'views.sql').read_text())
            report = audit(db, missing)
            if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise ValueError('SQLite integrity check failed')
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('SQLite foreign key check failed')
        db.close()
        staged.replace(args.output)
    report['database_sha256'] = digest(args.output)
    return report


def audit(db, missing):
    def one(sql):
        return db.execute(sql).fetchone()[0]

    status = dict(db.execute('SELECT state, count(*) FROM execution_bars GROUP BY state'))
    return {
        'missing_months': missing,
        'sessions': db.execute('SELECT count(*), min(day), max(day) FROM sessions').fetchone(),
        'official_rows': one('SELECT count(*) FROM membership'),
        'common_rows': sum(status.values()),
        'common_isins': one('SELECT count(*) FROM securities WHERE ever_common=1'),
        'common_codes': one('SELECT count(DISTINCT code) FROM membership WHERE common=1'),
        'raw_bar_states': status,
        'code_reuse': one('SELECT count(*) FROM (SELECT code FROM membership GROUP BY code HAVING count(DISTINCT isin)>1)'),
        'isin_code_changes': one('SELECT count(*) FROM (SELECT isin FROM membership GROUP BY isin HAVING count(DISTINCT code)>1)'),
        'common_last_seen_before_endpoint': one(
            'SELECT count(*) FROM securities WHERE ever_common=1 AND last_seen<(SELECT max(day) FROM sessions)'),
        'vendor_comparison': dict(db.execute('SELECT status,count(*) FROM vendor_comparison GROUP BY status')),
        'vendor_2015_sessions': one("SELECT count(DISTINCT day) FROM vendor_panel WHERE day<'20160101'"),
        'warmup_252_exact_identity_verified': 0,
        'large_raw_close_jumps': one('SELECT count(*) FROM large_raw_jumps'),
        'verified_signal_rows': one('SELECT count(*) FROM signal_prices'),
        'action_rows': {'|'.join(key): count for *key, count in db.execute(
            'SELECT kind,status,count(*) FROM corporate_actions GROUP BY kind,status')},
        'action_isin_unresolved': one('SELECT count(*) FROM corporate_actions WHERE isin IS NULL'),
        'cash_payment_terms': one("SELECT count(*) FROM corporate_actions WHERE kind='cash_dividend' AND payment_or_delivery IS NOT NULL"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--krx', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vendor', type=Path)
    parser.add_argument('--actions', type=Path)
    parser.add_argument('--correction', type=Path)
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    if args.correction and not args.actions:
        parser.error('--correction requires --actions')
    if args.output.suffix != '.sqlite' or args.output.exists():
        parser.error('Use a new .sqlite output path outside the source tree')
    print(json.dumps(build(args), indent=2))


if __name__ == '__main__':
    main()
