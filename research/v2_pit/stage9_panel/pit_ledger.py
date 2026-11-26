"""As-of filing/version selection and auditable F2/F3 ledger. No outcome data is used."""
import argparse
from bisect import bisect_right
import calendar
from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import io
import json
import re
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit

if __package__:
    from .q4_basis import annual_basis
else:
    from q4_basis import annual_basis

ROSTER_SHA = '84e5723e32f798a3fa7266c4dba6fa3fb076a014b4b01700077d4540ca369390'
FIELDS = ('revenue', 'operating_profit')
SIDES = ('current','prior')


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def snapshot_csv(path):
    raw=path.read_bytes()
    data=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline='')))
    return data,sha256(raw).hexdigest()


def day(value):
    return date.fromisoformat(value).strftime('%Y%m%d')


def prev_end(value, months):
    d = date.fromisoformat(value)
    m = d.year*12 + d.month-1-months
    y, m = divmod(m,12)
    return date(y,m+1,calendar.monthrange(y,m+1)[1]).strftime('%Y%m%d')


def filing_versions(rows, formation, period='', *, sessions, reference_only=False):
    """Latest available quarter, then latest available version of that quarter; never impute."""
    known = []
    for r in rows:
        if not r['period_end'] or not r['filing_date']:
            continue
        if r['filing_date'] >= formation or r['period_end'] > formation or (period and r['period_end'] != period):
            continue
        known.append(r)
    if not known:
        return None,'no_available_periodic_report'
    end = max(r['period_end'] for r in known)
    group = [r for r in known if r['period_end'] == end]
    body_ids={r['receipt'] for r in group if r.get('amendment_scope')!='nonfinancial_attachment_only'}
    exempt=[r for r in group if r.get('amendment_scope')=='nonfinancial_attachment_only'
            and r['version']=='amendment' and r['identity_status']=='PASS'
            and r.get('original_receipt') in body_ids
            and r['original_receipt'] in r.get('main_receipts_at_event','').split('|')
            and re.fullmatch('[a-f0-9]{64}',r.get('source_fss_viewer_sha256',''))]
    if exempt:
        group=[r for r in group if r not in exempt]
    latest_date = max(r['filing_date'] for r in group)
    on_date = [r for r in group if r['filing_date'] == latest_date]
    if len(on_date) > 1:
        times = [r.get('ordering_timestamp',r.get('kind_timestamp','')) for r in on_date]
        if not all(t and t[:10].replace('-','') == latest_date for t in times) or times.count(max(times)) != 1:
            return None,'same_day_version_order_unresolved'
        chosen = on_date[times.index(max(times))]
        # A complete clock from either registry can expose a reversed ordering.
        for clock in ('kind_timestamp','dart_timestamp'):
            stamps=[r.get(clock,'') for r in on_date]
            if all(stamp and stamp[:10].replace('-','')==latest_date for stamp in stamps):
                if chosen.get(clock,'') < max(stamps):
                    return None,'conflicting_publication_clocks'
    else:
        chosen = on_date[0]
    idx = bisect_right(sessions, latest_date)
    if idx == len(sessions) or sessions[idx] > formation:
        return None,'no_post_publication_session'
    if chosen.get('available_session') and chosen['available_session'] != sessions[idx]:
        return chosen,'publication_calendar_mismatch'
    if chosen['period_end'] > chosen['filing_date']:
        return chosen,'accounting_period_not_closed_at_filing'
    def verified(r):
        return r['identity_status']=='PASS' or (reference_only and r['version']=='original'
            and r['period_end']<sessions[0] and r.get('comparator_identity_status')=='PASS'
            and bool(r.get('comparator_identity_basis')))
    if not verified(chosen) or not chosen['corp_code'] or not chosen['receipt']:
        return chosen,'unverified_receipt_identity'
    originals = [r for r in group if r['version']=='original']
    if len(originals) != 1:
        return chosen,'missing_or_ambiguous_original'
    original = originals[0]
    if original['filing_date'] > chosen['filing_date'] or not verified(original):
        return chosen,'unverified_original'
    if chosen['version']=='original' and any(r['version']=='amendment' for r in group):
        return chosen,'amendment_precedes_original'
    if chosen['version'] not in ('original','amendment'):
        return chosen,'unrecognized_version'
    if chosen['version']=='amendment' and chosen.get('original_receipt')!=original['receipt']:
        return chosen,'unlinked_amendment'
    if chosen['corp_code']!=original['corp_code'] or chosen['report_type']!=original['report_type']:
        return chosen,'inconsistent_version_group'
    if exempt:
        chosen={**chosen,'nonfinancial_attachment_receipts':'|'.join(sorted(r['receipt'] for r in exempt))}
    return chosen,'PASS'


