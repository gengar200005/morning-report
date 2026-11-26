"""Independent, return-free roster, filing chronology, sign and denominator checks."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

ROSTER='84e5723e32f798a3fa7266c4dba6fa3fb076a014b4b01700077d4540ca369390'


def rows(path):
    with path.open(newline='',encoding='utf-8-sig') as source:
        return list(csv.DictReader(source))


def day(s):
    return s.replace('-','')[:8]


def audit(panel, ledger, versions, db, output):
    if sha256(panel.read_bytes()).hexdigest()!=ROSTER:
        raise ValueError('frozen roster hash changed')
    universe={(r['formation'],r['historical_isin'],r['historical_code']) for r in rows(panel)}
    observed=rows(ledger)
    if len(universe)!=14400 or len(observed)!=14400 or {(r['formation'],r['isin'],r['stock_code']) for r in observed}!=universe:
        raise ValueError('change in roster or ledger duplicate')
    with sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True) as connection:
        sessions=[r[0] for r in connection.execute('SELECT day FROM sessions ORDER BY day')]
    index=defaultdict(list)
    by_receipt={}
    for v in rows(versions):
        if not v.get('filing_date') or not v.get('period_end'):
            continue
        rd=v['receipt'][:8] if re.fullmatch(r'\d{14}',v['receipt']) else ''
        pub=max(day(v['filing_date']),day(v.get('kind_timestamp','')[:10]),rd)
        ver=(day(v['period_end']),pub,v.get('ordering_timestamp',v.get('kind_timestamp','')),v['receipt'],
             v.get('kind_timestamp',''),v.get('dart_timestamp',''))
        index[v['isin']].append(ver)
        if v['receipt']:
            by_receipt[v['isin'],v['receipt']]=ver
    counts=defaultdict(Counter)
    failures=[]
    for r in observed:
        t,isin=r['formation'],r['isin']
        c=counts[t[:4]]
        c['all']+=1
        c['identified']+=int(r['identity_pass'])
        group=r['industry_group']
        c[group]+=1
        for s in ('F2','F3'):
            c[s]+=int(r[s]!='')
        def check(valid,reason):
            if not valid:
                failures.append({'formation':t,'isin':isin,'receipt':r['receipt'],'reason':reason})
        check((r['status']=='PASS')==bool(r['F2'] or r['F3']),'status_vs_amount')
        if r['F2']=='' and r['F3']=='':
            continue
        check(group=='nonfinancial','ineligible_industry')
        check(bool(re.fullmatch(r'[a-f0-9]{64}(\|[a-f0-9]{64})*',r['source_sha256'])),'source_hash_absent')
        ver=by_receipt.get((isin,r['receipt']))
        check(ver is not None,'unknown_receipt')
        if not ver:
            continue
        period,pub=ver[:2]
        check(period==day(r['period_end']) and pub==day(r['filing_date']),'metadata_inconsistent')
        n=bisect_right(sessions,pub)
        check(n<len(sessions) and sessions[n]<=day(r['available_session'])<=t,'availability_or_next_session')
        eligible=[v for v in index[isin] if v[0]<=t and v[1]<t]
        latest=max((v[:2] for v in eligible),default=())
        check(ver[:2]==latest,'newer_period_or_version')
        same=[v for v in eligible if v[:2]==latest]
        if len(same)>1:
            ordering=[v[2] for v in same]
            check(all(s and day(s[:10])==pub for s in ordering)
                  and ordering.count(max(ordering))==1 and ver[2]==max(ordering),'unresolved_version_clock')
            for ix in (4,5):
                stamps=[v[ix] for v in same]
                if all(s and day(s[:10])==pub for s in stamps):
                    check(ver[ix]==max(stamps),'opposed_registry_clock')
        check(0<=(date.fromisoformat(t)-date.fromisoformat(period)).days<=180,'stale_period')
        for detail in json.loads(r['components'] or '{}').values():
            for ref in detail.get('receipts',[]):
                obj=by_receipt.get((isin,ref))
                check(bool(obj and obj[1]<t),'future_or_unidentified_q4_component')
            if detail.get('basis_available_session'):
                check(day(detail['basis_available_session'])<=t,'future_basis_confirmation')
        cur,prior=(Decimal(r[k]) for k in ('revenue_current','revenue_prior'))
        if r['F3']:
            ok=prior>0 and cur>=0
            check(ok and Decimal(r['F3'])==cur/prior-1,'invalid_growth')
        if r['F2']:
            ok=cur>0 and prior>0 and r['operating_profit_current']!='' and r['operating_profit_prior']!=''
            if ok:
                op,prevop=(Decimal(r[k]) for k in ('operating_profit_current','operating_profit_prior'))
                ok=Decimal(r['F2'])==100*(op/cur-prevop/prior)
            check(ok,'invalid_margin_change')
    for c in counts.values():
        for s in ('F2','F3'):
            c[s+'_annual_gate']=bool(c['all']==2880 and c['identified']*10>=c['all']*9 and c['nonfinancial'] and c[s]*5>=c['nonfinancial']*4)
            den=c['nonfinancial']+c['unknown']
            c[s+'_gate_treating_unknown_as_nonfinancial']=bool(c['identified']*10>=c['all']*9 and den and c[s]*5>=den*4)
    out={'roster_sha256':ROSTER,'ledger_sha256':sha256(ledger.read_bytes()).hexdigest(),
         'versions_sha256':sha256(versions.read_bytes()).hexdigest(),'issuer_months':len(observed),
         'by_year':dict(counts),'verified_signal_rows':sum(bool(r['F2'] or r['F3']) for r in observed),
         'failure_count':len(failures),'failures':failures}
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    if failures:
        raise ValueError(f'{len(failures)} discrepancies; see {output}')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('panel','ledger','versions','db','output'):
        p.add_argument('--'+k,required=True,type=Path)
    audit(**vars(p.parse_args()))
