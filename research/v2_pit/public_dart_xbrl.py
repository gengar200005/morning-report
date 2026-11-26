"""Download a receipt-bound Korean XBRL attachment from DART's public download menu."""
import argparse
import hashlib
from http.cookiejar import CookieJar
from io import BytesIO
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
from zipfile import ZipFile

from lxml import html

from public_dart import ROOT, NoRedirect, validate_receipt


def fetch(opener, url, referer=None):
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'}
    if referer:
        headers['Referer'] = referer
    with opener.open(Request(url, headers=headers), timeout=40) as response:
        data = response.read(32 * 1024**2 + 1)
    if len(data) > 32 * 1024**2:
        raise ValueError('Oversized DART response')
    return data


def attachment_path(menu, receipt, document):
    root = html.fromstring(menu.decode('utf-8'))
    choices = set()
    for path in root.xpath('//a[@href]/@href'):
        parts = urlsplit(path)
        if parts.scheme or parts.netloc or parts.path != '/pdf/download/ifrs.do':
            continue
        if parse_qs(parts.query) == {'rcp_no': [receipt], 'dcm_no': [document], 'lang': ['ko']}:
            choices.add(path)
    if len(choices) != 1:
        raise ValueError('Missing or ambiguous receipt-bound Korean XBRL menu entry')
    return choices.pop()


def download_package(receipt):
    validate_receipt(receipt)
    opener = build_opener(NoRedirect(), HTTPCookieProcessor(CookieJar()))
    main_url = ROOT + '/dsaf001/main.do?rcpNo=' + receipt
    main = fetch(opener, main_url)
    tree = html.fromstring(main.decode('utf-8'))
    if not tree.xpath('//option[@selected and @value=$receipt]', receipt='rcpNo=' + receipt):
        raise ValueError('Selected report does not match receipt')
    buttons = tree.xpath('//*[@onclick]/@onclick')
    pattern = re.compile(r"\s*openPdfDownload\('(\d{14})',\s*'(\d+)'\);?\s*")
    matches = (pattern.fullmatch(action) for action in buttons)
    ids = {match[2] for match in matches if match and match[1] == receipt}
    if len(ids) != 1:
        raise ValueError('Missing or ambiguous public attachment document number')
    document = ids.pop()
    menu_url = ROOT + f'/pdf/download/main.do?rcp_no={receipt}&dcm_no={document}'
    menu = fetch(opener, menu_url, main_url)
    file_url = ROOT + attachment_path(menu, receipt, document)
    raw = fetch(opener, file_url, menu_url)
    with ZipFile(BytesIO(raw)) as archive:
        if (sum(item.file_size for item in archive.infolist()) > 128 * 1024**2
                or not any(s.lower().endswith('.xbrl') for s in archive.namelist()) or archive.testzip()):
            raise ValueError('Invalid or oversized XBRL attachment')
    def sha(data):
        return hashlib.sha256(data).hexdigest()
    meta = dict(receipt=receipt, document=document, source=file_url, bytes=len(raw),
                sha256=sha(raw), main_sha256=sha(main), menu_sha256=sha(menu))
    return meta, raw


def package(db, receipt):
    validate_receipt(receipt)
    db.execute('CREATE TABLE IF NOT EXISTS packages(receipt TEXT PRIMARY KEY, meta TEXT NOT NULL, body BLOB NOT NULL)')
    row = db.execute('SELECT meta,body FROM packages WHERE receipt=?', (receipt,)).fetchone()
    if row is None:
        meta, data = download_package(receipt)
        with db:
            db.execute('INSERT OR IGNORE INTO packages VALUES(?,?,?)', (receipt, json.dumps(meta), data))
        return package(db, receipt)
    meta, data = json.loads(row[0]), row[1]
    if meta['receipt'] != receipt or hashlib.sha256(data).hexdigest() != meta['sha256']:
        raise ValueError('XBRL cache integrity error')
    return meta, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('receipts', nargs='+')
    args = parser.parse_args()
    args.directory.mkdir(exist_ok=True, parents=True)
    with sqlite3.connect(args.directory / 'receipt_xbrl.sqlite') as db:
        for receipt in args.receipts:
            meta, data = package(db, receipt)
            # Database is the durable cache. Materialized exports can be recreated from it.
            path = args.directory / (receipt + '.zip')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != meta['sha256']:
                    raise ValueError('Existing XBRL export hash mismatch')
            else:
                with NamedTemporaryFile(dir=args.directory, delete=False) as fp:
                    fp.write(data)
                Path(fp.name).replace(path)
            print(json.dumps(meta), flush=True)


if __name__ == '__main__':
    main()