def receipt_sources(cache, r):
    for meta,evidence in cache.get(r['receipt'],[]):
        if meta['corp']!=r['corp_code'] or meta['period']!=r['period_end']:
            continue
        if meta['kind']=='xbrl' and r.get('document') and meta['doc']!=r['document']:
            continue
        if meta['kind']=='dart_html':
            url=urlsplit(evidence.get('source_url',''))
            params=parse_qs(url.query)
            if ((url.scheme,url.netloc,url.path)!=('https','dart.fss.or.kr','/report/viewer.do')
                    or params.get('rcpNo')!=[r['receipt']] or params.get('dcmNo')!=[meta['doc']]
                    or (r.get('document') and meta['doc']!=r['document'])):
                continue
        if meta['kind']=='kind_html':
            url=evidence.get('source_url','')
            route=re.fullmatch(r'https://kind\.krx\.co\.kr/external/(\d{4})/(\d{2})/(\d{2})/(\d{6})/(\d{14})/[^/]+\.html?',url,re.I)
            if not route or ''.join(route.groups()[:4])!=r.get('kind_receipt') or route[5]!=meta['doc']:
                continue
        yield meta,evidence


def receipt_amounts(cache, r, duration, field, sides=SIDES):
    """Retain complete same-document, same-period pairs and reject source disagreements."""
    options = {}
    observed = [set() for _ in sides]
    sources=list(receipt_sources(cache,r))
    for meta, evidence in sources:
        fs = evidence.get(str(duration),{})
        items = [fs.get(field+'_'+s,{}) for s in sides]
        if any(item.get('status')=='conflicting_values' for item in items):
            return None,[],'source_disagreement'
        values = tuple(item.get('value') for item in items)
        for side, value in zip(observed,values):
            if type(value) is int:
                side.add(value)
        if all(type(v) is int for v in values):
            options.setdefault(values,[]).append(meta['sha'])
    if any(len(side)>1 for side in observed):
        return None,[],'source_disagreement'
    if len(options) != 1:
        if not sources:
            return None,[],'no_receipt_payload'
        if any(e.get('explicit_no_cfs') for _,e in sources):
            return None,[],'reported_no_consolidated_statement'
        if all(e.get('has_cfs_context') is False for _,e in sources):
            return None,[],'no_consolidated_xbrl_context'
        return None,[],'no_exact_cfs_pair'
    values, hashes = next(iter(options.items()))
    return values,sorted(set(hashes)),'PASS'


