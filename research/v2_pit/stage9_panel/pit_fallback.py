"""Select receipt-bound KIND supplements for imperfect XBRL among actual monthly filings."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sqlite3

if __package__:
    from .pit_ledger import FIELDS, filing_versions, normalize, read_csv, receipt_amounts
else:
    from pit_ledger import FIELDS, filing_versions, normalize, read_csv, receipt_amounts


def fallback_rows(roster, receipts, facts, sessions_db, context=None):
    history = normalize(read_csv(receipts))
    groups = {(r['formation'],r['isin']):r['industry_group'] for r in read_csv(context)} if context else {}
    with sqlite3.connect(sessions_db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        sessions=[r[0] for r in db.execute('SELECT day FROM sessions ORDER BY day')]
    cached=defaultdict(list)
    with sqlite3.connect(facts.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for record in db.execute('SELECT * FROM facts'):
            cached[record['receipt']].append((record,json.loads(record['evidence'])))
    needs={}
    for r in read_csv(roster):
        formation,isin = r['formation'],r['historical_isin']
        if groups.get((formation,isin))=='financial':
            continue
        issuer=history[isin]
        filing,status=filing_versions(issuer,formation,sessions=sessions)
        if status!='PASS' or not filing.get('kind_receipt'):
            continue
        src=cached.get(filing['receipt'],[])
        if {meta['kind'] for meta,_ in src}!={'xbrl'}:
            continue
        why=[]
        for field in FIELDS:
            pair,_,status=receipt_amounts(cached,filing,3,field)
            if pair or status=='source_disagreement':
                continue
            if filing['report_type']=='11011':
                # The full-year route already has the required annual raw value.
                if receipt_amounts(cached,filing,12,field)[0]:
                    continue
            why.append(field+'_missing')
        if why:
            needs[filing['receipt']]=dict(receipt=filing['receipt'],kind_receipt=filing['kind_receipt'],
                kind='kind_html',reason='|'.join(why),stock_code=filing['stock_code'],period_end=filing['period_end'])
    return [needs[k] for k in sorted(needs)]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('roster','receipts','facts','sessions_db','output'):
        parser.add_argument(name,type=Path)
    parser.add_argument('--context',type=Path)
    args=vars(parser.parse_args())
    path=args.pop('output')
    rows=fallback_rows(**args)
    temp=path.with_suffix('.tmp')
    with temp.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['receipt','kind_receipt','kind','reason','stock_code','period_end'])
        writer.writeheader();writer.writerows(rows)
    temp.replace(path)
    print('supplement candidates',len(rows))
