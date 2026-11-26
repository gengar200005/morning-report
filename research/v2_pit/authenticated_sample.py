"""Archive the fixed eight-event OpenDART pilot. No market data or strategy execution.

python authenticated_sample.py PRIVATE_DIRECTORY [--prompt-key]
The SQLite cache retains original API page/ZIP bytes. report.json covers acquisition
and receipt-list identity only. Reconcile financial values before any signal study.
"""
import argparse
from contextlib import closing
from getpass import getpass, GetPassWarning
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile
import warnings
from zipfile import ZipFile

from dart_receipts import archive, listing

# Within each event originals precede their corrections. Single SK releases have no
# corresponding correction in this pinned sample. Categories A/I are queried separately.
SAMPLE = (
    ('00126380', '2021Q1', ('20210517001185',), ('20210407800054','20210429800068')),
    ('00401731', '2021Q1', ('20210517000890',), ('20210407800092','20210429800242')),
    ('00164779', '2021Q1', ('20210517000667',), ('20210428800041',)),
    ('00126380', '2023Q1', ('20230515002335',), ('20230407800208','20230427800066')),
    ('00401731', '2023Q1', ('20230515001288',), ('20230407800596','20230427800323')),
    ('00164779', '2023Q1', ('20230515001677',), ('20230426800003',)),
    ('00790501', '2016Q3', ('20161114002433','20161130001119'), ()),
    ('00159005', '2018Q3', ('20181114002813',), ()),
)


def cached(db, name, fetch):
    found = db.execute('SELECT digest, body FROM archive WHERE name=?', (name,)).fetchone()
    if found is None:
        body = fetch()
        digest = sha256(body).hexdigest()
        with db:
            db.execute('INSERT OR IGNORE INTO archive VALUES (?,?,?)', (name,digest,body))
        found = db.execute('SELECT digest, body FROM archive WHERE name=?', (name,)).fetchone()
    if sha256(found[1]).hexdigest() != found[0]:
        raise ValueError('Cached byte digest mismatch')
    return found


def checked(raw, key):
    if key.encode() in raw:
        raise ValueError('Unexpected response body')
    return raw


def receipt_bytes(key, receipt, xbrl_code):
    if xbrl_code:
        raw = archive(key, 'fnlttXbrl.xml', rcept_no=receipt, reprt_code=xbrl_code)
    else:
        raw = archive(key, 'document.xml', rcept_no=receipt)
    checked(raw,key)
    with ZipFile(BytesIO(raw)) as z:
        names = [entry for entry in z.infolist() if not entry.is_dir()]
        wanted = ('.xbrl',) if xbrl_code else ('.xml','.html','.htm')
        if not any(entry.filename.lower().endswith(wanted) for entry in names):
            raise ValueError('Unexpected archive contents')
        for entry in names:
            checked(z.read(entry),key)
    return raw


def get_rows(db,key,corp,quarter,category):
    yr = quarter[:4]
    start,end = (yr+'0401',yr+'0630') if quarter.endswith('Q1') else (yr+'1001',yr+'1231')
    name = f'{corp}-{category}-{start}-{end}'
    # Save all exact page texts as one transaction so a partial listing is never reused.
    def fetch_pages():
        pages = listing(key,corp,start,end,category)
        return json.dumps([checked(p,key).decode('utf8') for p in pages],ensure_ascii=False).encode()
    digest,body = cached(db, name+'.json', fetch_pages)
    pages = [json.loads(text) for text in json.loads(body)]
    return digest,{r['rcept_no']:r for p in pages for r in p.get('list',[])}


def public_reference():
    path = Path(__file__).with_name('evidence_20261126') / 'pilot_xbrl.json'
    rows = json.loads(path.read_text(encoding='utf8'))
    return {(row['corp'],row['receipt']):row['instance_sha256'] for row in rows}


def instance_comparison(raw, expected):
    if expected is None:
        return {'status':'BLOCKED','reason':'NO_RECEIPT_AND_CORPORATION_REFERENCE'}
    with ZipFile(BytesIO(raw)) as z:
        members = [item for item in z.infolist() if item.filename.lower().endswith('.xbrl')]
        if len(members) != 1:
            return {'status':'BLOCKED','reason':'NO_UNIQUE_INSTANCE','public_sha256':expected}
        actual = sha256(z.read(members[0])).hexdigest()
    return {'status':'PASS' if actual==expected else 'FAIL',
            'public_sha256':expected,'authenticated_sha256':actual}


