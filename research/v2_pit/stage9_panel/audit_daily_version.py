"""Replay the archived SundO Electric original and changed filing at two actual KRX sessions."""
import argparse
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from pit_facts import extract_receipt
from pit_ledger import filing_versions, normalize, receipt_amounts


def run(manual, register, packages, session_db, output):
    lock=json.loads(manual.read_bytes())
    readings={r['receipt']:r for r in lock['rows'] if r['stock_code']=='007610'}
    targets={'20201116':'20201113000442','20201117':'20201116001901'}
    if set(readings)!=set(targets.values()):raise ValueError('missing independent original or amendment')
    with register.open() as f: histories=normalize(list(csv.DictReader(f)))
    history=histories['KR7007610009']
    with sqlite3.connect('file:'+str(session_db.resolve())+'?mode=ro',uri=True) as db:
        sessions=[r[0] for r in db.execute('SELECT day FROM sessions ORDER BY day')]
    with sqlite3.connect('file:'+str(packages.resolve())+'?mode=ro',uri=True) as raw_db:
        replays=[]
        for session,expected in targets.items():
            if session not in sessions:raise ValueError('not a KRX session')
            chosen,why=filing_versions(history,session,sessions=sessions)
            if why!='PASS' or chosen['receipt']!=expected:raise ValueError((session,why,chosen))
            key=chosen['receipt']
            cache={key:[]}
            sources=[]
            for fmt,dn,h,url,b in raw_db.execute('''SELECT kind,document,sha256,source,body FROM packages p WHERE receipt=?
                    AND NOT EXISTS (SELECT 1 FROM quarantine q WHERE (q.receipt,q.kind)=(p.receipt,p.kind)) ORDER BY kind''',(key,)):
                evidence=extract_receipt(key,dn,chosen['corp_code'],date.fromisoformat(chosen['period_end']).isoformat(),fmt,b,h)
                cache[key].append((dict(corp=chosen['corp_code'],period=chosen['period_end'],doc=dn,kind=fmt,sha=h),evidence))
                sources.append(dict(kind=fmt,sha256=h,url=url))
            actual={}
            for field in ('revenue','operating_profit'):
                pair,_,status=receipt_amounts(cache,chosen,3,field)
                if status!='PASS':raise ValueError((key,field,status))
                actual[field+'_current'],actual[field+'_prior']=pair
            if actual!=readings[key]['manual']:raise ValueError('independent table mismatch')
            replays.append(dict(session=session,receipt=key,kind_receipt=chosen['kind_receipt'],version=chosen['version'],
                                published_kst=chosen['kind_timestamp'],available_session=chosen['available_session'],
                                verified_against_independent_display=True,amounts_KRW=actual,sources=sources))
    out={'scope':'Two daily KRX boundary checks, separate from the 60 original monthly formations and their sample counts.',
         'stock_code':'007610','isin':'KR7007610009','reports':replays,'manual_input_sha256':lock['input_sha256'],
         'revenue_change_current':replays[1]['amounts_KRW']['revenue_current']-replays[0]['amounts_KRW']['revenue_current'],
         'amendment_change_prior_quarter_op_KRW':replays[1]['amounts_KRW']['operating_profit_prior']-replays[0]['amounts_KRW']['operating_profit_prior']}
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('manual','register','packages','session_db','output'):p.add_argument(n,type=Path)
    run(**vars(p.parse_args()))