def derived_quarter(rows, annual, formation, sessions, cache, basis, field):
    dates = [prev_end(annual['period_end'],n) for n in (3,12,15)]
    versioned = [filing_versions(rows,formation,end,sessions=sessions,reference_only=index>0)
                 for index,end in enumerate(dates)]
    if any(status!='PASS' for _,status in versioned):
        return None,{},'cumulative_support_version_unavailable'
    nine,prior_annual,prior_nine = [r for r,_ in versioned]
    sources=[annual,nine,prior_annual,prior_nine]
    if any(r.get('amendment_scope')=='financial_attachment_only' for r in sources):
        return None,{},'financial_attachment_comparison_unverified'
    for required in (annual,nine):
        if required.get('comparison_basis_status')=='BLOCKED':
            return None,{},required.get('comparison_basis_reason') or 'comparison_basis_unverified'
    if (annual['report_type']!='11011' or prior_annual['report_type']!='11011'
            or len({r['corp_code'] for r in sources})!=1 or len({r['receipt'] for r in sources})!=4):
        return None,{},'incompatible_cumulative_filings'
    amounts=[]; hashes=[]
    for row,months,sides in zip(sources,(12,9,12,9),(SIDES,SIDES,('current',),('current',))):
        pair, source, status=receipt_amounts(cache,row,months,field,sides)
        if status!='PASS':
            return None,{},'cumulative_'+status
        amounts.append(pair);hashes.append(source)
    fy,q3,prev_fy,prev_q3=amounts
    detail=dict(receipts=[r['receipt'] for r in sources], hashes=hashes,
                comparator_identity=[r.get('comparator_identity_basis') or r['identity_status'] for r in sources[2:]],
                filings=[r['filing_date'] for r in sources],
                **{'annual':fy,'nine_month':q3,'prior_year_filed_annual':prev_fy,'prior_year_filed_nine_month':prev_q3})
    if prev_fy[0]!=fy[1] or prev_q3[0]!=q3[1]:
        return None,detail,'prior_comparator_restated_or_inconsistent'
    derived=tuple(a-b for a,b in zip(fy,q3))
    detail['arithmetic_pair']=derived
    evidence_rows=[(meta['sha'],facts) for meta,facts in receipt_sources(cache,annual)]
    proof, audit=annual_basis(evidence_rows,field,q3,derived)
    detail['annual_basis_evidence']=audit
    if proof=='BLOCKED':
        return None,detail,'annual_inconsistent_with_interim'
    if proof=='PASS':
        detail['basis']=audit['reason']
    else:
        # Independent basis reviews are bound to hash/version and evidence public by formation.
        key=(annual['receipt'],nine['receipt'],prior_annual['receipt'],prior_nine['receipt'],field)
        review=basis.get(key)
        if (not review or review.get('verdict')!='PASS' or not review.get('source_url')
                or not re.fullmatch(r'[a-f0-9]{64}',review.get('source_sha256','')) or not review.get('available_session')
                or day(review['available_session']) not in sessions or day(review['available_session'])>formation
                or not all(h in saved for h,saved in zip(review.get('component_hashes',()),hashes,strict=False))
                or len(review.get('component_hashes',()))!=4):
            return None,detail,'arithmetic_only_basis_unverified'
        if review.get('note_source_hashes'):
            note_hashes=review['note_source_hashes']
            if (len(note_hashes)!=4 or not all(re.fullmatch(r'[a-f0-9]{64}',h) for h in note_hashes)
                    or not all(h in {meta['sha'] for meta,_ in receipt_sources(cache,r)}
                               for h,r in zip(note_hashes,sources,strict=True))):
                return None,detail,'basis_note_hashes_not_bound_to_effective_receipts'
            detail['note_source_hashes']=note_hashes
        if review.get('review_method'):
            detail['review_method']=review['review_method']
        if 'independent_quarter_confirmed' in review:
            detail['independent_quarter_confirmed']=review['independent_quarter_confirmed']
        detail['basis']=review['source_url']
        detail['basis_sha256']=review['source_sha256']
        detail['basis_available_session']=day(review['available_session'])
    detail['latest_component_filed']=max(r['filing_date'] for r in sources)
    return derived,detail,'PASS'


def normalize(rows):
    output=defaultdict(list)
    seen=set()
    for old in rows:
        r=dict(old)
        if not r.get('isin'):
            continue
        for n in ('period_end','filing_date','available_session'):
            if r.get(n):
                r[n]=day(r[n])
        if r.get('filing_date'):
            # A receipt number is not a publication timestamp. Later documented dates always win.
            documented=[r['filing_date']]
            if r.get('kind_timestamp'):
                documented.append(day(r['kind_timestamp'][:10]))
            if r.get('receipt') and len(r['receipt'])==14 and r['receipt'].isdigit():
                documented.append(day(r['receipt'][:8]))
            r['filing_date']=max(documented)
        k=(r['isin'],r.get('kind_receipt'),r.get('receipt'),r.get('period_end'),r.get('version'))
        if k in seen:
            raise ValueError('Duplicate filing version in identity metadata')
        seen.add(k)
        output[r['isin']].append(r)
    return output


