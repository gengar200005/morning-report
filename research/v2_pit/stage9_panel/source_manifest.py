"""Write a lossless list of the saved source hashes and audit actual HTTP request totals."""
import argparse
from collections import Counter
import csv
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import statistics

def run(database,directory):
    directory.mkdir(parents=True,exist_ok=True)
    out=directory/'source_manifest.csv'
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=60) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        urls=list(db.execute('SELECT receipt,kind,phase,step,http,status,nbytes,elapsed,started FROM requests ORDER BY started'))
        last={}
        for r in urls:
            if r['step']=='body' and r['status']=='received' and r['phase']!='wrapper_recheck':
                last[r['receipt'],r['kind']]=r['started']
        query="""SELECT p.receipt,p.document,p.corp,p.kind,p.source,p.sha256,length(p.body) AS bytes,
          COALESCE(r.phase,'reused') phase, COALESCE(q.reason,'') AS quarantine FROM packages p
          LEFT JOIN reservations r USING(receipt,kind) LEFT JOIN quarantine q USING(receipt,kind)
          ORDER BY p.receipt,p.kind"""
        rows=[]
        for rec in db.execute(query):
            r=dict(rec)
            stamp=last.get((r['receipt'],r['kind']))
            r['last_recorded_original_http_utc']=datetime.fromtimestamp(stamp,timezone.utc).isoformat() if stamp else ''
            rows.append(r)
        with out.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
        stats={}
        for phase in sorted({r['phase'] for r in urls}):
            requests=[r for r in urls if r['phase']==phase]
            span=max(r['started']+r['elapsed'] for r in requests)-min(r['started'] for r in requests)
            intake=sum(r['phase']==phase for r in rows)
            stats[phase]=dict(http_attempts=len(requests),distinct_file_http_attempts=len({(r['receipt'],r['kind']) for r in requests}),http_status=dict(Counter(str(r['http'])+'/'+r['status'] for r in requests)),
               raw_files_received=intake,body_bytes=sum(r['nbytes'] for r in requests if r['step']=='body'),
               all_http_bytes=sum(r['nbytes'] for r in requests),elapsed_wall_seconds=round(span,3),
               files_per_minute=round(60*intake/span,2) if span>0 else None,
               median_http_seconds=round(statistics.median(r['elapsed'] for r in requests),3))
        missing=[dict(r) for r in db.execute("""SELECT r.receipt,r.kind,r.phase,COALESCE(c.status,'pending') AS status,
            COALESCE(c.detail,'') AS detail FROM reservations r LEFT JOIN completed c USING(receipt,kind)
            LEFT JOIN packages p USING(receipt,kind) WHERE p.receipt IS NULL ORDER BY r.receipt,r.kind""")]
        summary=dict(source_rows=len(rows),distinct_receipts=len({r['receipt'] for r in rows}),total_raw_bytes=sum(r['bytes'] for r in rows),
               original_by_kind=dict(Counter(r['kind'] for r in rows)),quarantined_by_kind=dict(Counter(r['kind'] for r in rows if r['quarantine'])),
               sources_by_phase=dict(Counter(r['phase'] for r in rows)),download_diagnostics=stats,
               unretrieved_by_status=dict(Counter(r['status'] for r in missing)),unretrieved=missing,
               manifest_sha256=sha256(out.read_bytes()).hexdigest())
    (directory/'source_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print('cached',summary['source_rows'],'unretrieved',summary['unretrieved_by_status'])
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('database','directory'):p.add_argument(name,type=Path)
    run(**vars(p.parse_args()))
