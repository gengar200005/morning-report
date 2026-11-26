"""Retrieve original KIND financial statements for an identity-validated list.

From research/v2_pit, run:
python -m stage82b.kind_display INPUT.csv CACHE_DIRECTORY --period-end 2021-03-31

Industry is assigned by the dated universe ledger. Explicitly unavailable consolidated
filings remain in its denominator; standalone-only amounts are exported separately.
"""

import hashlib
import re
import sqlite3
import zlib
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from lxml import html

from dart_receipts import NoRedirect
from public_dart import validate_receipt

ROOT = 'https://kind.krx.co.kr'
BASE = ROOT + '/common/disclsviewer.do?'
MAX_SIZE = 40 * 1024 * 1024


def document_number(raw, receipt, stock_code=None):
    root = html.fromstring(raw.decode('utf-8'))
    if stock_code is not None:
        header = root.xpath('string(//header//h1)')
        codes = re.findall(r'\((\d{6})\)', header)
        if codes != [stock_code]:
            raise ValueError('KIND report viewer belongs to another security')
    printed_date = '.'.join((receipt[:4], receipt[4:6], receipt[6:8]))
    choices = []
    for node in root.xpath('//select[@id="mainDoc"]/option'):
        title = ''.join(node.text_content().split())
        if (not title.startswith(('분기보고서', '반기보고서', '사업보고서'))
                or not title.endswith('(' + printed_date + ')')):
            continue
        if re.fullmatch(r'\d{14}\|[YN]', node.get('value', '')):
            choices.append(node.get('value').split('|')[0])
    if len(choices) != 1:
        raise ValueError('No unambiguous dated original in KIND menu')
    return choices[0]


def contents_url(raw, receipt, document):
    pairs = re.findall(rb"parent\.setPath\('([^']+)','([^']+)'", raw)
    if len(pairs) != 1:
        raise ValueError('Ambiguous KIND document pointer')
    url = pairs[0][1].decode('ascii')
    prefix = f'{ROOT}/external/{receipt[:4]}/{receipt[4:6]}/{receipt[6:8]}/{receipt[8:]}/{document}/'
    if not url.startswith(prefix) or not re.fullmatch(r'1101[1-4]\.htm', url[len(prefix):]):
        raise ValueError('KIND receipt/document mismatch')
    return url


def cached(db, url, parse):
    row = db.execute('SELECT hash,raw FROM page WHERE url=?', (url,)).fetchone()
    if row:
        claimed, packed = row
        raw = zlib.decompress(packed)
        if hashlib.sha256(raw).hexdigest() != claimed:
            raise ValueError('KIND cache hash mismatch')
        return claimed, parse(raw)
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with build_opener(NoRedirect()).open(request, timeout=35) as response:
        raw = response.read(MAX_SIZE + 1)
    if not raw or len(raw) > MAX_SIZE:
        raise ValueError('Empty or oversized KIND payload')
    parsed = parse(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with db:
        updated = db.execute('INSERT OR IGNORE INTO page VALUES (?,?,?)',
                             (url, digest, zlib.compress(raw, 2))).rowcount
    return (digest, parsed) if updated else cached(db, url, parse)


def full_report(cache, row):
    receipt, dart = row['kind_receipt'], row['receipt_candidate']
    validate_receipt(receipt)
    validate_receipt(dart)
    if (row['identity_status'] != 'PASS' or receipt[:8] != dart[:8]
            or row['filing_date'].replace('-', '') != dart[:8]):
        raise ValueError('Expected previously cross-validated original identifiers and date')
    with sqlite3.connect(cache, timeout=60) as db:
        db.execute('CREATE TABLE IF NOT EXISTS page (url TEXT PRIMARY KEY, hash TEXT NOT NULL, raw BLOB NOT NULL)')
        index = BASE + urlencode({'method': 'search', 'acptno': receipt})
        ih, document = cached(db, index, lambda raw: document_number(raw, receipt, row['stock_code']))
        pointer = BASE + urlencode({'method': 'searchContents', 'docNo': document})
        ph, url = cached(db, pointer, lambda raw: contents_url(raw, receipt, document))
        def valid_body(raw):
            tree = html.fromstring(raw.decode('utf-8'))
            if not tree.xpath('//h2[@class="SECTION-1"]|//p[@class="SECTION-1"]'):
                raise ValueError('Incomplete KIND report body')
            return raw
        bh, raw = cached(db, url, valid_body)
    return {'kind_receipt': receipt, 'receipt': dart, 'document': document, 'index_url': index,
            'index_sha256': ih, 'pointer_url': pointer, 'pointer_sha256': ph,
            'source_url': url, 'source_sha256': bh}, raw


def collect_fields(cache, row, period_end, financial=None):
    from stage82b.display_fields import extract_display_fields, no_consolidated_statement

    source, raw = full_report(cache, row)
    cfs = extract_display_fields(raw, 'CFS', period_end, financial)
    explicit = no_consolidated_statement(raw)
    standalone = extract_display_fields(raw, 'OFS', period_end, financial, standalone_confirmed=True) if explicit else None
    return {**source, **cfs, 'stock_code': row['stock_code'], 'isin': row['isin'],
            'corp_code': row['corp_code_candidate'], 'explicit_no_cfs': explicit, 'separate_only': standalone}


def main():
    import argparse
    import csv
    import json
    from pathlib import Path
    from tempfile import NamedTemporaryFile

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('identity_csv', type=Path, help='Previously cross-identified dated originals')
    parser.add_argument('directory', type=Path)
    parser.add_argument('--period-end', required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    cache = args.directory / 'filings.sqlite'
    failures = 0
    with args.identity_csv.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['identity_status'] != 'PASS':
                continue
            receipt = row['kind_receipt']
            try:
                result = collect_fields(cache, row, args.period_end)
            except (OSError, ValueError, sqlite3.Error) as exc:
                failures += 1
                print(receipt, 'BLOCKED', type(exc).__name__, str(exc)[:140])
                continue
            with NamedTemporaryFile('w', dir=args.directory, encoding='utf-8', delete=False) as tmp:
                json.dump(result, tmp, ensure_ascii=False, indent=2)
            Path(tmp.name).replace(args.directory / (receipt + '.json'))
            print(receipt, 'OK')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