def one_row(member, industry, history, coverage, sessions, cache, basis):
    t, isin=member['formation'],member['historical_isin']
    item=dict(formation=t,isin=isin,stock_code=member['historical_code'],industry_group=industry,
              identity_pass=0,period_end='',filing_date='',available_session='',receipt='',original_receipt='',
              corp_code='',kind_receipt='',document='',report_type='',nonfinancial_attachment_receipts='',amendment_scope='',ordering_timestamp='',comparison_basis_status='',comparison_basis_reason='',age_days='',filing_lag_days='',source_sha256='',version='',method_F2='',method_F3='',F2='',F3='',
              revenue_current='',revenue_prior='',operating_profit_current='',operating_profit_prior='',
              revenue_source_sha256='',operating_profit_source_sha256='',
              F2_reason='',F3_reason='',revenue_reason='',operating_profit_reason='',candidate_revenue_current='',candidate_revenue_prior='',
              candidate_operating_profit_current='',candidate_operating_profit_prior='',components='',status='BLOCKED',reason='')
    chosen,status=filing_versions(history,t,sessions=sessions)
    if chosen:
        for key in ('period_end','filing_date','receipt','corp_code','version','original_receipt','kind_receipt','document','report_type','nonfinancial_attachment_receipts','amendment_scope','ordering_timestamp','comparison_basis_status','comparison_basis_reason'):
            item[key]=chosen.get(key,'')
        if chosen['version']=='original':
            item['original_receipt']=chosen['receipt']
        item['age_days']=(date.fromisoformat(t)-date.fromisoformat(chosen['period_end'])).days
        item['filing_lag_days']=(date.fromisoformat(chosen['filing_date'])-date.fromisoformat(chosen['period_end'])).days
        n=bisect_right(sessions,chosen['filing_date'])
        item['available_session']=sessions[n] if n<len(sessions) else ''
    earliest=(date.fromisoformat(t)-timedelta(days=180)).strftime('%Y%m%d')
    if not coverage or coverage.get('complete') not in ('1','true','True'):
        status='incomplete_filing_index'
    elif coverage.get('formation') and day(coverage['formation'])!=t:
        status='incomplete_filing_window'
    elif not coverage.get('formation') and (not coverage.get('start_date') or not coverage.get('end_date')
            or day(coverage['start_date'])>earliest or day(coverage['end_date'])<t):
        status='incomplete_filing_window'
    elif coverage['stock_code']!=member['historical_code']:
        status='historical_security_mismatch'
    if status=='PASS':
        item['identity_pass']=1
        if chosen['stock_code']!=member['historical_code']:
            status='historical_security_mismatch';item['identity_pass']=0
        elif chosen['period_end'][4:6] not in ('03','06','09','12'):
            status='not_calendar_quarter_end'
        elif chosen['period_end'] < earliest:
            status='stale_latest_quarter'
        elif chosen.get('amendment_scope')=='financial_attachment_only':
            status='financial_attachment_comparison_unverified'
        elif chosen.get('comparison_basis_status')=='BLOCKED':
            status=chosen.get('comparison_basis_reason') or 'comparison_basis_unverified'
    if status!='PASS':
        item['F2_reason']=item['F3_reason']=item['reason']=status
        return item
    sources=set();details={};methods={};reasons={}
    for field in FIELDS:
        pair,hashes,why=receipt_amounts(cache,chosen,3,field)
        method='direct_quarter'
        if not pair and why!='source_disagreement' and chosen['report_type']=='11011':
            pair,detail,why=derived_quarter(history,chosen,t,sessions,cache,basis,field)
            method='annual_minus_nine'
            if detail:
                details[field]=detail
                if 'arithmetic_pair' in detail:
                    item['candidate_'+field+'_current'],item['candidate_'+field+'_prior']=detail['arithmetic_pair']
            if pair:
                hashes=[h for group in detail['hashes'] for h in group]
                hashes.extend(d['sha256'] for d in detail['annual_basis_evidence']['documents'])
                hashes.extend(detail.get('note_source_hashes',[]))
                if detail.get('basis_sha256'):
                    hashes.append(detail['basis_sha256'])
                latest=bisect_right(sessions,detail['latest_component_filed'])
                item['available_session']=max(item['available_session'],sessions[latest],detail.get('basis_available_session',''))
        if pair:
            item[field+'_current'],item[field+'_prior']=pair
            methods[field]=method
            sources.update(hashes)
            item[field+'_source_sha256']='|'.join(sorted(set(hashes)))
        reasons[field]=why
        item[field+'_reason']=why
    item['source_sha256']='|'.join(sorted(sources))
    item['components']=json.dumps(details,sort_keys=True,separators=(',',':')) if details else ''
    if industry!='nonfinancial':
        item['F2_reason']=item['F3_reason']=item['reason']='industry_'+industry
        return item
    rev,prior=item['revenue_current'],item['revenue_prior']
    op,prior_op=item['operating_profit_current'],item['operating_profit_prior']
    if rev=='':
        item['F2_reason']=item['F3_reason']=item['reason']='revenue_'+reasons['revenue']
        return item
    if prior>0 and rev>=0:
        item['F3']=str(Decimal(rev)/Decimal(prior)-1)
        item['method_F3']=methods['revenue'];item['F3_reason']='PASS'
    else:
        item['F3_reason']='nonpositive_prior_or_negative_current_revenue'
    if rev>0 and prior>0 and op!='':
        item['F2']=str(100*(Decimal(op)/Decimal(rev)-Decimal(prior_op)/Decimal(prior)))
        item['method_F2']='+'.join(sorted({methods[field] for field in FIELDS}));item['F2_reason']='PASS'
    else:
        item['F2_reason']='operating_profit_'+reasons['operating_profit'] if op=='' else 'nonpositive_revenue'
    if item['F2'] or item['F3']:
        item['status']='PASS';item['reason']='both_signals' if item['F2'] and item['F3'] else 'one_signal'
    else:
        item['reason']='no_eligible_signal'
    return item


