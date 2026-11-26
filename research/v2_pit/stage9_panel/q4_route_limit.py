"""2017 cost scenario only: hold missing comparator chains and direct-Q4 evidence fixed."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage9_panel.coverage_limits import ceiling,field_class,read_csv
from stage9_panel.pit_ledger import filing_versions,normalize,prev_end,receipt_amounts,receipt_sources


def path_ceiling(n,structural,increment):
    result=ceiling(n,structural+increment)
    return {'denominator':n,'required_for_80pct':result['required'],
            'existing_confirmed_exclusions':structural,'additional_conditional_exclusions':increment,
            'conditional_maximum_observations':result['maximum_observations'],'conditional_maximum_fraction':result['maximum_fraction'],
            'shortfall_under_assumption':max(0,result['required']-result['maximum_observations'])}


def scenario(root,sessions_path,ledger_dir,dest):
    def digest(p):return sha256(p.read_bytes()).hexdigest()
    ledger,ledger_sha=read_csv(ledger_dir/'issuer_months.csv')
    quality=json.loads((ledger_dir/'quality.json').read_bytes())
    limit_path=ledger_dir/'coverage_limits.json'; limits=json.loads(limit_path.read_bytes())
    ir=root/'identity'; metadata,meta_sha=read_csv(ir/'receipts.csv')
    jobs,job_sha=read_csv(root/'ledger/precalendar_amendments_needed.csv')
    chains,chain_sha=read_csv(ir/'comparator_chains.csv')
    _,roster_sha=read_csv(root/'limited_issuer_months.csv')
    if ((roster_sha,meta_sha,ledger_sha)!=(quality['roster_sha256'],quality['metadata_sha256'],quality['ledger_sha256'])
            or limits['ledger_sha256']!=ledger_sha or limits['metadata_sha256']!=meta_sha):
        raise ValueError('Run against matching roster, ledger, quality and coverage-limit snapshots')
    selected={r['receipt']:r for r in jobs}
    links={r['receipt']:r for r in chains if r['receipt'] in selected}
    if links.keys()!=selected.keys():raise ValueError('Missing comparator job in chain review')
    blocked={rid:r for rid,r in links.items() if r['status']=='BLOCKED' and r['reason']=='no_verified_dual_menu'}
    for rid,r in links.items():
        if any(r[k]!=selected[rid][k] for k in ('isin','corp_code','period_end')):raise ValueError('Different comparator legal entity or period')
    history=normalize(metadata)
    with sqlite3.connect(sessions_path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        days=[r[0] for r in db.execute("select day from sessions where day between '20150101' and '20211231' order by day")]
    if sha256(('\n'.join(days)+'\n').encode()).hexdigest()!=quality['session_dates_sha256']:raise ValueError('Different trading calendar')
    cache=defaultdict(list);signature=sha256()
    with sqlite3.connect((root/'ledger/facts.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for r in db.execute('select * from facts order by receipt,kind,sha,period'):
            signature.update(json.dumps(tuple(r),ensure_ascii=False,separators=(',',':')).encode()+b'\n')
            if r['period']=='20161231':cache[r['receipt']].append((r,json.loads(r['evidence'])))
    if signature.hexdigest()!=quality['fact_snapshot_sha256']:raise ValueError('Rebuild final ledger from the same archived fact snapshot')
    with sqlite3.connect((root/'raw/receipts.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as db:
        raw=defaultdict(set)
        for rc,k,h in db.execute("select receipt,kind,sha256 from packages p where kind in ('kind_html','xbrl','dart_html') and not exists(select 1 from quarantine q where q.receipt=p.receipt and q.kind=p.kind)"):
            raw[rc].add((k,h))
    no_cfs={(r['formation'],r['isin']) for r in limits['confirmed_no_cfs_issuer_months']}
    other_hard={(r['formation'],r['isin']) for r in limits['additional_documented_candidates']}
    watch={x['isin'] for x in blocked.values()}
    fields={'F2':('revenue','operating_profit'),'F3':('revenue',)}
    added=defaultdict(list);reasons=defaultdict(Counter);trace=[]
    annual_rows=[r for r in ledger if r['formation'].startswith('2017') and r['industry_group']=='nonfinancial'
                 and r['period_end']=='20161231' and r['report_type']=='11011' and r['isin'] in watch]
    for r in annual_rows:
        day,i,corp=r['formation'],r['isin'],r['corp_code'];key=day,i
        if r['identity_pass']!='1' or not r['receipt']:continue
        h=history[i]; current,valid=filing_versions(h,day,sessions=days)
        if valid!='PASS' or current['receipt']!=r['receipt']:continue
        ref=[filing_versions(h,day,prev_end(r['period_end'],m),sessions=days,reference_only=m!=3) for m in (3,12,15)]
        denied={v['receipt'] for v,status in ref if v and v['receipt'] in blocked and v['corp_code']==corp
                and status in ('unverified_receipt_identity','unlinked_amendment')}
        if not denied:continue
        others=[status for v,status in ref if status!='PASS' and (v or {}).get('receipt') not in denied]
        # Screening all already published versions from this issuer's same fiscal period is optimistic.
        # A direct pair in an older version keeps the row out of the scenario; no signal is approved here.
        versions=[v for v in h if v['corp_code']==corp and v['period_end']==r['period_end'] and v['filing_date']<day and v['receipt']]
        inspected=set();unchecked=False;direct=set();why=defaultdict(set)
        for v in versions:
            sources=list(receipt_sources(cache,v))
            verified={(meta['kind'],meta['sha']) for meta,e in sources if not e.get('error')}
            if raw[v['receipt']]-verified:unchecked=True
            for meta,e in sources:
                if not e.get('error'):inspected.add((v['receipt'],meta['kind'],meta['sha']))
            for f in fields['F2']:
                pair,_,reason=receipt_amounts(cache,v,3,f)
                why[f].add(reason)
                if pair is not None:direct.add(f)
        for signal,required_fields in fields.items():
            missing=[f for f in required_fields if f not in direct]
            condition='additional_path_exclusion'
            if r[signal]:condition='already_observed'
            elif key in no_cfs or key in other_hard or field_class(r,signal,{})[0] in ('verified_period_rule','verified_signal_domain'):
                condition='already_in_structural_bound'
            elif not missing:condition='archived_direct_pair_available'
            elif (not any(rc==r['receipt'] for rc,_,_ in inspected) or unchecked):condition='annual_archive_unexamined'
            elif others or any(r[f+'_reason']!='cumulative_support_version_unavailable' for f in missing):
                condition='different_or_multiple_version_block'
            elif any('source_disagreement' in why[f] for f in missing):condition='direct_source_conflict'
            reasons[signal][condition]+=1
            if condition=='additional_path_exclusion':added[signal].append(key)
            trace.append(dict(formation=day,isin=i,signal=signal,current_annual=r['receipt'],unlinked_comparators=sorted(denied),
                              direct_fields=sorted(direct),other_support_version_issues=others,
                              reason=condition,examined_annual_sources=sorted(inspected)))
    out={}
    base=limits['by_year']['2017']
    for f in fields:
        structural=base['fields'][f]['structural_and_confirmed_rules']
        unique=set(added[f]);n=base['nonfinancial'];u=base['unknown'];hard=structural['hard_exclusions']
        if len(unique)!=len(added[f]):raise ValueError('Duplicate issuer/month scenario deduction')
        out[f]=dict(current_evidence_structural=structural,scenario_incremental=len(unique),
                    conditional_fixed_nonfinancial=path_ceiling(n,hard,len(unique)),
                    conditional_all_unknown_succeed=path_ceiling(n+u,hard,len(unique)),candidate_row_dispositions=dict(reasons[f]))
    result=dict(year='2017',nature='counterfactual collection-route ceiling for cost review, not structural impossibility or an outcome-release gate',
        condition='No additional admissible direct comparative Q4 or evidence connecting the affected amended 2015 comparator to its original; every other unresolved row succeeds.',
        roster_sha256=roster_sha,ledger_sha256=ledger_sha,fact_snapshot_sha256=signature.hexdigest(),metadata_sha256=meta_sha,coverage_limits_sha256=digest(limit_path),
        requested_list_sha256=job_sha,chain_status_sha256=chain_sha,requested_receipts=len(jobs),requested_month_links=sum(int(r['affected_issuer_months']) for r in jobs),
        demonstrated_chains=sorted(rid for rid,r in links.items() if r['status']=='PASS'),unlinked_receipts=len(blocked),
        unlinked_list_month_links_before_dedup=sum(int(selected[rid]['affected_issuer_months']) for rid in blocked),
        verified_latest_comparator_links_before_dedup=sum(len(x['unlinked_comparators']) for x in trace if x['signal']=='F3'),
        distinct_issuer_months_after_formation_replay=len({(x['formation'],x['isin']) for x in trace}),
        tested_raw_annual_source_versions=len({tuple(s) for x in trace for s in x['examined_annual_sources']}),
        by_signal=out,issuer_months=trace)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','sessions_path','ledger_dir','dest'):p.add_argument(name,type=Path)
    scenario(**vars(p.parse_args()))
