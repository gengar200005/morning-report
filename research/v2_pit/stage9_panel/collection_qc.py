"""Report raw source acquisition, rate and failure outcomes without market results."""
import argparse
import csv
import hashlib
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from stage9_panel.collect_receipts import read_csv
from stage9_panel.pit_facts import extract_receipt

def run(raw,meta,draw,out,include_later=False):
    bykey=defaultdict(list)
    for r in read_csv(meta):
        if r['period_end'] and r['version']=='original':
            bykey[r['isin'],date.fromisoformat(r['period_end']).isoformat()].append(r)
    early=meta.parent/'technical_download_candidates.csv'
    earlyrows={(r['isin'],r['period_end']):r for r in read_csv(early)} if early.is_file() else {}
    statuses=[]
    with sqlite3.connect(raw) as db:
        allcounts=dict(db.execute('SELECT kind,count(*) FROM packages GROUP BY kind'))
        phases={}
        for phase, in db.execute('SELECT DISTINCT phase FROM reservations'):
            event=db.execute('SELECT http,status,nbytes,elapsed,started FROM requests WHERE phase=?',(phase,)).fetchall()
            completed=dict(db.execute('SELECT c.status, count(*) FROM reservations r JOIN completed c USING(receipt,kind) WHERE phase=? GROUP BY c.status',(phase,)))
            new=db.execute('SELECT count(*) FROM reservations WHERE phase=?',(phase,)).fetchone()[0]
            actual=db.execute('SELECT count(*) FROM (SELECT DISTINCT receipt,kind FROM requests WHERE phase=?)',(phase,)).fetchone()[0]
            phases[phase]=dict(distinct_reserved_files=new,distinct_initial_file_attempts=actual,completed=completed,http_requests=len(event),
                               http_results=dict(Counter(str(e[0])+':'+e[1] for e in event)),
                               response_bytes=sum(e[2] for e in event),elapsed_wall_s=(round(max(e[4]+e[3] for e in event)-min(e[4] for e in event),2) if event else 0),
                               median_response_seconds=round(statistics.median(e[3] for e in event),3) if event else None)
        for drawrow in read_csv(draw):
            row=dict(drawrow)
            candidates=[r for r in bykey[row['isin'],row['period_end']] if r['identity_status']=='PASS']
            nr=len(candidates);row.update(identity='PASS' if nr==1 else 'no_unique_indexed_original',receipt='',forms='',direct_3m_pair=0,annual_12m_pair=0,reason='identity unavailable')
            rr=candidates[0] if nr==1 else earlyrows.get((row['isin'],row['period_end']))
            if rr:
                if nr!=1:row['identity']='two_DART_indexes_only_KIND_pending'
                rc=rr['receipt'];row['receipt']=rc;row['reason']='no_original_raw'
                packages=db.execute("""SELECT kind,document,corp,sha256,body FROM packages WHERE receipt=? AND corp=? AND NOT EXISTS (SELECT 1 FROM quarantine q WHERE q.receipt=packages.receipt AND q.kind=packages.kind) AND kind IN ('xbrl','kind_html','dart_html') AND (? OR NOT EXISTS (SELECT 1 FROM reservations v WHERE v.receipt=packages.receipt AND v.kind=packages.kind AND v.phase='full')) ORDER BY kind""",(rc,rr['corp_code'],int(include_later))).fetchall()
                row['forms']=','.join(r[0] for r in packages)
                if packages:row['reason']='CFS exact monetary field/period unavailable'
                for kind,doc,corp,digest,body in packages:
                    try: ev=extract_receipt(rc,doc,corp,row['period_end'],kind,body,digest)
                    except (ValueError,ArithmeticError) as err:
                        row['reason']=str(err);continue
                    for dur,key in [('3','direct_3m_pair'),('12','annual_12m_pair')]:
                        fs=ev.get(dur,{})
                        if all('value' in fs.get(f'{f}_{s}',{}) for f in ['revenue','operating_profit'] for s in ['current','prior']):
                            row[key]=1
                if row['direct_3m_pair']:row['reason']='direct_CFS_two_fields_current_prior'
                elif row['annual_12m_pair']:row['reason']='annual_raw_verified_Q4_needs_matching_9m'
            statuses.append(row)
    def grouped(field):
        data=defaultdict(Counter)
        for r in statuses:
            key=r[field]
            data[key].update({'fixed':1,'unique_original':int(r['identity']=='PASS'),'source_received':int(bool(r['forms'])),
                              'direct_CFS_pair':r['direct_3m_pair'],'annual_CFS_pair':r['annual_12m_pair']})
        return dict(data)
    out.mkdir(exist_ok=True,parents=True)
    file=out/'technical_rows.csv'
    with file.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(statuses[0]));w.writeheader();w.writerows(statuses)
    summary=dict(includes_post_technical_sources=include_later,fixed_draw_sha256=hashlib.sha256(draw.read_bytes()).hexdigest(),audit_rows_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                 generation_meta_sha256=hashlib.sha256(meta.read_bytes()).hexdigest(),all_cached_by_source=allcounts,requests_by_phase=phases,
                 fixed_by_year=grouped('year'),fixed_by_stratum=grouped('stratum'),fixed_by_quarter=grouped('quarter'))
    (out/'collection_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print('summary',allcounts,phases)
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    for key in ('raw','meta','draw','out'):a.add_argument(key,type=Path)
    a.add_argument('--include-later',action='store_true')
    run(**vars(a.parse_args()))