def summary(group):
    applicable=[r for r in group if r['industry_group']=='nonfinancial']
    return dict(rows=len(group),identity=sum(r['identity_pass'] for r in group),nonfinancial=len(applicable),
                unknown=sum(r['industry_group']=='unknown' for r in group),
                F2=sum(bool(r['F2']) for r in applicable), F3=sum(bool(r['F3']) for r in applicable),
                conservative_denominator=len(applicable)+sum(r['industry_group']=='unknown' for r in group),
                F2_reasons=dict(Counter(r['F2_reason'] for r in applicable)),
                F3_reasons=dict(Counter(r['F3_reason'] for r in applicable)),
                reasons=dict(Counter(r['reason'] for r in group)))


def build(roster, context, receipts, coverage, sessions_db, facts_db, output, basis_file=None):
    if sha256(roster.read_bytes()).hexdigest()!=ROSTER_SHA:
        raise ValueError('Frozen sample roster mismatch')
    members=read_csv(roster)
    context_rows,context_sha=snapshot_csv(context)
    groups={(r['formation'],r['isin']):r for r in context_rows}
    if len(groups)!=len(context_rows):
        raise ValueError('Duplicate industry context')
    filing_rows,filing_sha=snapshot_csv(receipts)
    history=normalize(filing_rows)
    coverage_rows,coverage_sha=snapshot_csv(coverage)
    spans={(r.get('formation',''),r['isin']):r for r in coverage_rows}
    if len(spans)!=len(coverage_rows):
        raise ValueError('Duplicate coverage records')
    basis={}
    basis_sha=''
    if basis_file:
        raw_basis=basis_file.read_bytes()
        basis_sha=sha256(raw_basis).hexdigest()
        for r in json.loads(raw_basis):
            key=(*r['component_receipts'],r['field'])
            if key in basis:
                raise ValueError('Duplicate cumulative review')
            basis[key]=r
    with sqlite3.connect(sessions_db.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        sessions=[r[0] for r in db.execute("SELECT day FROM sessions WHERE day BETWEEN '20150101' AND '20211231' ORDER BY day")]
    if len(sessions)!=len(set(sessions)) or not set(m['formation'] for m in members).issubset(sessions):
        raise ValueError('Missing or duplicated formation sessions')
    cache=defaultdict(list)
    fact_signature=sha256()
    with sqlite3.connect(facts_db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for record in db.execute('SELECT * FROM facts ORDER BY receipt,kind,sha,period'):
            fact_signature.update(json.dumps(tuple(record),ensure_ascii=False,separators=(',',':')).encode()+b'\n')
            cache[record['receipt']].append((record,json.loads(record['evidence'])))
    rows=[]
    for m in members:
        g=groups.get((m['formation'],m['historical_isin']))
        if g is None or g['code']!=m['historical_code'] or g.get('sampled','1')!='1':
            raise ValueError('Frozen security missing from selected historical context')
        sector=g['industry_group']
        if sector not in ('nonfinancial','financial','unknown'):
            raise ValueError('Unknown industry group label')
        rows.append(one_row(m,sector,history[m['historical_isin']],spans.get((m['formation'],m['historical_isin']),spans.get(('',m['historical_isin']))),sessions,cache,basis))
    if len(rows)!=14400 or set(Counter(r['formation'] for r in rows).values())!={240} or len({(r['formation'],r['isin']) for r in rows})!=14400:
        raise ValueError('Expected complete 240 x 60 ledger')
    output.mkdir(exist_ok=True,parents=True)
    path=output/'issuer_months.csv'
    temp=path.with_suffix('.tmp')
    with temp.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    temp.replace(path)
    by_year={y:summary([r for r in rows if r['formation'][:4]==y]) for y in sorted({r['formation'][:4] for r in rows})}
    by_quarter={q:summary([r for r in rows if (int(r['formation'][4:6])-1)//3+1==q]) for q in range(1,5)}
    source_quarters=Counter(r['period_end'] for r in rows if r['period_end'])
    result=dict(total=summary(rows),by_year=by_year,by_formation_calendar_quarter=by_quarter,
                by_month={k:summary([r for r in rows if r['formation']==k]) for k in sorted({r['formation'] for r in rows})},
                by_selected_period={k:summary([r for r in rows if r['period_end']==k]) for k in sorted(source_quarters)},
                ledger_sha256=sha256(path.read_bytes()).hexdigest(),roster_sha256=ROSTER_SHA,
                metadata_sha256=filing_sha,coverage_sha256=coverage_sha,context_sha256=context_sha,
                fact_snapshot_sha256=fact_signature.hexdigest(),cumulative_basis_sha256=basis_sha,
                by_report_type={k:summary([r for r in rows if r['report_type']==k]) for k in sorted({r['report_type'] for r in rows})},
                by_version={k:summary([r for r in rows if r['version']==k]) for k in sorted({r['version'] for r in rows})},
                by_industry={k:summary([r for r in rows if r['industry_group']==k]) for k in sorted({r['industry_group'] for r in rows})})
    result['annual_gates']={k:{y:bool(v['identity']*10>=9*v['rows'] and v['nonfinancial'] and v[k]*5>=4*v['nonfinancial'])
                               for y,v in by_year.items()} for k in ('F2','F3')}
    (output/'quality.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('roster','context','receipts','coverage','sessions_db','facts_db','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--basis-file',type=Path)
    result=build(**vars(p.parse_args()))
    print(json.dumps({'totals':result['total'],'annual_gates':result['annual_gates']},ensure_ascii=False))
