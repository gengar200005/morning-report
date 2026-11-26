"""Read CFS monetary facts at exact calendar durations from immutable submitted bytes."""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from lxml.etree import ParserError
from zipfile import BadZipFile, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filing_xbrl import X, NIL, classify, dimensions_match, field_for, parse_instance, unit_kind
from stage82b.display_fields import extract_display_fields, no_consolidated_statement
from stage9_panel.pit_display import cumulative_facts

FIELDS = ('revenue', 'operating_profit')
DURATIONS = (3, 9, 12)
ANNUAL_SUBPERIODS = {'first9': (3,9), 'first6': (6,6), 'first3': (9,3), 'second3': (6,3), 'third3': (3,3)}
FACTS_VERSION = 3


def dates_for(end, months, prior=False):
    year = end.year - prior
    last = date(year, end.month, calendar.monthrange(year, end.month)[1])
    offset = year * 12 + end.month - months
    return (date(offset // 12, offset % 12 + 1, 1).isoformat(), last.isoformat())


def inspect_xbrl(raw, corp, end):
    """One XML pass for each length; avoid treating quarter and YTD contexts alike."""
    if len(raw) > 32 * 1024**2:
        raise ValueError('oversized archive')
    with ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        paths = [m.filename for m in members if m.filename.lower().endswith('.xbrl')]
        if (len(paths) != 1 or len(members) != len(set(archive.namelist()))
                or sum(m.file_size for m in members) > 128 * 1024**2):
            raise ValueError('ambiguous or oversized archive layout')
        instance = archive.read(paths[0])  # ZIP CRC is checked for the extracted instance.
    tree, ns = parse_instance(instance)
    wanted = {dates_for(end, duration, prior): (duration, name) for duration in DURATIONS
              for prior, name in [(False, 'current'), (True, 'prior')]}
    for label, (lag, duration) in ANNUAL_SUBPERIODS.items():
        sub_year, month0 = divmod(end.year * 12 + end.month - 1 - lag, 12)
        sub_month = month0 + 1
        sub_end = date(sub_year, sub_month, calendar.monthrange(sub_year, sub_month)[1])
        for prior, name in [(False, 'current'), (True, 'prior')]:
            wanted[dates_for(sub_end, duration, prior)] = (label, name)
    contexts = {}
    has_cfs = False
    for context in tree.findall(X + 'context'):
        cid = context.get('id')
        ident = context.find(X + 'entity/' + X + 'identifier')
        if not cid or cid in contexts or ident is None or (ident.get('scheme'), ident.text) != ('http://dart.fss.or.kr/ifrs/CIK', corp):
            raise ValueError('invalid or mixed corporate identity/context')
        relevant = None
        if dimensions_match(context, ns):
            has_cfs = True
            interval = tuple(context.findtext(X + 'period/' + X + tag) for tag in ('startDate', 'endDate'))
            relevant = wanted.get(interval)
        contexts[cid] = relevant
    if not contexts:
        raise ValueError('missing XBRL contexts')
    units = {}
    for unit in tree.findall(X + 'unit'):
        uid = unit.get('id')
        if not uid or uid in units:
            raise ValueError('ambiguous unit id')
        units[uid] = unit_kind(unit, ns)
    candidates = defaultdict(list)
    for node in tree:
        when = contexts.get(node.get('contextRef'))
        if when is None:
            continue
        field = field_for(node.tag, set(), corp)
        if field in FIELDS:
            candidates[when, field].append({'tag': node.tag, 'context': node.get('contextRef'),
                'unit': units.get(node.get('unitRef'), 'unknown'), 'raw': node.text,
                'nil': node.get(NIL) in ('true','1'), 'decimals': node.get('decimals')})
    output = {'source_type': 'xbrl', 'instance_sha256': sha256(instance).hexdigest(), 'has_cfs_context': has_cfs}
    for duration in (*DURATIONS, *ANNUAL_SUBPERIODS):
        group = {}
        for field in FIELDS:
            for side in ('current', 'prior'):
                facts = candidates[(duration, side), field]
                validated = classify(facts, field, cumulative=duration != 3)
                value = Decimal(validated['value']) if validated['status'] == 'PASS' else None
                item = {'status': validated['reason']}
                if value is not None and value == value.to_integral_value():
                    item.update(value=int(value), tags=sorted({f['tag'] for f in facts}),
                                contexts=sorted({f['context'] for f in facts}))
                group[field + '_' + side] = item
        output[str(duration)] = group
    return output


def extract_receipt(receipt, document, corp, period_end, kind, raw, expected_hash):
    digest = sha256(raw).hexdigest()
    if expected_hash != digest:
        raise ValueError('immutable payload SHA mismatch')
    end = date.fromisoformat(period_end)
    if end.day != calendar.monthrange(end.year, end.month)[1]:
        raise ValueError('unsupported non-month-end accounting period')
    if kind == 'kind_html':
        display = extract_display_fields(raw, 'CFS', end.isoformat(), None)
        group = {}
        for field, data in display['fields'].items():
            if data.get('observed'):
                for side in ('current', 'prior'):
                    group[field+'_'+side] = {'value': data[side], 'status':'exact_display_quarter',
                        'table':data['table_index'], 'row':data['row_index'], 'columns':data['value_columns'],
                        'unit':data['unit'],'label':data['source_label']}
        result = {'source_type': kind,'3':group,'explicit_no_cfs':not group and no_consolidated_statement(raw)}
        if not result['explicit_no_cfs']:
            for duration in (9,12):
                wanted=tuple(tuple(date.fromisoformat(v) for v in dates_for(end,duration,prior)) for prior in (False,True))
                result[str(duration)]=cumulative_facts(raw,duration,wanted)
    elif kind == 'xbrl':
        result = inspect_xbrl(raw,corp,end)
    else:
        raise ValueError('unsupported payload source')
    return dict(result, receipt=receipt, document=document, corp=corp, period_end=end.isoformat(),
                source_sha256=digest)


def index_facts(packages, receipts, cache):
    """Resume from per-source hash keyed records; financial facts DB is independent of the ledger."""
    import csv
    from xml.etree.ElementTree import ParseError

    with receipts.open(encoding='utf-8-sig', newline='') as f:
        by_receipt = defaultdict(set)
        for r in csv.DictReader(f):
            if r['receipt'] and r['period_end']:
                end=date.fromisoformat(r['period_end']).strftime('%Y%m%d')
                by_receipt[r['receipt']].add((r['corp_code'], end, r.get('document','')))
    indexed = reused = blocked = 0
    with sqlite3.connect(packages.resolve().as_uri()+'?mode=ro', uri=True, timeout=60) as source, sqlite3.connect(cache,timeout=60) as out:
        out.execute('CREATE TABLE IF NOT EXISTS facts(receipt TEXT, kind TEXT, doc TEXT, corp TEXT, period TEXT, sha TEXT, evidence TEXT NOT NULL, PRIMARY KEY(receipt,kind,sha,period))')
        quarantine=set()
        if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='quarantine'").fetchone():
            quarantine=set(source.execute('SELECT receipt,kind FROM quarantine'))
            with out:
                out.executemany('DELETE FROM facts WHERE receipt=? AND kind=?',quarantine)
        # Do not materialize all archives (or hold a read transaction across network fetches).
        for receipt, kind, corp, doc, digest, url in source.execute('SELECT receipt,kind,corp,document,sha256,source FROM packages').fetchall():
            if (receipt,kind) in quarantine:
                continue
            candidates = by_receipt.get(receipt, set())
            periods = {p for c,p,d in candidates if c==corp and p and (kind=='kind_html' or not d or d==doc)}
            if len(periods) != 1:
                continue
            end = periods.pop()
            if out.execute("SELECT 1 FROM facts WHERE receipt=? AND kind=? AND sha=? AND period=? AND json_extract(evidence,'$.facts_version')=?", (receipt,kind,digest,end,FACTS_VERSION)).fetchone():
                reused += 1
                continue
            row = source.execute('SELECT body FROM packages WHERE receipt=? AND kind=? AND sha256=?', (receipt,kind,digest)).fetchone()
            if not row:
                raise ValueError('payload changed during indexing')
            try:
                facts = extract_receipt(receipt,doc,corp,end,kind,row[0],digest)
            except (ValueError, BadZipFile, ParseError, ParserError, UnicodeError, InvalidOperation) as error:
                facts={'source_sha256':digest,'source_type':kind,'error':str(error)}
                blocked += 1
            facts.update(facts_version=FACTS_VERSION,source_url=url)
            with out:
                out.execute('INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?,?,?)',
                            (receipt,kind,doc,corp,end,digest,json.dumps(facts,ensure_ascii=False)))
            indexed += 1
    return {'new':indexed,'reused':reused,'parse_blocked':blocked,'quarantined':len(quarantine)}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packages','receipts','cache'):
        parser.add_argument(name,type=Path)
    print(index_facts(**vars(parser.parse_args())))
