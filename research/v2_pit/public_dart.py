"""Archive dated public DART display pages and their tables for manual PIT review.

python public_dart.py CACHE_DIR RECEIPT [RECEIPT ...]
This is receipt-specific evidence, not authenticated XBRL or an issuer-wide listing.
"""

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from urllib.request import build_opener

from lxml import html

from dart_receipts import NoRedirect

ROOT = 'https://dart.fss.or.kr'
PARAMS = ('rcpNo', 'dcmNo', 'eleId', 'offset', 'length', 'dtd')
CUTOFF = date(2023, 12, 31)
LIMIT = 16 * 1024 * 1024


def validate_receipt(receipt):
    if not re.fullmatch(r'[0-9]{14}', receipt) or date.fromisoformat(receipt[:8]) > CUTOFF:
        raise ValueError('Expected a dated receipt through 2023')


def download(url):
    with build_opener(NoRedirect()).open(url, timeout=35) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Public filing page exceeds the review limit')
    return raw


def cache_init(db):
    db.execute('CREATE TABLE IF NOT EXISTS page (url TEXT PRIMARY KEY, sha TEXT NOT NULL, body BLOB NOT NULL)')


def read_page(db, url, parse):
    """Validate before storing; each complete page is independently resumable."""
    row = db.execute('SELECT sha,body FROM page WHERE url=?', (url,)).fetchone()
    if row:
        digest, raw = row
        if sha256(raw).hexdigest() != digest:
            raise ValueError('Archived page SHA-256 mismatch')
        return digest, parse(raw)
    raw = download(url)
    parsed = parse(raw)
    digest = sha256(raw).hexdigest()
    with db:
        db.execute('INSERT OR IGNORE INTO page VALUES (?,?,?)', (url, digest, raw))
    # Prefer the persisted first observation if a concurrent run got it first.
    if db.execute('SELECT sha FROM page WHERE url=?', (url,)).fetchone()[0] != digest:
        return read_page(db, url, parse)
    return digest, parsed


def main_index(raw, receipt):
    source = raw.decode('utf-8')
    tree = html.fromstring(source)
    selected = tree.xpath('//option[@selected]/@value')
    if 'rcpNo=' + receipt not in selected:
        raise ValueError('Selected filing differs from the requested receipt')
    title = tree.findtext('.//title', '').strip()
    sections = []
    if '분기보고서' in title:
        for block in re.split(r'var node\d+\s*=\s*\{\s*\}\s*;', source)[1:]:
            node = dict(re.findall(r"""node\d+\['(\w+)'\]\s*=\s*"([^"]*)"\s*;""", block))
            label = node.get('text', '')
            if re.fullmatch(r'\d+\.\s*연결재무제표(?:\s*주석)?', label):
                sections.append((label, {k: node[k] for k in PARAMS}))
        kinds = [bool('주석' in label) for label, _ in sections]
        if sorted(kinds) != [False, True]:
            raise ValueError('Ambiguous or missing consolidated statements and notes')
    elif '잠정' in title and '실적' in title:
        for args in re.findall(r'viewDoc\(([^()\n]+)\);', source):
            fields = re.findall(r'"([^"]*)"', args)
            if len(fields) >= len(PARAMS) and fields[0] == receipt:
                sections.append(('잠정실적', dict(zip(PARAMS, fields))))
        if len(sections) != 1:
            raise ValueError('Ambiguous preliminary filing body')
    else:
        raise ValueError('Unsupported filing type')
    for _, params in sections:
        if (params['rcpNo'] != receipt
                or any(not re.fullmatch(r'[0-9]+', params[k]) for k in PARAMS[1:5])
                or not re.fullmatch(r'(?:dart[0-9]*\.xsd|HTML)', params['dtd'])):
            raise ValueError('Invalid receipt-specific viewer coordinates')
    return title, sections


def normalized(text):
    return ' '.join(text.split())


def table_rows(raw, label):
    # Original exchange filings in the display viewer can be encoded in CP949.
    try:
        source = raw.decode('utf-8')
    except UnicodeDecodeError:
        source = raw.decode('cp949')
    tree = html.fromstring(source)
    if label != '잠정실적':
        headings = tree.xpath('//a[@name]/text()')
        if label not in [normalized(s) for s in headings]:
            raise ValueError('Viewer does not contain the requested section heading')
    elif '잠정' not in tree.text_content() or '실적' not in tree.text_content():
        raise ValueError('Viewer does not contain preliminary earnings')
    tables = []
    for table in tree.xpath('//table'):
        rows = []
        for row in table.xpath('./tr|./thead/tr|./tbody/tr|./tfoot/tr'):
            cells = []
            for cell in row.xpath('./td|./th'):
                item = {'text': normalized(cell.text_content())}
                for attr in ('rowspan', 'colspan'):
                    if cell.get(attr):
                        item[attr] = cell.get(attr)
                cells.append(item)
            rows.append(cells)
        if rows:
            previous = table.xpath('preceding-sibling::*[1][self::p]')
            tables.append({'preceding_paragraph': normalized(previous[0].text_content()) if previous else '',
                           'rows': rows})
    if not tables:
        raise ValueError('Requested section has no display tables')
    return tables


def collect(db, receipt):
    validate_receipt(receipt)
    url = ROOT + '/dsaf001/main.do?rcpNo=' + receipt
    digest, (title, sections) = read_page(db, url, lambda raw: main_index(raw, receipt))
    result = {'receipt': receipt, 'source': 'public_dart_display', 'title': title,
              'index_url': url, 'index_sha256': digest, 'sections': []}
    for label, params in sections:
        viewer_url = ROOT + '/report/viewer.do?' + urlencode(params)
        section_hash, tables = read_page(db, viewer_url, lambda raw: table_rows(raw, label))
        result['sections'].append({'section': label, 'url': viewer_url,
                                   'sha256': section_hash, 'tables': tables})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('receipts', nargs='+')
    args = parser.parse_args()
    receipts = list(dict.fromkeys(args.receipts))
    if len(receipts) > 16:
        parser.error('Review a maximum of 16 named pilot receipts per run')
    for receipt in receipts:
        validate_receipt(receipt)
    args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(args.directory / 'pages.sqlite') as db:
        cache_init(db)
        for receipt in receipts:
            result = collect(db, receipt)
            target = args.directory / (receipt + '.json')
            with NamedTemporaryFile('w', encoding='utf-8', dir=args.directory, delete=False) as stream:
                json.dump(result, stream, ensure_ascii=False)
            Path(stream.name).replace(target)
            print(receipt, result['title'], len(result['sections']), 'sections')


if __name__ == '__main__':
    main()
