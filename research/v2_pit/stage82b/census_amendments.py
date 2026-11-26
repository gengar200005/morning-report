"""Compare bounded original/updated quarter reports and build first-next-session intervals."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from collections import defaultdict
from urllib.error import URLError

if __package__:
    from .census_collect import cached_result, portal_file, prepare
else:
    from census_collect import cached_result, portal_file, prepare


def read_csv(path):
    with path.open(encoding='utf8') as f:return list(csv.DictReader(f))


def pair(record, field):
    fs=record.get('fields',{})
    items=[fs.get(t,{}).get(field,{}) for t in ('current','prior_as_reported')]
    if all(f.get('status')=='PASS' for f in items):
        return [f['value'] for f in items]
    return None


def run(identity,filings,index,amended_cache,original_cache,output):
    issuers={r['corp_code_candidate']:r for r in read_csv(identity) if r['identity_status']=='PASS'}
    updates=[r for r in read_csv(filings) if r['corp_code'] in issuers and r['type']!='original']
    by_receipt={r['receipt']:r for r in json.loads(index.read_text())['rows']}
    sessions=json.loads(Path(__file__).with_name('calendar_qc.json').read_text())['sessions']
    evidence_by_receipt={}
    with sqlite3.connect(amended_cache) as db:
        prepare(db)
        for a in updates:
            receipt=a['receipt']
            m=by_receipt.get(receipt)
            if not m or not m.get('document') or m['corp_code']!=a['corp_code'] or m['title'].replace(' ','')!=a['title'].replace(' ',''):
                continue
            cached=db.execute('SELECT sha,evidence,raw FROM originals WHERE receipt=?',(receipt,)).fetchone()
            if cached:
                if hashlib.sha256(cached[2]).hexdigest()!=cached[0]:raise ValueError('Amendment archive integrity error')
                evidence_by_receipt[receipt]=json.loads(cached[1])
                continue
            try:
                raw,url=portal_file(m)
                data=cached_result(m,raw,url)
            except (URLError,ValueError,TimeoutError) as e:
                with db:db.execute('INSERT INTO attempts VALUES(?,?,?)',(receipt,time.time(),str(e)))
                continue
            with db:db.execute('INSERT INTO originals VALUES(?,?,?,?,?,?)',(receipt,m['document'],m['corp_code'],data['archive_sha256'],json.dumps(data,ensure_ascii=False),raw))
            evidence_by_receipt[receipt]=data
            time.sleep(.4)
    with sqlite3.connect(f'file:{original_cache}?mode=ro',uri=True) as db:
        originals={n:json.loads(e) for n,e in db.execute('SELECT receipt,evidence FROM originals')}
    groups=defaultdict(list)
    for a in updates:groups[a['corp_code']].append(a)
    results=[]
    for corp,items in groups.items():
        ident=issuers[corp]
        initial={'receipt':ident['receipt_candidate'],'filed':ident['filing_date'],'type':'original'}
        dated=[]
        for entry in [initial]+items:
            indexed=by_receipt.get(entry['receipt'])
            effective_day=max(entry['filed'],indexed['received'].replace('.','')) if indexed else entry['filed']
            dated.append({**entry,'filed':effective_day})
        series=sorted(dated,key=lambda r:(r['filed'],r['receipt']))
        day_counts={d:sum(entry['filed']==d for entry in series) for d in {t['filed'] for t in series}}
        for i,r in enumerate(series):
            receipt=r['receipt'];filing_day=r['filed']
            next_days=[s for s in sessions if s>filing_day]
            next_date=next_days[0] if next_days else None
            same_day=day_counts[r['filed']]>1
            # With one original and one correction the correction supersedes the filing.
            # Multiple corrections on one day are never ordered using receipt numbers alone.
            statuses=[q['type'] for q in series if q['filed']==r['filed']]
            tie_blocked=same_day and (r['type']=='original' or statuses.count('amendment_or_other')!=1)
            record=originals.get(receipt,{}) if r['type']=='original' else evidence_by_receipt.get(receipt,{})
            later=[q for q in series if q['filed']>r['filed']]
            stop=next((s for s in sessions if s>later[0]['filed']),None) if later else None
            results.append(dict(stock_code=ident['stock_code'],isin=ident['isin'],corp=corp,receipt=receipt,
                         version=r['type'],filed=filing_day,start_session=None if tie_blocked else next_date,
                         stop_session_exclusive=stop,bounded_to='20210630',same_day_quarantined=tie_blocked,
                         sha256=record.get('archive_sha256'),source=record.get('source_url'),revenue=pair(record,'revenue'),
                         operating_profit=pair(record,'operating_profit')))
    month_open={}
    for day in sessions:
        if day <= '20210630':month_open.setdefault(day[:6],day)
    asof=[]
    changes=[]
    for corp, ident in ((c,issuers[c]) for c in groups):
        series=[r for r in results if r['corp']==corp]
        base=next(r for r in series if r['version']=='original')
        for v in series:
            if v['version']=='original':continue
            for f in ('revenue','operating_profit'):
                if base[f] is not None and v[f] is not None and base[f]!=v[f]:
                    changes.append({'original':base['receipt'],'amendment':v['receipt'],'field':f,
                                    'as_original':base[f],'as_amended':v[f]})
        for formation in month_open.values():
            known=[v for v in series if v['start_session'] and v['start_session']<=formation and
                   (v['stop_session_exclusive'] is None or formation<v['stop_session_exclusive'])]
            if len(known)>1:raise ValueError('Overlapping version intervals')
            if known:
                v=known[0]
                asof.append(dict(isin=ident['isin'],formation=formation,receipt=v['receipt'],
                                 version=v['version'],revenue=v['revenue'],operating_profit=v['operating_profit']))
    summary=dict(changed_original_vs_correction=changes,affected_company_month_start_observations=asof,
                 amendments_indexed=len(updates),affected_issuers=len(groups),amendments_obtained=len(evidence_by_receipt),
                 available_signed_pairs=sum(bool(pair(r,'revenue') and pair(r,'operating_profit')) for r in evidence_by_receipt.values()),
                 bounded_version_rows=results)
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print({k:v for k,v in summary.items() if k not in ('bounded_version_rows','changed_original_vs_correction','affected_company_month_start_observations')})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('identity','filings','index','amended_cache','original_cache','output'):p.add_argument(key,type=Path)
    run(**vars(p.parse_args()))
