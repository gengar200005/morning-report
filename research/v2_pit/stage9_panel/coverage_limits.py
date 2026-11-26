"""Upper bounds on annual PIT signal coverage. Read fixed membership, financial facts and ledger only."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sqlite3
from lxml import html


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


def other_exclusions(identity, ledger, quality):
    """Recheck complete negative searches and legal formation dates against archived metadata."""
    extra={}
    cover,cover_sha=read_csv(identity/'monthly_coverage.csv')
    cover={(r['formation'],r['isin']):r for r in cover}
    empty_codes={r['stock_code'] for r in ledger if r['F3_reason']=='no_available_periodic_report'}
    kind_dates=defaultdict(set)
    for f in (identity/'parsed').glob('K*-p*.json') if empty_codes else ():
        for v in json.loads(f.read_bytes())['records']:
            if v['stock_code'] in empty_codes:
                kind_dates[v['stock_code']].add(v['kind_timestamp'][:10].replace('-',''))
    legal={}
    proof=identity/'prelisting_proof.json'
    for r in json.loads(proof.read_bytes()) if proof.is_file() else ():
        if not r.get('established'):continue
        reg=(identity/'raw'/('ipo-'+r['stock_code']+'-corp.html')).read_bytes()
        if sha256(reg).hexdigest()!=r['registry_sha256']:raise ValueError('Changed legal establishment evidence')
        tree=html.fromstring(reg.decode())
        values={''.join(cell.text_content().split()):''.join(cell.getnext().text_content().split())
                for cell in tree.xpath('//tr/th[following-sibling::*[1][self::td]]')}
        if (re.sub(r'\D','',values.get('설립일','')),values.get('종목코드'))!=(r['established'],r['stock_code']):
            raise ValueError('Registry date or stock code mismatch')
        for note in r['official_listing']:
            raw=(identity/'raw'/('transfer-'+note['kind']+'.htm')).read_bytes()
            if sha256(raw).hexdigest()!=note['body_sha256']:raise ValueError('Changed listing notice')
            if r['isin'].encode('ascii') in raw:
                legal[r['isin'],r['corp_code']]={'established':r['established'],'notice_date':note['date'][:10].replace('-',''),
                    'stock_code':r['stock_code'],'registry_sha256':r['registry_sha256'],'listing_sha256':note['body_sha256']}
    dates={}
    for row in ledger:
        d,isin=row['formation'],row['isin']; co=row['stock_code']; key=d,isin
        src=legal.get((isin,row['corp_code']))
        if (src and src['stock_code']==co and src['notice_date']<d and row['identity_pass']=='1' and row['period_end']
                and row.get('comparison_basis_status')=='BLOCKED'):
            last=date.fromisoformat(row['period_end'])
            # The first day of the required three-month comparator is 14 months before the fiscal end month.
            year,month=divmod(12*last.year+last.month-1-14,12)
            prior_start=f'{year:04d}{month+1:02d}01'
            if src['established']>prior_start:
                extra[key]=('confirmed_issuer_not_established',dict(src,receipt=row['receipt'],prior_quarter_start=prior_start))
        elif row['F3_reason']=='no_available_periodic_report' and not row['receipt']:
            c=cover.get(key,{})
            if (cover_sha!=quality['coverage_sha256'] or c.get('stock_code')!=co or
                    not all(c.get(f)=='1' for f in ('complete','kind_window_complete','full_dart_list','corp_identity_evidenced'))):
                continue
            if co not in dates:
                source=identity/'parsed'/('D-'+co+'-ALL.json')
                if not source.is_file():continue
                data=json.loads(source.read_bytes())
                if data['code']!=co or data['count']!=len(data['records']):continue
                for j,h in enumerate(data['hashes'],1):
                    raw=(identity/'raw'/f'D-{co}-ALL-p{j}.html').read_bytes()
                    if sha256(raw).hexdigest()!=h:raise ValueError('Changed full DART receipt index')
                dates[co]=data
            data=dates[co]; earliest=(date.fromisoformat(d)-timedelta(days=180)).strftime('%Y%m%d')
            has_dart=any(earliest<=v['filing_date']<d for v in data['records'])
            has_kind=any(earliest<=seen<d for seen in kind_dates[co])
            if data['start']<=earliest and data['end']>=d and not (has_dart or has_kind):
                extra[key]=('complete_search_no_periodic_report',dict(start=earliest,before_formation=d,
                    full_dart_sha256=data['hashes'],complete_kind_and_dart_scope_sha256=cover_sha))
    return extra


def field_class(r,field,proof,extra=None):
    has_identity=r['identity_pass']=='1' and bool(r['receipt'] and r['original_receipt'] and r['corp_code']
                                                  and r['available_session'] and r['available_session']<=r['formation'])
    verified=[h for k,h in proof.get((r['receipt'],r['corp_code'],r['period_end']),[]) if k and k==r['kind_receipt']]
    if r[field]!='':
        if r[field+'_reason']!='PASS' or not r['source_sha256'] or not has_identity or verified or extra:
            raise ValueError('Numeric signal lacks evidence or conflicts with explicit no-CFS disclosure')
        return 'observed',[]
    if has_identity and verified:
        return 'explicit_no_cfs',verified
    if extra:
        return extra[0],[]
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


def minimum_uncached_receipts(n,hard,uncached):
    """All unclassified monthly cases and all cached receipts succeed for free."""
    required=(4*n+4)//5
    free=n-hard-sum(uncached.values())
    remaining=max(0,required-free)
    needed=0
    fit=0
    for months in sorted(uncached.values(),reverse=True):
        if fit>=remaining:break
        fit+=months;needed+=1
    return dict(observations_required=required,free_success_assumption=free,issuer_months_not_free=sum(uncached.values()),
                distinct_uncached_latest_receipts=len(uncached),additional_issuer_months_needed=remaining,
                minimum_uncached_latest_receipts=needed if fit>=remaining else None)


def run(roster_path,context_path,ledger_path,quality_path,facts,output,identity=None,packages=None):
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
    identity=identity or roster_path.parent/'identity'
    extra=other_exclusions(identity,ledger,quality) if (identity/'monthly_coverage.csv').is_file() else {}
    packages=packages or roster_path.parent/'raw'/'receipts.sqlite'
    cached=None
    if packages.is_file():
        with sqlite3.connect(packages.resolve().as_uri()+'?mode=ro',uri=True) as db:
            cached={r[0] for r in db.execute('SELECT DISTINCT receipt FROM packages')}
        with sqlite3.connect(facts.resolve().as_uri()+'?mode=ro',uri=True) as db:
            cached.update(r[0] for r in db.execute('SELECT DISTINCT receipt FROM facts'))
    uncached=defaultdict(Counter)
    windows=defaultdict(Counter); reasons=defaultdict(Counter); profiles=defaultdict(Counter); support=[]
    for r in ledger:
        d,i=r['formation'],r['isin']; c=market[d,i];y=d[:4];k=r['industry_group']
        if k!=c['industry_group'] or r['stock_code']!=c['code']:raise ValueError('Ledger and historical market context differ')
        a=windows[y];a['total']+=1;a[k]+=1;a['identity']+=int(r['identity_pass']=='1')
        for field in ('F2','F3'):
            profile=profiles[y,k,c['cap_quartile'],field];profile['membership']+=1
            if k!='nonfinancial':continue
            cls,proof=field_class(r,field,verified,extra.get((d,i)))
            if (cached is not None and cls=='pending_or_unproven' and r['identity_pass']=='1'
                    and r['original_receipt'] and r['receipt'] and r['receipt'] not in cached):
                uncached[y,field][r['receipt']]+=1
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
            obs=a[f+'_observed'];unborn=a[f+'_confirmed_issuer_not_established'];absent=a[f+'_complete_search_no_periodic_report']
            hard=blocked+period+invalid+unborn+absent
            fields[f]={'observed':obs,'current_coverage':obs/n if n else None,'observed_plus_unknown_denominator':obs/(n+u) if n+u else None,
                'structural_only':ceiling(n,blocked),'structural_only_assume_all_unknown_pass':ceiling(n+u,blocked),
                'structural_and_confirmed_rules':ceiling(n,hard),
                'structural_and_confirmed_rules_assume_all_unknown_pass':ceiling(n+u,hard),
                'verified_period_rule':period,'verified_signal_domain':invalid,
                'confirmed_issuer_not_established':unborn,'complete_search_no_periodic_report':absent,
                'incomplete_index_with_same_no_cfs_document':a[f+'_index_incomplete_with_explicit_filing'],
                'unresolved_maximum_potential_increment':n-hard-obs,'ledger_reasons':dict(sorted(reasons[y,f].items()))}
            if cached is not None:
                fields[f]['minimum_new_receipts_relative_to_panel_cache']=minimum_uncached_receipts(n,hard,uncached[y,f])
        out[y]={'sample':a['total'],'identity':a['identity'],'identity_denominator':a['total'],
                'identity_required_90pct':(9*a['total']+9)//10,'identity_pending_or_unverified':a['total']-a['identity'],
                'financial':a['financial'],'nonfinancial':a['nonfinancial'],'unknown':a['unknown'],'fields':fields}
    result={'scope':'2017–2021; original 60 × 240 draw; observed historical sector and full-market size quartile',
            'ledger_sha256':ledger_sha,'context_sha256':ctx_sha,'metadata_sha256':quality['metadata_sha256'],
            'coverage_sha256':quality['coverage_sha256'],'by_year':out,'confirmed_no_cfs_issuer_months':support,
            'counted_local_cached_receipts':len(cached) if cached is not None else None,
            'cached_receipt_ids_sha256':sha256('\n'.join(sorted(cached)).encode()).hexdigest() if cached is not None else None,
            'additional_documented_candidates':[dict(formation=d,isin=i,reason=reason,**detail) for (d,i),(reason,detail) in sorted(extra.items())],
            'year_sector_size':[dict(year=y,industry=k,full_market_cap_quartile=q,field=f,counts=dict(v)) for (y,k,q,f),v in sorted(profiles.items())]}
    result['impossible_even_if_all_unknown_succeed']=[
        {'year':y,'signal':f,**a['structural_and_confirmed_rules_assume_all_unknown_pass']}
        for y,annual in out.items() for f,a in annual['fields'].items()
        if a['structural_and_confirmed_rules_assume_all_unknown_pass']['impossible_at_80pct']]
    tmp=output.with_suffix(output.suffix+'.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(output)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('roster_path','context_path','ledger_path','quality_path','facts','output'):
        parser.add_argument(key,type=Path)
    parser.add_argument('--identity',type=Path)
    parser.add_argument('--packages',type=Path)
    report=run(**vars(parser.parse_args()))
    if report['impossible_even_if_all_unknown_succeed']:
        print(json.dumps(report['impossible_even_if_all_unknown_succeed']))
