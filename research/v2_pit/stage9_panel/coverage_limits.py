"""Upper bounds on annual PIT signal coverage. Read fixed membership, financial facts and ledger only."""
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sqlite3


def read_csv(path):
    raw=path.read_bytes()
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))),sha256(raw).hexdigest()


def market_audit(roster,context):
    selected={(r['formation'],r['historical_isin']):r['historical_code'] for r in roster}
    counts=Counter(d for d,_ in selected)
    expected={f'{y}{m:02}' for y in range(2017,2022) for m in range(1,13)}
    if (len(selected)!=len(roster) or set(counts.values())!={240} or len(counts)!=60
            or {d[:6] for d in counts}!=expected):
        raise ValueError('Different development calendar or frozen sample width')
    whole=defaultdict(list); matched={}
    for r in context:
        d,i=r['formation'],r['isin']; sec=r['sector_code']
        sector_group='financial' if sec=='G40' else 'nonfinancial' if sec else 'unknown'
        if (d not in counts or sec not in ('','G10','G15','G20','G25','G30','G35','G40','G45','G50','G55')
                or sector_group!=r['industry_group'] or r['sampled'] not in ('0','1')
                or ((d,i) in selected)!=(r['sampled']=='1')):
            raise ValueError('Historical classification or sample flag mismatch')
        whole[d].append(r)
        if (d,i) in selected:
            if (d,i) in matched or r['code']!=selected[d,i]:
                raise ValueError('Ambiguous historical security')
            matched[d,i]=r
    if len(context)!=46106 or matched.keys()!=selected.keys():
        raise ValueError('Incomplete market or firm-month map')
    for rows in whole.values():
        if len({r['isin'] for r in rows})!=len(rows):
            raise ValueError('Duplicate historical market row')
        for rank,r in enumerate(sorted(rows,key=lambda r:(int(r['cap_krw']),r['isin']))):
            if int(r['cap_quartile'])!=1+4*rank//len(rows):
                raise ValueError('Full-formation market capitalization rank mismatch')
    return matched


def cfs_proofs(dbpath):
    """Only explicit original display language counts. Reject conflicting source evidence."""
    absent=defaultdict(list); present=set()
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for receipt,kind,doc,corp,period,h,blob in db.execute('SELECT receipt,kind,doc,corp,period,sha,evidence FROM facts'):
            facts=json.loads(blob)
            if facts.get('error') or facts.get('source_sha256')!=h:
                continue
            key=(receipt,corp,period)
            if (kind=='kind_html' and facts.get('explicit_no_cfs') is True and facts.get('3')=={}
                    and facts.get('receipt')==receipt and facts.get('corp')==corp
                    and facts.get('period_end','').replace('-','')==period and facts.get('document')==doc):
                route=re.fullmatch(r'https://kind\.krx\.co\.kr/external/(\d{4})/(\d{2})/(\d{2})/(\d{6})/(\d{14})/[^/]+\.htm(?:l)?',
                                   facts.get('source_url',''),flags=re.I)
                if route and route[5]==doc:
                    absent[key].append((''.join(route.groups()[:4]),h))
            if facts.get('has_cfs_context') is True or any(
                    isinstance(v,dict) and any(isinstance(t,dict) and type(t.get('value')) is int for t in v.values())
                    for v in facts.values()):
                present.add(key)
    return {key:docs for key,docs in absent.items() if key not in present}


def field_class(r,field,proof):
    has_identity=r['identity_pass']=='1' and bool(r['receipt'] and r['original_receipt'] and r['corp_code']
                                                  and r['available_session'] and r['available_session']<=r['formation'])
    verified=[h for k,h in proof.get((r['receipt'],r['corp_code'],r['period_end']),[]) if k and k==r['kind_receipt']]
    if r[field]!='':
        if r[field+'_reason']!='PASS' or not r['source_sha256'] or not has_identity or verified:
            raise ValueError('Numeric signal lacks evidence or conflicts with explicit no-CFS disclosure')
        return 'observed',[]
    if has_identity and verified:
        return 'explicit_no_cfs',verified
    if has_identity and r[field+'_reason'] in ('stale_latest_quarter','not_calendar_quarter_end'):
        return 'verified_period_rule',[]
    if has_identity and r['revenue_source_sha256'] and r['revenue_reason']=='PASS':
        now,prior=Decimal(r['revenue_current']),Decimal(r['revenue_prior'])
        if prior<=0 or (now<=0 if field=='F2' else now<0):
            return 'verified_signal_domain',[]
    if verified:
        return 'index_incomplete_with_explicit_filing',[]
    return 'pending_or_unproven',[]


def ceiling(n,exclusions):
    possible=n-exclusions
    return {'denominator':n,'required':(4*n+4)//5,'hard_exclusions':exclusions,'maximum_observations':possible,
            'maximum_fraction':possible/n if n else None,'impossible_at_80pct':bool(n and 5*possible<4*n)}


