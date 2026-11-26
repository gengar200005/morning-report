"""Estimate collection remaining for one frozen year using observed requests, without outcomes."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage9_panel.collection_targets import target_receipts
from stage9_panel.pit_ledger import read_csv


def estimate(root, sessions, year):
    manifest=read_csv(root/'identity/receipts.csv')
    by_receipt={r['receipt']:r for r in manifest if r['receipt']}
    roster=[r for r in read_csv(root/'limited_issuer_months.csv') if r['formation'].startswith(year)]
    if len(roster)!=2880:
        raise ValueError('Expected 12 fixed formations')
    target=target_receipts(manifest,roster,sessions,read_csv(root/'identity/monthly_coverage.csv'),
                           read_csv(root/'context.csv'),[],[])
    with sqlite3.connect((root/'raw/receipts.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        cached={r[0] for r in db.execute("SELECT DISTINCT receipt FROM packages WHERE kind IN ('xbrl','kind_html','dart_html') AND (receipt,kind) NOT IN (SELECT receipt,kind FROM quarantine)")}
        observed=defaultdict(dict)
        for kind,step,count,mean_bytes,seconds in db.execute('SELECT kind,step,count(*),avg(nbytes),avg(elapsed) FROM requests WHERE http=200 GROUP BY kind,step'):
            observed[kind][step]=dict(count=count,mean_bytes=mean_bytes,mean_seconds=seconds)
    remaining=target-cached
    count=Counter('xbrl' if by_receipt[r]['document'] else 'kind_html' for r in remaining)
    requests=0; response_bytes=0; seconds=0
    for kind,n in count.items():
        steps=('body',) if kind=='xbrl' else ('index','pointer','body')
        for step in steps:
            samples=observed.get(kind,{}).get(step,{})
            if not samples:
                raise ValueError(f'No observed cost for {kind} {step}')
            requests+=n; response_bytes+=n*samples['mean_bytes']; seconds+=n*samples['mean_seconds']
    return dict(year=year,all_primary_and_comparator_receipts=len(target),cached_source_receipts=len(target&cached),
                missing_receipts=len(remaining),assumed_source_route=count,measured_http200=observed,
                estimated_http_requests=requests,estimated_response_bytes=round(response_bytes),
                estimated_sum_request_seconds=round(seconds),
                caveats=['Excludes audit extras, data gaps, retries and further Q4 comparability reviews.',
                         'Counts are receipts, not distinct raw-format jobs. Request duration sum is not wall time.'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('sessions',type=Path)
    parser.add_argument('year');parser.add_argument('output',type=Path)
    args=vars(parser.parse_args());output=args.pop('output')
    report=estimate(**args)
    output.write_text(json.dumps(report,indent=2)+'\n')
