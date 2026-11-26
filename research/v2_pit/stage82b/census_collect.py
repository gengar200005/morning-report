"""Fetch original 2021Q1 public OpenDART packages matched to the quarter-end census.

Inputs: official receipt/document index JSON and historical security-to-filing crosswalk CSV.
A bounded pool fetches one immutable archive per receipt. The SQLite cache retains checked
raw bytes and receipts together. Later corrections are distinct records and excluded here.
"""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from zipfile import BadZipFile, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filing_xbrl import extract
from public_dart import NoRedirect

PORTAL = 'https://opendart.fss.or.kr'
PRIOR = Path(__file__).resolve().parents[1] / 'evidence_20261126'
MAX_RAW = 32 * 1024**2
FETCH_PAUSE = 0.4

def prior_facts():
    facts = {}
    for file in ('pilot_xbrl.json', 'qc_xbrl.json'):
        for r in json.loads((PRIOR / file).read_text()):
            if r['periods']['current'] == ['2021-01-01', '2021-03-31']:
                facts[r['receipt']] = r
    return facts


def matching_rows(candidates, index):
    originals = {r['receipt']: r for r in index['rows'] if r['document'] and
                 re.fullmatch(r'분기보고서\s*\(2021\.03\)',r['title'])}
    rows = list(csv.DictReader(candidates.open(encoding='utf-8')))
    if len(rows) != 782 or len({r['isin'] for r in rows}) != 782:
        raise ValueError('Expected the complete historical KRX census')
    seen = set()
    matches = []
    for r in rows:
        receipt = r['receipt_candidate']
        m = originals.get(receipt)
        if not m or m['corp_code'] != r['corp_code_candidate']:
            continue
        if receipt in seen:
            raise ValueError('Ambiguous security/receipt match')
        seen.add(receipt)
        matches.append(m)
    return matches


def portal_file(m):
    r, d = m['receipt'], m['document']
    if not re.fullmatch(r'20210[4-6]\d{8}',r) or not d.isdigit():
        raise ValueError('Invalid Q1 receipt/document')
    url = f'{PORTAL}/cmm/downloadIfrs.do?rcp_no={r}&dcm_no={d}&lang=ko'
    headers = {'User-Agent':'Mozilla/5.0', 'Referer':PORTAL+'/disclosureinfo/fnltt/xbrl/main.do'}
    with build_opener(NoRedirect()).open(Request(url,headers=headers), timeout=22) as response:
        raw = response.read(MAX_RAW+1)
    if len(raw) > MAX_RAW or not raw.startswith(b'PK'):
        raise ValueError(f'Invalid ZIP response ({len(raw)} bytes)')
    return raw, url


def cached_result(m, raw, source):
    digest = sha256(raw).hexdigest()
    with ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if (not members or len(members) != len(set(archive.namelist()))
                or sum(f.file_size for f in members) > 128*1024**2 or archive.testzip()):
            raise ValueError('Unexpected archive layout or CRC')
    with TemporaryDirectory() as directory:
        p = Path(directory)/'receipt.zip'
        p.write_bytes(raw)
        try:
            result = extract(p,m['receipt'],m['document'],m['corp_code'],2021,1,digest)
        except (ValueError, BadZipFile, SyntaxError) as e:
            # Keep a valid submitted archive even if this strict parser does not support it.
            result = {'receipt':m['receipt'],'document':m['document'],'corp':m['corp_code'],
                      'archive_sha256':digest,'parser_blocker':str(e),'fields':{}}
    result['source_url'] = source
    return result


def prepare(db):
    db.execute('CREATE TABLE IF NOT EXISTS originals(receipt TEXT PRIMARY KEY, document TEXT NOT NULL, '
               'corp TEXT NOT NULL, sha TEXT NOT NULL, evidence TEXT NOT NULL, raw BLOB NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS attempts(receipt TEXT, happened REAL, status TEXT)')

def run(candidates,index_file,cache,workers,nondec=None):
    matches = matching_rows(candidates,json.loads(index_file.read_text()))
    if nondec:
        for row in json.loads(nondec.read_text())['rows']:
            if row.get('identity')=='PASS' and row.get('statement',{}).get('quarter_only_status')=='PASS':
                m=row['dart']
                if m['title'].replace(' ','')!='반기보고서(2021.03)' or m['receipt'] in {r['receipt'] for r in matches}:
                    raise ValueError('Unexpected non-December receipt')
                matches.append(m)
    known = prior_facts()
    with sqlite3.connect(cache,timeout=20) as db:
        prepare(db)
        saved = {r:(d,c) for r,d,c in db.execute('SELECT receipt,document,corp FROM originals')}
        pending=[]
        for m in matches:
            key=m['receipt']; expected=(m['document'],m['corp_code'])
            if key in known:
                if (known[key]['document'],known[key]['corp']) != expected: raise ValueError('Archived identity changed')
                continue
            if key in saved:
                if saved[key] != expected: raise ValueError('Cache identity changed')
                continue
            pending.append(m)
        print(f'{len(matches)} indexed, {len(pending)} to fetch; previous evidence reused',flush=True)
        lock=Lock()
        next_request=[0.0]
        def worker(m):
            with lock:
                delay = next_request[0] - time.monotonic()
                if delay>0:time.sleep(delay)
                next_request[0]=time.monotonic()+FETCH_PAUSE
            raw,url=portal_file(m)
            return raw,cached_result(m,raw,url)
        errors=0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            group_size=workers*3
            for off in range(0,len(pending),group_size):
                futures={pool.submit(worker,m):m for m in pending[off:off+group_size]}
                upstream=0
                for fut in as_completed(futures):
                    m=futures[fut]; receipt=m['receipt']
                    try:
                        raw,result=fut.result()
                    except (HTTPError, URLError, TimeoutError, ValueError, BadZipFile) as e:
                        status=f'{type(e).__name__}:{e}'
                        errors+=1
                        if isinstance(e,(URLError,TimeoutError)) and getattr(e,'code',503) in (429,500,502,503,504):
                            upstream+=1
                        with db: db.execute('INSERT INTO attempts VALUES(?,?,?)',(receipt,time.time(),status))
                        continue
                    with db:
                        db.execute('INSERT OR IGNORE INTO originals VALUES(?,?,?,?,?,?)',(receipt,m['document'],m['corp_code'],result['archive_sha256'],json.dumps(result,ensure_ascii=False),raw))
                if off//group_size % 5 == 0 or off+group_size>=len(pending):
                    print('progress',min(off+group_size,len(pending)),len(pending),'errors',errors,flush=True)
                if upstream >= max(2,len(futures)//2):
                    print('Widespread upstream failures; progress saved. Retry this command later.',flush=True)
                    break
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('candidates',type=Path);a.add_argument('index_file',type=Path);a.add_argument('cache',type=Path)
    a.add_argument('--nondec',type=Path)
    a.add_argument('--workers',type=int,choices=range(1,9),default=4)
    run(**vars(a.parse_args()))
