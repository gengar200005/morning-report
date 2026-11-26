"""Join dated KRX identities to independently indexed KIND and FSS original/amended reports."""
import argparse
from bisect import bisect_left,bisect_right
import calendar
from collections import Counter,defaultdict
import csv
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

TYPES={'사업보고서':'11011','반기보고서':'11012','분기보고서':'11013'}
COLUMNS=('isin stock_code corp_code kind_receipt receipt document filing_date available_session period_end report_type version identity_status '
         'kind_timestamp source_kind_sha256 source_dart_sha256 original_receipt reason source_kind_export_sha256 source_xbrl_index_sha256 '
         'kind_title dart_title kind_name dart_name stamp_precision kind_published dart_published xbrl_index_date dart_timestamp source_dart_time_sha256 ordering_timestamp comparator_identity_status comparator_identity_basis').split()
def read(path):
    with path.open(encoding='utf-8-sig',newline='') as s:return list(csv.DictReader(s))
def load(path):
    return json.loads(path.read_bytes())
def save(path,records,cols):
    tmp=path.with_suffix('.tmp')
    with tmp.open('w',newline='',encoding='utf8') as s:
        w=csv.DictWriter(s,fieldnames=cols,extrasaction='ignore',lineterminator='\n');w.writeheader();w.writerows(records)
    tmp.replace(path)
def alias(text):
    text=unicodedata.normalize('NFKC',text or '').upper().replace('주식회사','').replace('(주)','')
    return re.sub(r'[\s·ㆍ]','',text)
def event(title):
    plain=re.sub(r'\[[^\]]*\]', '',title).replace(' ','')
    form=next((v for k,v in TYPES.items() if plain.startswith(k+'(')),None)
    period=re.search(r'\((\d{4})[.\-](\d{1,2})\)\s*$',title.replace(' ',''))
    if not form or not period:return None
    y,m=map(int,period.groups())
    if not 1<=m<=12:return None
    end=f'{y:04d}{m:02d}{calendar.monthrange(y,m)[1]:02d}'
    version='amendment' if any(v in title for v in ('정정','첨부추가','첨부변경')) else 'original'
    return end,form,version

def securities(dbpath,issuers):
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        days=[r[0] for r in db.execute("select day from sessions where day between '20160101' and '20211231' order by day")]
        states={};opening={}
        for isin in issuers:
            states[isin]={d:(c,n) for d,c,n in db.execute("select day,code,name from membership where isin=? and common=1 and day<='20211201'",(isin,))}
            opening[isin]=db.execute('select code,listing_date from membership where day=? and isin=? and common=1',(days[0],isin)).fetchone()
    return days,states,opening
def previous(days,dt):
    i=bisect_right(days,dt)-1
    return days[i] if i>=0 else ''
def following(days,dt):
    if not days or dt<days[0]:return ''
    i=bisect_right(days,dt)
    return days[i] if i<len(days) else ''
def minute_number(value):
    hour,minute=map(int,value.split(':'))
    return hour*60+minute
def time_matches(k,d,clocks):
    time=clocks.get(d['receipt'])
    if not time or time['date']!=k['kind_timestamp'][:10].replace('-','') or event(time['title'])!=event(d['title']):return False
    return abs(minute_number(time['minute'])-minute_number(k['kind_timestamp'][-5:]))<=1
def valid_name(k,d,historical):
    return bool({alias(k['name']),alias(k['submitter']),alias(historical)}&{alias(d['name']),alias(d['submitter'])}-{''})
def local_source(w):
    kind={};whole=[];dart_files={};portal=defaultdict(dict)
    for f in sorted((w/'parsed').glob('K*-p*.json')):
        for r in load(f)['records']:kind[r['kind_receipt']]=r
    for f in sorted((w/'parsed').glob('KP-*.json')):
        if '-p' not in f.stem:
            obj=load(f);whole.append((obj['start'].replace('-',''),obj['end'].replace('-','')))
    for f in sorted((w/'parsed').glob('D-*-ALL.json')):
        rec=load(f);dart_files[rec['code']]=rec
    for f in sorted((w/'parsed').glob('X-*.json')):
        rec=load(f)
        for r in rec['records']:portal[rec['code']][r['receipt']]=r
    return kind,whole,dart_files,portal