def run(key, directory):
    if not re.fullmatch(r'[A-Za-z0-9]{40}',key):
        return {'status':'BLOCKED','reason':'OPENDART_API_KEY_MISSING_OR_INVALID_FORMAT','api_called':False}
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    reference = public_reference()
    results,lists = [],[]
    with closing(sqlite3.connect(directory/'api_archive.sqlite3',timeout=30)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS archive (name TEXT PRIMARY KEY,digest TEXT NOT NULL,body BLOB NOT NULL)')
        for corp,quarter,reports,releases in SAMPLE:
            for category,receipts in [('A',reports),('I',releases)]:
                log = {'corp_code':corp,'quarter':quarter,'category':category}
                try:
                    digest, rows = get_rows(db,key,corp,quarter,category)
                    log.update(status='PASS',sha256=digest,listing_rows=len(rows))
                except Exception:
                    # The provider or network stack may include sensitive request data in errors.
                    rows = {}
                    log.update(status='BLOCKED',reason='LIST_OR_CACHE_UNAVAILABLE')
                lists.append(log)
                for i,receipt in enumerate(receipts):
                    rec = dict(corp_code=corp,quarter=quarter,category=category,receipt=receipt,
                               version='correction' if i else 'original',related_original=receipts[0] if i else None)
                    results.append(rec)
                    row = rows.get(receipt,{})
                    title = row.get('report_nm','')
                    type_ok = '분기보고서' in title if category=='A' else '잠정' in title and '실적' in title
                    if (row.get('corp_code')!=corp or row.get('rcept_dt')!=receipt[:8] or
                            not type_ok or ('정정' in title)!=bool(i)):
                        rec.update(status='BLOCKED',reason='LIST_IDENTITY_TYPE_OR_VERSION_UNCONFIRMED')
                        continue
                    rec['files'] = {}
                    formats = [('document',None)]
                    if category=='A':
                        formats.append(('xbrl','11013' if quarter.endswith('Q1') else '11014'))
                    for fmt,code in formats:
                        try:
                            name = f'{receipt}-{fmt}.zip'
                            h,raw = cached(db,name,lambda:receipt_bytes(key,receipt,code))
                            rec['files'][fmt] = {'status':'PASS','sha256':h,'bytes':len(raw),'cache_key':name}
                        except Exception:
                            rec['files'][fmt] = {'status':'BLOCKED','reason':'ENDPOINT_OR_CACHE_UNAVAILABLE'}
                    if category=='A':
                        rec['instance_comparison'] = (
                            instance_comparison(raw,reference.get((corp,receipt)))
                            if rec['files']['xbrl']['status']=='PASS' else {'status':'BLOCKED','reason':'XBRL_UNAVAILABLE'})
                    rec['status'] = 'PASS' if all(v['status']=='PASS' for v in rec['files'].values()) else 'BLOCKED'
    passed = all(r['status']=='PASS' for r in lists+results)
    comparisons = [r.get('instance_comparison',{}).get('status','BLOCKED') for r in results if r['category']=='A']
    matched = all(status=='PASS' for status in comparisons)
    return {'status':'PASS' if passed and matched else 'BLOCKED',
            'acquisition_status':'PASS' if passed else 'BLOCKED',
            'public_instance_matches':comparisons.count('PASS'),'instance_comparisons_expected':len(comparisons),
            'scope':'Receipt-list identity, archived API responses, and exact XBRL instance bytes from two access paths. Financial-field and corpus completeness checks are separate.',
            'listing_windows':lists,'receipts':results}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--prompt-key',action='store_true',help='Read a key from an echo-disabled terminal if the environment has none')
    args=parser.parse_args(argv)
    key=os.environ.get('OPENDART_API_KEY','').strip()
    if args.prompt_key and not key:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',GetPassWarning)
                key=getpass('OpenDART key (hidden): ').strip()
        except (EOFError,GetPassWarning,KeyboardInterrupt,OSError):
            key=''
    try:
        result=run(key,args.output)
        if 'receipts' in result:
            with NamedTemporaryFile('w',dir=args.output,delete=False,encoding='utf8') as f:
                json.dump(result,f,ensure_ascii=False,indent=2)
                tmp=Path(f.name)
            tmp.replace(args.output/'report.json')
        print(json.dumps({k:result[k] for k in ('status','reason','api_called') if k in result}))
    except Exception:
        print('{"status":"BLOCKED","reason":"LOCAL_OUTPUT_OR_CACHE_UNAVAILABLE"}')
        return 2
    return 0 if result['status']=='PASS' else 2


if __name__=='__main__':
    raise SystemExit(main())