def run(roster_path,context_path,ledger_path,quality_path,facts,output):
    roster,roster_sha=read_csv(roster_path); ctx,ctx_sha=read_csv(context_path)
    ledger,ledger_sha=read_csv(ledger_path);quality=json.loads(quality_path.read_bytes())
    if (roster_sha!='84e5723e32f798a3fa7266c4dba6fa3fb076a014b4b01700077d4540ca369390'
            or (roster_sha,ctx_sha,ledger_sha)!=(quality['roster_sha256'],quality['context_sha256'],quality['ledger_sha256'])):
        raise ValueError('Scope or quality summary hashes differ; retry with one ledger snapshot')
    market=market_audit(roster,ctx)
    keys=[(r['formation'],r['isin']) for r in ledger]
    if len(keys)!=len(set(keys)) or set(keys)!=market.keys():
        raise ValueError('Incomplete as-of ledger or duplicated issuer-month')
    verified=cfs_proofs(facts)
    windows=defaultdict(Counter); reasons=defaultdict(Counter); profiles=defaultdict(Counter); support=[]
    for r in ledger:
        d,i=r['formation'],r['isin']; c=market[d,i];y=d[:4];k=r['industry_group']
        if k!=c['industry_group'] or r['stock_code']!=c['code']:raise ValueError('Ledger and historical market context differ')
        a=windows[y];a['total']+=1;a[k]+=1;a['identity']+=int(r['identity_pass']=='1')
        for field in ('F2','F3'):
            profile=profiles[y,k,c['cap_quartile'],field];profile['membership']+=1
            if k!='nonfinancial':continue
            cls,proof=field_class(r,field,verified)
            profile[cls]+=1;a[field+'_'+cls]+=1
            reasons[y,field][r[field+'_reason']]+=1
            if cls=='explicit_no_cfs' and field=='F3':
                support.append(dict(formation=d,isin=i,corp_code=r['corp_code'],receipt=r['receipt'],kind_receipt=r['kind_receipt'],
                                    period_end=r['period_end'],source_sha256=sorted(set(proof))))
    out={}
    for y,a in sorted(windows.items()):
        ref=quality['by_year'][y]
        if (a['total'],a['identity'],a['nonfinancial'],a['unknown'],a['F2_observed'],a['F3_observed'])!=(
                ref['rows'],ref['identity'],ref['nonfinancial'],ref['unknown'],ref['F2'],ref['F3']):
            raise ValueError('Yearly denominator, identity or signal count differs from ledger summary')
        fields={}
        for f in ('F2','F3'):
            n=a['nonfinancial'];u=a['unknown']; blocked=a[f+'_explicit_no_cfs']; period=a[f+'_verified_period_rule'];invalid=a[f+'_verified_signal_domain']
            obs=a[f+'_observed']
            fields[f]={'observed':obs,'current_coverage':obs/n if n else None,'observed_plus_unknown_denominator':obs/(n+u) if n+u else None,
                'structural_only':ceiling(n,blocked),'structural_only_assume_all_unknown_pass':ceiling(n+u,blocked),
                'structural_and_confirmed_rules':ceiling(n,blocked+period+invalid),
                'structural_and_confirmed_rules_assume_all_unknown_pass':ceiling(n+u,blocked+period+invalid),
                'verified_period_rule':period,'verified_signal_domain':invalid,
                'incomplete_index_with_same_no_cfs_document':a[f+'_index_incomplete_with_explicit_filing'],
                'unresolved_maximum_potential_increment':n-blocked-period-invalid-obs,'ledger_reasons':dict(sorted(reasons[y,f].items()))}
        out[y]={'sample':a['total'],'identity':a['identity'],'identity_denominator':a['total'],
                'identity_required_90pct':(9*a['total']+9)//10,'identity_pending_or_unverified':a['total']-a['identity'],
                'financial':a['financial'],'nonfinancial':a['nonfinancial'],'unknown':a['unknown'],'fields':fields}
    result={'scope':'2017–2021; original 60 × 240 draw; observed historical sector and full-market size quartile',
            'ledger_sha256':ledger_sha,'context_sha256':ctx_sha,'metadata_sha256':quality['metadata_sha256'],
            'coverage_sha256':quality['coverage_sha256'],'by_year':out,'confirmed_no_cfs_issuer_months':support,
            'year_sector_size':[dict(year=y,industry=k,full_market_cap_quartile=q,field=f,counts=dict(v)) for (y,k,q,f),v in sorted(profiles.items())]}
    tmp=output.with_suffix(output.suffix+'.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(output)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('roster_path','context_path','ledger_path','quality_path','facts','output'):
        parser.add_argument(key,type=Path)
    run(**vars(parser.parse_args()))