def stage82(root,requested):
    docs=load(root/'public_xbrl_receipt_index.json');doc={r['receipt']:r for r in docs['rows']}
    assets=load(root/'identity_summary.json')['source_sha256']
    output={}
    for r in read(root/'identity_universe.csv'):
        if r['isin'] not in requested or r['identity_status']!='PASS':continue
        rid=r['receipt_candidate'];k=assets['kind'][r['kind_page']]
        output[r['kind_receipt']]=dict(isin=r['isin'],stock_code=r['stock_code'],corp_code=r['corp_code_candidate'],kind_receipt=r['kind_receipt'],
            receipt=rid,document=doc.get(rid,{}).get('document') or '',filing_date=r['filing_date'],available_session='',period_end='20210331',
            report_type='11013',version='original',identity_status='PASS',kind_timestamp=r['kind_timestamp'],source_kind_sha256=k['screen'],
            source_dart_sha256=assets['dart_index'],original_receipt=rid,reason='verified_stage82_original',source_kind_export_sha256=k['export'],
            source_xbrl_index_sha256='',kind_title='분기보고서(2021.03)',dart_title='분기보고서(2021.03)',kind_name=r['kind_name'],
            dart_name=r['dart_name'],stamp_precision='KIND_minute')
    return output
def consolidate(w,roster,db,prior):
    members=read(roster);sec={r['historical_isin']:r['historical_code'] for r in members};isos={v:k for k,v in sec.items()}
    issuers={r['stock_code']:r for r in read(w/'issuers.csv')};session,states,opening=securities(db,sec)
    kind,complete,darts,portals=local_source(w)
    clocks={r['receipt']:r for f in (w/'parsed').glob('time-*.json') for r in load(f)['records']}
    transfer={r['stock_code']:r for r in load(w/'transfer_proof.json') if r['verified_transfer']} if (w/'transfer_proof.json').exists() else {}
    # These date-qualified anchors remove same-name corporations from name-only search output.
    supp_path=w.parent/'identity_supplement/issuer_resolution.csv'
    supp={r['stock_code']:r['corp_code'] for r in read(supp_path) if r['issuer_verdict']=='historical_isin_anchored'} if supp_path.is_file() else {}
    for co,expected in supp.items():
        if co in darts:darts[co]['records']=[r for r in darts[co]['records'] if r['corp_code']==expected]
        portals[co]={key:r for key,r in portals[co].items() if r['corp_code']==expected}
    registry=stage82(prior,sec)
    for r in registry.values():
        r.update(available_session=following(session,r['filing_date']),kind_published=r['filing_date'],dart_published=r['filing_date'])
    candidates=defaultdict(list);kd=defaultdict(list)
    chosen_d={}
    for code in isos:
        sources={rid:r for rid,r in portals[code].items()}
        for r in darts.get(code,{}).get('records',[]):sources[r['receipt']]=r
        chosen_d[code]=sources
        for d in sources.values():
            ev=event(d['title'])
            if ev:candidates[(code,d['filing_date'],*ev)].append(d)
    for k in kind.values():
        co=k['stock_code'];ev=event(k['title'])
        if co in isos and ev:kd[(co,k['kind_timestamp'][:10].replace('-',''),*ev)].append(k)
    used=defaultdict(set);proven=set()
    for r in registry.values():proven.add((r['stock_code'],r['corp_code']))
    for key,kr in kd.items():
        co,fd,end,form,version=key;isins=isos[co];match=candidates.get(key,[])
        if len(kr)==len(match)==1 and (previous(session,fd) in states[isins]) and valid_name(kr[0],match[0],states[isins][previous(session,fd)][1]):
            proven.add((co,match[0]['corp_code']))
    # KRX may timestamp the submission on a different session from FSS publication (e.g. Friday vs Monday).
    # Accept a drift match only when both registries identify a single event and its dated identifier corroborates an endpoint.
    alternative=defaultdict(list)
    for key,ks in kd.items():
        if len(ks)!=1 or candidates.get(key):continue
        co,fd,end,form,version=key
        choices=[]
        for other in (previous(session,fd),following(session,fd),session[bisect_left(session,fd)-1] if bisect_left(session,fd)>0 else ''):
            if other==fd:continue
            matched=candidates.get((co,other,end,form,version),[])
            if len(matched)!=1 or kd.get((co,other,end,form,version)):continue
            d=matched[0]
            if d['receipt'][:8]!=fd and ks[0]['kind_receipt'][:8]!=other:continue
            if not valid_name(ks[0],d,'') and (co,d['corp_code']) not in proven:continue
            choices.append(d)
        if len({d['receipt'] for d in choices})==1:alternative[key]=[choices[0]]
    alternative_counts=Counter(d['receipt'] for ds in alternative.values() for d in ds)
    for key,ks in kd.items():
        co,fd,end,form,version=key;isin=isos[co];issuer_state=states[isin];dcs=candidates.get(key,[])
        filed=issuer_state.get(previous(session,fd));fiscal=issuer_state.get(previous(session,end))
        if not dcs and len(alternative[key])==1 and alternative_counts[alternative[key][0]['receipt']]==1:
            dcs=alternative[key]
        for k in ks:
            # Do not impose chronology from receipt number when the official day contains multiple versions.
            possibles=[d for d in dcs if valid_name(k,d,filed[1] if filed else '') or (co,d['corp_code']) in proven]
            d=possibles[0] if len(ks)==len(possibles)==1 else {}
            via_clock=False
            if not d:
                timed=[v for v in possibles if time_matches(k,v,clocks)]
                if len(timed)==1 and sum(time_matches(kr,timed[0],clocks) for kr in ks)==1:
                    d=timed[0];via_clock=True
            accepted=bool(d and filed and fiscal and filed[0]==fiscal[0]==co)
            via_transfer=False
            tr=transfer.get(co)
            if not accepted and d and tr and tr['isin']==isin and min(end,fd)>=tr['previous_listing_date']:
                # At least one relevant date precedes the direct KOSDAQ-to-KOSPI transfer.
                # The contemporary exit notice gives the original listing date, stock class and code.
                covered=lambda t,record:bool(record and record[0]==co) or tr['previous_listing_date']<=t<tr['transfer_date']
                if min(fd,end)<tr['transfer_date'] and covered(fd,filed) and covered(end,fiscal):
                    accepted=True;via_transfer=True
            xid=portals[co].get(d.get('receipt'),{})
            # The archived daily KOSPI master starts in 2016. A source from 2015 can still be
            # corroborated for comparison-only use by an original listing date preceding both dates,
            # as well as dated KRX-issued code on the original and matching FSS corporate identity.
            at_open=opening.get(isin)
            comparison_only=bool(not accepted and d and min(fd,end)<session[0] and at_open
                                 and at_open[0]==co and at_open[1]<=min(fd,end)
                                 and (co,d['corp_code']) in proven and valid_name(k,d,'')
                                 and (fd<session[0] or bool(filed and filed[0]==co)))

            reason=('official_KOSDAQ_KOSPI_continuous_transfer_and_cross_index' if via_transfer else 'unique_cross_index_publication_minute' if accepted and via_clock else 'cross_index_historical_ISIN' if accepted else 'missing_historical_filing_or_period_security' if d else
                    'ambiguous_same_day_or_issuer' if possibles else 'no_DART_crossindex_match')
            prev=registry.get(k['kind_receipt'])
            if prev and not accepted:continue
            published=max(fd,d.get('filing_date',''),xid.get('filing_date',''))
            out=dict(isin=isin,stock_code=co,corp_code=d.get('corp_code',''),kind_receipt=k['kind_receipt'],receipt=d.get('receipt',''),
                     document=xid.get('document') or (prev or {}).get('document',''),filing_date=published,available_session=following(session,published),
                     kind_published=fd,dart_published=d.get('filing_date',''),xbrl_index_date=xid.get('filing_date',''),
                     period_end=end,report_type=form,version=version,identity_status='PASS' if accepted else 'BLOCKED',
                     kind_timestamp=k['kind_timestamp'],source_kind_sha256=k['source_kind_sha256'],source_kind_export_sha256=k['source_kind_export_sha256'],
                     source_dart_sha256=d.get('source_sha256',''),source_xbrl_index_sha256=xid.get('source_sha256',''),
                     comparator_identity_status='PASS' if accepted or comparison_only else 'BLOCKED',
                     comparator_identity_basis=('same_as_signal_identity' if accepted else 'precalendar_original_KIND_code_FSS_CIK_20160104_master_prior_listing_date' if comparison_only else ''),
                     original_receipt='',reason=reason,kind_name=k['name'],dart_name=d.get('name',''),kind_title=k['title'],
                     dart_title=d.get('title',''),stamp_precision='KIND_minute')
            registry[k['kind_receipt']]=out
    for r in registry.values():
        if r['receipt']:used[r['stock_code']].add(r['receipt'])
    for co,evs in chosen_d.items():
        isin=isos[co]
        for rid,d in evs.items():
            if rid in used[co]:continue
            e=event(d['title'])
            if not e or (co,d['corp_code']) not in proven:continue
            fd=d['filing_date'];end,form,version=e;xd=portals[co].get(rid,{})
            registry['D'+co+rid]=dict(isin=isin,stock_code=co,corp_code=d['corp_code'],kind_receipt='',receipt=rid,
                document=xd.get('document') or '',filing_date=fd,available_session=following(session,fd),period_end=end,
                report_type=form,version=version,identity_status='BLOCKED',kind_timestamp='',source_kind_sha256='',
                source_dart_sha256=d['source_sha256'],original_receipt='',reason='DART_event_not_yet_uniquely_confirmed_by_KIND',
                source_kind_export_sha256='',source_xbrl_index_sha256=xd.get('source_sha256',''),kind_title='',dart_published=fd,xbrl_index_date=xd.get('filing_date',''),
                dart_title=d['title'],kind_name='',dart_name=d['name'],stamp_precision='date')
    result=list(registry.values());originals=defaultdict(set)
    for r in result:
        if r['version']=='original' and r['identity_status']=='PASS':
            originals[(r['isin'],r['period_end'],r['report_type'])].add(r['receipt'])
    for r in result:
        clock=clocks.get(r['receipt'])
        if clock and event(clock['title'])==event(r.get('dart_title','')):
            r['dart_timestamp']=clock['date'][:4]+'-'+clock['date'][4:6]+'-'+clock['date'][6:]+' '+clock['minute']
            r['source_dart_time_sha256']=clock['source']
        if (not r.get('dart_published') or not r.get('kind_published') or r['dart_published']==r['kind_published']):
            r['ordering_timestamp']=r.get('dart_timestamp') or r.get('kind_timestamp','')
        if 'comparator_identity_status' not in r:
            r['comparator_identity_status']='PASS' if r['identity_status']=='PASS' else 'BLOCKED'
            r['comparator_identity_basis']='same_as_signal_identity' if r['identity_status']=='PASS' else ''
        if not r['available_session'] and r['filing_date']<session[0]:
            r['reason']+=';before_verified_KRX_calendar'
        if r.get('dart_published') and r.get('kind_published') and r['dart_published']!=r['kind_published']:
            r['stamp_precision']='separate_agency_dates_max_no_within_day_order'
        orig=originals[(r['isin'],r['period_end'],r['report_type'])]
        if len(orig)==1:r['original_receipt']=next(iter(orig))
        elif r['version']=='amendment' and r['identity_status']=='PASS':
            r.update(identity_status='BLOCKED',reason='ambiguous_or_unavailable_original_version')
        elif len(orig)>1:r.update(identity_status='BLOCKED',comparator_identity_status='BLOCKED',reason='multiple_candidate_originals')
    result.sort(key=lambda r:(r['isin'],r['filing_date'],r['kind_timestamp'],r['receipt'],r['kind_receipt']))
    save(w/'receipts.csv',result,COLUMNS)
    monthly=[];co_summ=[]
    timeline=sorted(complete)
    def iscovered(start,end):
        remaining=date.fromisoformat(start)
        for lo,hi in timeline:
            a,b=date.fromisoformat(lo),date.fromisoformat(hi)
            if a<=remaining<=b:remaining=b+timedelta(days=1)
        return remaining>date.fromisoformat(end)
    for m in members:
        co=m['historical_code'];isin=m['historical_isin'];formation=m['formation'];hasd=co in darts and bool(darts[co]['records'])
        earliest=(date.fromisoformat(formation)-timedelta(days=180)).strftime('%Y%m%d')
        covered=iscovered(earliest,formation);historical=any(c==co for c,_ in proven)
        monthly.append(dict(formation=formation,isin=isin,stock_code=co,complete=int(hasd and covered and historical),
            kind_window_complete=int(covered),full_dart_list=int(hasd),corp_identity_evidenced=int(historical),
            reason='complete_search' if hasd and covered and historical else 'pending_or_unverified_search'))
    counts=Counter(r['isin'] for r in monthly if r['complete'])
    for co,isin in sorted(isos.items()):
        m=[r for r in monthly if r['isin']==isin];hasd=co in darts and bool(darts[co]['records'])
        co_summ.append(dict(isin=isin,stock_code=co,complete=int(counts[isin]==len(m)),start_date=m[0]['formation'],end_date=m[-1]['formation'],
            kind_completed_windows=len(complete),dart_report_11011=int(hasd),dart_report_11012=int(hasd),dart_report_11013=int(hasd),
            complete_months=counts[isin],expected_months=len(m),issue='' if counts[isin]==len(m) else 'pending_or_unverified_search'))
    save(w/'monthly_coverage.csv',monthly,list(monthly[0]));save(w/'coverage.csv',co_summ,list(co_summ[0]))
    summary=dict(rows=len(result),pass_rows=sum(r['identity_status']=='PASS' for r in result),
        downloadable=sum(r['identity_status']=='PASS' and bool(r['document']) for r in result),
        complete_kind_windows=complete,complete_issuer_full_dart=len(darts),complete_months=sum(counts.values()),expected_months=len(monthly))
    tmp=w/'progress.tmp';tmp.write_text(json.dumps(summary,ensure_ascii=False,indent=2));tmp.replace(w/'progress.json')
    print(summary['rows'],summary['pass_rows'],summary['downloadable'],summary['complete_issuer_full_dart'],summary['complete_months'],flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('work','roster','database','stage82'):p.add_argument(key,type=Path)
    a=p.parse_args();consolidate(a.work,a.roster,a.database,a.stage82)
