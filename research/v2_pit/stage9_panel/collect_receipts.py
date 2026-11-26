"""Resumable original-receipt collection. Python -m stage9_panel.collect_receipts --help."""
import argparse
import calendar
import csv
import fcntl
import hashlib
import io
import json
import re
import sqlite3
import threading
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener

from lxml import html
from dart_receipts import NoRedirect
from stage82b.kind_display import BASE, contents_url
from stage9_panel.fss_section import statement_pointer

XBRL_URL = 'https://opendart.fss.or.kr/cmm/downloadIfrs.do?'
REFERER = 'https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrl/main.do'
MAX = 40 * 1024 * 1024
LOCK = threading.Lock()
HALT = threading.Event()
next_start = 0.0
RETRYABLE = (408, 425, 429, 500, 502, 503, 504)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS packages(receipt TEXT NOT NULL,document TEXT NOT NULL,corp TEXT NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,sha256 TEXT NOT NULL,body BLOB NOT NULL,PRIMARY KEY(receipt,kind));
CREATE TABLE IF NOT EXISTS reservations(receipt TEXT NOT NULL,kind TEXT NOT NULL,phase TEXT NOT NULL,PRIMARY KEY(receipt,kind));
CREATE TABLE IF NOT EXISTS requests(receipt TEXT,kind TEXT,phase TEXT,step TEXT,url TEXT,started REAL,elapsed REAL,http INTEGER,nbytes INTEGER,status TEXT);
CREATE TABLE IF NOT EXISTS pointers(url TEXT PRIMARY KEY,sha TEXT NOT NULL,body BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS quarantine(receipt TEXT,kind TEXT,reason TEXT,PRIMARY KEY(receipt,kind));
CREATE TABLE IF NOT EXISTS completed(receipt TEXT,kind TEXT,status TEXT,detail TEXT,PRIMARY KEY(receipt,kind));
'''
def connect(path):
    return sqlite3.connect(path, timeout=60)

def initialize(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(SCHEMA)

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))

def sha(body):
    return hashlib.sha256(body).hexdigest()

def store(db, receipt,document,corp,kind,url,body,expected=None):
    digest=sha(body)
    if expected is not None and expected!=digest:
        raise ValueError('source SHA mismatch')
    with db:
        db.execute('INSERT OR IGNORE INTO packages VALUES(?,?,?,?,?,?,?)',(receipt,document,corp,kind,url,digest,body))
        actual=db.execute('SELECT document,corp,sha256 FROM packages WHERE receipt=? AND kind=?',(receipt,kind)).fetchone()
        if actual!=(document,corp,digest):
            raise ValueError('conflicting immutable payload')
    return digest

def check_archive(body):
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        members=z.infolist()
        if not members or sum(v.file_size for v in members)>128*1024*1024 or not any(v.filename.lower().endswith('.xbrl') for v in members):
            raise ValueError('no readable XBRL instance or archive exceeds bound')
        if z.testzip() is not None:
            raise ValueError('XBRL CRC mismatch')

def kind_document(raw,receipt,stock_code,amendment,kind_timestamp=''):
    root=html.fromstring(raw.decode('utf-8'))
    if re.findall(r'\((\d{6})\)',root.xpath('string(//header//h1)'))!=[stock_code]:
        raise ValueError('wrong security in report viewer')
    stamps={'.'.join((receipt[:4],receipt[4:6],receipt[6:8]))}
    # Publication and receipt-prefix dates can differ on a weekend/after hours.
    # Use a second date only from the independent official KRX listing of this event.
    if kind_timestamp:stamps.add(date.fromisoformat(kind_timestamp[:10]).strftime('%Y.%m.%d'))
    hits=[]
    for node in root.xpath('//select[@id="mainDoc"]/option'):
        title=''.join(node.text_content().split())
        report=any(k in title for k in ('분기보고서','반기보고서','사업보고서'))
        desired=('정정' in title) if amendment else title.startswith(('분기보고서','반기보고서','사업보고서'))
        if report and desired and any(title.endswith('('+s+')') for s in stamps) and re.fullmatch(r'\d{14}\|[YN]',node.get('value','')):
            hits.append(node.get('value').split('|')[0])
    if len(hits)!=1:raise ValueError('no unique dated report matching verified KIND publication date')
    return hits[0]

def once(db, row, kind, phase, step, url, interval):
    global next_start
    if step!='body':
        cached=db.execute('SELECT sha,body FROM pointers WHERE url=?',(url,)).fetchone()
        if cached:
            if sha(cached[1])!=cached[0]:raise ValueError('pointer hash mismatch')
            return cached[1]
    headers={'User-Agent':'Mozilla/5.0','Referer':REFERER if kind=='xbrl' else ('https://dart.fss.or.kr/' if kind.startswith('dart_') else 'https://kind.krx.co.kr/')}
    for attempt in range(3):
        if HALT.is_set():raise InterruptedError('public server rate/access signal')
        with LOCK:
            wait=next_start-time.monotonic()
            if wait>0:time.sleep(wait)
            next_start=time.monotonic()+interval
        begin=time.time()
        status=0
        body=b''
        message=''
        try:
            with build_opener(NoRedirect()).open(Request(url,headers=headers),timeout=22) as response:
                status=response.status
                body=response.read(MAX+1)
                if not 0<len(body)<=MAX:raise ValueError('empty or oversized response')
        except HTTPError as exc:
            status=exc.code;message=type(exc).__name__
        except (OSError,ValueError) as exc:
            message=type(exc).__name__
        with db:
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?)',(row['receipt'],kind,phase,step,url,begin,time.time()-begin,status,len(body),message or 'received'))
        if status in (403,429):
            HALT.set()
            raise InterruptedError(f'public server HTTP {status}; stop pending requests')
        if not message:
            if step!='body':
                with db:db.execute('INSERT OR IGNORE INTO pointers VALUES(?,?,?)',(url,sha(body),body))
            return body
        if status and status not in RETRYABLE or attempt==2:
            raise ValueError(f'HTTP {status} {message} at {step}')
        time.sleep(2**(attempt+1))

def fetch(job):
    path,row,kind,phase,interval=job
    if HALT.is_set() or (phase=='full' and (path.parent/'final.stop').exists()):return 'DEFERRED'
    with connect(path) as db:
        rc,corp,doc=row['receipt'],row['corp_code'],row.get('document','')
        try:
            if not re.fullmatch(r'\d{14}',rc) or not re.fullmatch(r'\d{8}',corp):
                raise ValueError('invalid receipt/corp')
            if kind=='xbrl':
                if not re.fullmatch(r'\d{5,10}',doc):raise ValueError('invalid document')
                url=XBRL_URL+urlencode(dict(rcp_no=rc,dcm_no=doc,lang='ko'))
                body=once(db,row,kind,phase,'body',url,interval)
                check_archive(body)
            elif kind in ('dart_html','dart_notes','dart_overview'):
                if not row.get('url'):
                    main='https://dart.fss.or.kr/dsaf001/main.do?'+urlencode({'rcpNo':rc})
                    main_body=once(db,row,kind,phase,'index',main,interval)
                    label,doc,url=statement_pointer(main_body,rc,doc,'notes' if kind=='dart_notes' else 'statement')
                    row=dict(row,url=url,section=label,source_main_sha256=sha(main_body))
                url=row['url'];u=urlsplit(url);params=parse_qs(u.query)
                expected=r'I\.회사의개요' if kind=='dart_overview' else r'\d+\.연결재무제표'+('주석' if kind=='dart_notes' else '')
                if (u.scheme!='https' or u.netloc!='dart.fss.or.kr' or u.path!='/report/viewer.do'
                        or set(params)!= {'rcpNo','dcmNo','eleId','offset','length','dtd'}
                        or params['rcpNo']!=[rc] or params['dcmNo']!=[doc]
                        or not re.fullmatch(r'\d{5,10}',doc)
                        or not re.fullmatch(expected,''.join(row['section'].split()))
                        or not re.fullmatch('[0-9a-f]{64}',row['source_main_sha256'])):
                    raise ValueError('FSS main-to-CFS pointer mismatch')
                body=once(db,row,kind,phase,'body',url,interval)
                try:
                    page=html.fromstring(body.decode('utf-8'))
                except UnicodeDecodeError:
                    page=html.fromstring(body.decode('cp949'))
                headings={''.join(x.split()) for x in page.xpath('//a[@name]/text()')}
                if ''.join(row['section'].split()) not in headings:
                    raise ValueError('FSS viewer heading and main node disagree')
            else:
                kr=row['kind_receipt']
                if not re.fullmatch(r'\d{14}',kr) or not re.fullmatch(r'\d{6}',row['stock_code']):raise ValueError('invalid KIND receipt/security')
                index=BASE+urlencode(dict(method='search',acptno=kr))
                doc=kind_document(once(db,row,kind,phase,'index',index,interval),kr,row['stock_code'],is_amended(row),row.get('kind_timestamp',''))
                pointer=BASE+urlencode(dict(method='searchContents',docNo=doc))
                url=contents_url(once(db,row,kind,phase,'pointer',pointer,interval),kr,doc)
                body=once(db,row,kind,phase,'body',url,interval)
                if not html.fromstring(body.decode('utf-8')).xpath('//h2[@class="SECTION-1"]|//p[@class="SECTION-1"]'):
                    raise ValueError('incomplete KIND body')
            store(db,rc,doc,corp,kind,url,body)
            result='PASS'; detail=''
        except InterruptedError:
            return 'DEFERRED'
        except (OSError,ValueError,zipfile.BadZipFile,UnicodeError) as exc:
            result='BLOCKED';detail=str(exc)[:240]
        with db:db.execute('INSERT OR REPLACE INTO completed VALUES(?,?,?,?)',(rc,kind,result,detail))
        return result

def is_amended(row):
    return row['version'].strip().lower() not in ('original','original_first','원본','최초','최초공시')

def quarter_keys(panel):
    months=defaultdict(list)
    for r in panel:months[r['historical_isin']].append(date.fromisoformat(r['formation']))
    result={}
    for isin,days in months.items():
        for year in range(min(days).year-1,max(days).year+1):
            for m,d in [(3,31),(6,30),(9,30),(12,31)]:
                end=date(year,m,d)
                dates=[j for j in days if 0<=(j-end).days<=180]
                if dates:result[isin,end.isoformat()]=max(dates)
    return result

def plan(manifest,draw,audit,panel,phase):
    rows=[dict(r,period_end=date.fromisoformat(r['period_end']).isoformat()) for r in manifest
          if r.get('identity_status')=='PASS' and r.get('receipt') and r.get('corp_code') and r.get('period_end')]
    pairs={(r['isin'],r['period_end']) for r in draw}
    audits={(r['isin'],r['period_end']) for r in audit}
    jobs=[]
    if phase=='full':
        months=defaultdict(list)
        for member in panel:
            months[member['historical_isin']].append(date.fromisoformat(member['formation']))
        keys={}
        for r in rows:
            key=(r['isin'],r['period_end'])
            if key in keys:continue
            end=date.fromisoformat(key[1])
            days=[d for d in months[key[0]] if 0<=(d-end).days<=180]
            keys[key]=max(days) if days else None
        # Each eligible fiscal year, including September year-ends, needs its own
        # nine-month filing even if that filing predates the normal 180-day window.
        for r in rows:
            key=(r['isin'],r['period_end'])
            if r.get('report_type')!='11011' or not keys.get(key):continue
            end=date.fromisoformat(key[1])
            y,m=divmod(end.year*12+end.month-1-3,12)
            prev=date(y,m+1,calendar.monthrange(y,m+1)[1]).isoformat()
            prior=(key[0],prev)
            keys[prior]=max(keys.get(prior) or keys[key],keys[key])
        for r in rows:
            last=keys.get((r['isin'],r['period_end']))
            if last and r['available_session'] and date.fromisoformat(r['available_session'])<=last:
                jobs.append((r,'xbrl' if r.get('document') else 'kind_html'))
        return jobs
    # The original 84 never change. For ten separate-format audit records and six
    # amendment/support slots, the request cap also counts failed initial requests.
    base=[];checks=[];supp=[];extra_amend=[]
    for r in rows:
        k=(r['isin'],r['period_end'])
        if k in pairs and not is_amended(r):
            base.append((r,'xbrl' if r.get('document') else 'kind_html'))
            if k in audits and r.get('kind_receipt'):checks.append((r,'kind_html'))
        if k in pairs and is_amended(r):extra_amend.append((r,'xbrl' if r.get('document') else 'kind_html'))
        if not is_amended(r) and r['period_end'].endswith('-09-30') and (k[0],k[1][:4]+'-12-31') in audits:
            supp.append((r,'xbrl' if r.get('document') else 'kind_html'))
    sort=lambda v:hashlib.sha256(('stage9-tech-support-v1|'+v[0]['receipt']).encode()).digest()
    return sorted(base,key=sort)+sorted(checks,key=sort)+sorted(supp,key=sort)[:2]+sorted(extra_amend,key=sort)[:4]

def reserve(db,jobs,phase,retry_blocked=False,limit=None):
    seen=set()
    accepted=[]
    with db:
        db.execute('BEGIN IMMEDIATE')
        remaining=100-db.execute("SELECT count(*) FROM reservations WHERE phase='technical'").fetchone()[0]
        for r,k in jobs:
            key=(r['receipt'],k)
            if key in seen:continue
            seen.add(key)
            if db.execute('SELECT 1 FROM packages WHERE receipt=? AND kind=?',key).fetchone():continue
            if not retry_blocked:
                fail=db.execute("SELECT detail FROM completed WHERE receipt=? AND kind=? AND status='BLOCKED'",key).fetchone()
                if fail and fail[0]!='No unambiguous dated original in KIND menu':continue
            held=db.execute('SELECT phase FROM reservations WHERE receipt=? AND kind=?',key).fetchone()
            if not held and phase=='technical' and remaining<=0:continue
            if not held:
                db.execute('INSERT INTO reservations VALUES(?,?,?)',(*key,phase))
                remaining-=1
            accepted.append((r,k))
            if limit is not None and len(accepted)>=limit:break
    return accepted

def collect(path,manifest,draw,audit,panel,phase,workers,interval,retry_blocked,display_queue=None,batch_size=300,kinds=None):
    initialize(path)
    if phase=='full' and (path.parent/'final.stop').exists():
        print('new acquisition frozen');return
    if workers is None:workers=3 if phase=='technical' else 5
    allrows=read_csv(manifest)
    rows=allrows
    if (manifest.parent/'parsed').is_dir():
        # A blank document during a partial portal crawl is not a negative portal result.
        rows=[r for r in rows if r.get('document') or (manifest.parent/'parsed'/
              f"X-{r['stock_code']}-{r['report_type']}.json").is_file()]
    drawrows=read_csv(draw)
    audits=read_csv(audit)
    roster=read_csv(panel)
    sessions_db=panel.parent.parent/'economic.sqlite'
    coverage=manifest.parent/'monthly_coverage.csv'
    industry=panel.parent/'context.csv'
    main=audit.with_name('audit_main_frozen.csv')
    priority_year={}
    if phase=='full' and sessions_db.exists() and coverage.is_file():
        from stage9_panel.collection_targets import target_receipts
        coverage_rows=read_csv(coverage)
        industry_rows=read_csv(industry) if industry.exists() else []
        needed=target_receipts(allrows,roster,sessions_db,coverage_rows,industry_rows,
                               drawrows,audits+(read_csv(main) if main.exists() else []))
        for rank,year in enumerate(('2017','2018','2019','2021','2020')):
            year_targets=target_receipts(allrows,[r for r in roster if r['formation'].startswith(year)],
                                         sessions_db,coverage_rows,industry_rows,[],[])
            for rc in year_targets:priority_year.setdefault(rc,rank)
        jobs=[(r,'xbrl' if r.get('document') else 'kind_html') for r in rows
              if r.get('amendment_scope') not in ('financial_attachment_only','nonfinancial_attachment_only') and (r['identity_status']=='PASS' or r.get('comparator_identity_status')=='PASS') and r['receipt'] in needed]
    else:
        jobs=plan(rows,drawrows,audits,roster,phase)
    if phase=='full':
        # Frozen independent checks need source-diverse row/column evidence.
        main=audit.with_name('audit_main_frozen.csv')
        targets={(r['isin'],r['period_end']) for r in (audits+(read_csv(main) if main.exists() else []))}
        base={(r['isin'],r['period_end']) for r in drawrows}
        from stage9_panel.pit_ledger import prev_end
        annual_checks={(r['isin'],date.fromisoformat(r['period_end']).isoformat()) for r,k in jobs
                       if r['report_type']=='11011'}
        for isin,end in targets & annual_checks:
            for n in (3,12,15):
                targets.add((isin,date.fromisoformat(prev_end(end,n)).isoformat()))
        manual_receipts=set()
        review=panel.parent/'raw'/'audit_display_requests.csv'
        if review.is_file():manual_receipts={r['receipt'] for r in read_csv(review)}
        checks=[]
        for r,k in jobs:
            key=(r['isin'],date.fromisoformat(r['period_end']).isoformat())
            if (key in targets or r['receipt'] in manual_receipts) and r.get('kind_receipt'):
                checks.extend([(r,'kind_html'),(r,k)])
            elif key in base:
                checks.append((r,k))
        # A stable hash interleaves issuers/years during long collections.
        ordered=sorted(jobs,key=lambda j:(priority_year.get(j[0]['receipt'],9),sha(('stage9-full-v1|'+j[0]['receipt']).encode())))
        jobs=checks+ordered
    if phase=='full' and display_queue is not None:
        eligible={r['receipt']:r for r,kind in jobs if r.get('kind_receipt')}
        supplements=[(eligible[r['receipt']],'kind_html') for r in read_csv(display_queue) if r['receipt'] in eligible]
        jobs=checks+supplements+jobs
    if phase=='full':
        # A failed original ZIP can still have the independently identified full
        # KRX rendering of the same dated filing. Both receipts remain attributable.
        with connect(path) as db:
            blocked={r[0] for r in db.execute("SELECT receipt FROM completed WHERE kind='xbrl' AND status='BLOCKED' UNION SELECT receipt FROM quarantine WHERE kind='xbrl'")}
        jobs=[(r,'kind_html') for r,k in jobs if k=='xbrl' and r['receipt'] in blocked and r.get('kind_receipt')]+jobs
    if phase=='full':
        roster_codes={r['historical_code'] for r in roster}
        for filename,kind in (('dart_display_requests.csv','dart_html'),('dart_notes_requests.csv','dart_notes'),('dart_group_overview_requests.csv','dart_overview')):
            review=manifest.parent/filename
            if review.is_file():
                jobs=[(r,kind) for r in read_csv(review) if r['stock_code'] in roster_codes]+jobs
    early=manifest.parent/'technical_download_candidates.csv'
    if phase=='technical' and early.is_file():
        frozen={(r['isin'],r['stock_code'],r['period_end']) for r in read_csv(draw)}
        for r in read_csv(early):
            if ((r['isin'],r['stock_code'],r['period_end']) in frozen and r['document']
                    and r.get('FSS_full_list_hash') and r.get('OpenDART_download_index_hash')):
                jobs.append((r,'xbrl'))
    if phase=='full' and kinds and 'dart_html' in kinds:
        # The alternate display is for the very same verified document. Reuse
        # KRX financial bodies already on disk. Request a second format only
        # for explicitly designated independent reviews.
        with connect(path) as db:
            old_displays={r[0] for r in db.execute("SELECT receipt FROM packages WHERE kind IN ('kind_html','dart_html')")}
        alternate=[(r,'dart_html') for r,k in jobs if k=='kind_html' and r['receipt'] not in old_displays]
        # A partial XBRL directory search can coexist with independently
        # verified DART/KRX identity and a receipt-specific FSS statement.
        if sessions_db.exists() and coverage.is_file():
            alternate.extend((r,'dart_html') for r in allrows if r['receipt'] in needed and not r.get('document')
                and r['receipt'] not in old_displays and r.get('amendment_scope') not in ('financial_attachment_only','nonfinancial_attachment_only') and (r['identity_status']=='PASS' or r.get('comparator_identity_status')=='PASS'))
        manual=[(r,k) for r,k in jobs if k.startswith('dart_') and r.get('url')]
        alternate=sorted(alternate,key=lambda pair:priority_year.get(pair[0]['receipt'],9))
        jobs=manual+alternate+jobs
    notes=panel.parent/'raw'/'audit_note_receipts.csv'
    if phase=='full' and notes.is_file():
        desired={(r['receipt'],r['stock_code']) for r in read_csv(notes)}
        notes_jobs=[(r,'dart_notes') for r in allrows if (r['receipt'],r['stock_code']) in desired and
            (r['identity_status']=='PASS' or r.get('comparator_identity_status')=='PASS') and r['corp_code']]
        # Keep explicitly cross-identified menu coordinates preferred over new index access.
        have={r['receipt'] for r,k in jobs if k=='dart_notes' and r.get('url')}
        jobs=[j for j in notes_jobs if j[0]['receipt'] not in have]+jobs
    xchecks=panel.parent/'raw'/'audit_xbrl_requests.csv'
    if phase=='full' and xchecks.is_file():
        identity_by_id={r['receipt']:r for r in allrows if r['identity_status']=='PASS'}
        review=[]
        for spec in read_csv(xchecks):
            signed=identity_by_id.get(spec['receipt'])
            if not signed or signed['stock_code']!=spec['stock_code'] or signed['report_type']!=spec['report_type']:continue
            stem='X-'+spec['stock_code']+'-'+spec['report_type']
            index=manifest.parent/'parsed'/(stem+'.json')
            if not index.is_file():continue
            matches=[x for x in json.loads(index.read_text())['records'] if x['receipt']==spec['receipt'] and
                     x['corp_code']==signed['corp_code'] and x.get('document')==spec['document']]
            if len(matches)!=1:continue
            if not any(sha(f.read_bytes())==matches[0]['source_sha256'] for f in (manifest.parent/'raw').glob(stem+'-p*.html')):continue
            review.append((dict(signed,document=spec['document']),'xbrl'))
        jobs=review+jobs
    if kinds:jobs=[(r,k) for r,k in jobs if k in kinds]
    with connect(path) as db:accepted=reserve(db,jobs,phase,retry_blocked,batch_size if phase=='full' else None)
    print(f'{phase} planned {len(jobs)} pending {len(accepted)}',flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        totals=Counter()
        for i,status in enumerate(pool.map(fetch,((path,r,k,phase,interval) for r,k in accepted)),1):
            totals[status]+=1
            if i%25==0:print(i,dict(totals),flush=True)
    print(dict(totals),flush=True)
    if HALT.is_set():raise SystemExit('Stopped on public server rate/access response')

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for name in ('path','manifest','draw','audit','panel'):a.add_argument(name,type=Path)
    a.add_argument('phase',choices=('technical','full'))
    a.add_argument('--workers',type=int)
    a.add_argument('--interval',type=float,default=0.65)
    a.add_argument('--retry-blocked',action='store_true')
    a.add_argument('--display-queue',type=Path)
    a.add_argument('--batch-size',type=int,default=300)
    a.add_argument('--kinds',nargs='+',choices=('xbrl','kind_html','dart_html','dart_notes','dart_overview'))
    args=a.parse_args()
    args.path.parent.mkdir(parents=True,exist_ok=True)
    # A concurrent snapshot refresh must never request a second copy of a reserved file.
    with args.path.with_suffix('.collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        collect(**vars(args))
