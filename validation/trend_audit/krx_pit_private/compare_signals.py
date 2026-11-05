"""Join preserved feature diagnostics to private official PIT membership.
No KRX calls, account replay, exits, or fabricated returns. Full details private.
"""
from collections import defaultdict
import gzip,hashlib,io,json,os,zipfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
import pandas as pd
from gdrive_upload import _build_service
from validation.trend_audit.krx_pit_private.drive_collect import existing,folder,validate
from validation.trend_audit.krx_pit_private.drive_retry import read_retry,upload_archive
from validation.trend_audit.krx_pit_private.compare_universe import classification

MEMBERSHIP_NAME='KRX_PIT_UNIVERSE_COMPARE_46af0417ddfcf866.json.gz'
MEMBERSHIP_SHA='46af0417ddfcf8667ef8e8c21ff96a5ea5ef8a0bfd4d84d736c4231b4e0d5bfe'


def sha(data): return hashlib.sha256(data).hexdigest()


def select_day(frame,members,rs_min):
    # Official membership is required before ranking. A future STK row in the
    # calculation pool cannot make a past KOSDAQ row enter the RS denominator.
    day=frame[frame.Code.isin(members)].copy()
    if not day.MarketId.eq('STK').all():
        raise ValueError('OFFICIAL_MIRROR_MARKET_CONFLICT')
    day['rs']=day.ret252.rank(method='max',pct=True)*100
    signals=day[day.precondition & day.rs.ge(rs_min) & day.gate].copy()
    signals['execution_record_available']=signals.Volume.gt(0)&signals[['Open','High','Low','Close']].gt(0).all(axis=1)
    signals['execution_record_available'] &= signals.Low.le(signals[['Open','Close']].min(axis=1)) & signals.High.ge(signals[['Open','Close']].max(axis=1))
    return day,signals


def compare(frame,membership,manifest,exact,proxy):
    calendar=manifest['calendar'];nextday=dict(zip(calendar[:-1],calendar[1:])); fixed=manifest['ordered_fixed'];fixedset=set(fixed)
    byday={d:g for d,g in frame.groupby('date')}
    rs_min=manifest['config']['signal']['minervini']['rs_min']
    exactkeys={(str(r.date),r.code) for r in exact.itertuples()}
    proxykeys={(str(r.date),r.code) for r in proxy.itertuples()}
    signals=[];ranks=[];coverage=[];identity=defaultdict(set);missing=[];seen=set();price_codes=set();eligible_codes=set()
    allmembers={row['date']:row['members'] for row in membership['daily_membership']}
    for date,members_list in allmembers.items():
        members={r['code']:r for r in members_list};seen.update(members)
        for code,r in members.items():
            if r['listing_date']>date: raise ValueError('PRE_LISTING_MEMBERSHIP')
            identity[code].add(r['isin'])
        f=byday.get(date,frame.iloc[:0]);present=set(f.Code)&members.keys();price_codes.update(present)
        absent=members.keys()-set(f.Code)
        missing.extend(dict(date=date,code=c,reason='mirror_no_row') for c in absent)
        # Derived previous comparison included official daily validation; names,
        # ISIN and class are not inferred from mirror strings.
        ranked,candidates=select_day(f,members,rs_min)
        eligible_codes.update(ranked.loc[ranked.ret252.notna(),'Code'])
        valid=ranked.ret252.notna();unavailable=ranked.loc[~valid,'Code']
        for c in unavailable: missing.append(dict(date=date,code=c,reason='insufficient_or_discontinuous_253_row_signal_history'))
        cf=f[f.Code.isin(fixedset)].copy();cf['fixed_rs']=cf.ret252.rank(method='max',pct=True)*100
        joined=ranked[['Code','rs']].merge(cf[['Code','fixed_rs']],on='Code')
        joined=joined.dropna()
        for r in joined.itertuples():
            ranks.append(dict(date=date,code=r.Code,pit_rs=r.rs,fixed_rs=r.fixed_rs,change=r.rs-r.fixed_rs))
        eligible_date=nextday.get(date)
        if eligible_date:
            for r in candidates.itertuples():
                signals.append(dict(date=eligible_date,signal_date=date,code=r.Code,rs=r.rs,
                                    isin=members[r.Code]['isin'],outside_fixed=r.Code not in fixedset,
                                    execution_record_available=bool(r.execution_record_available),
                                    still_listed_next_open=r.Code in {x['code'] for x in allmembers.get(eligible_date,[])},
                                    basis='comparison_base_chain_proxy'))
        coverage.append(dict(date=date,pit=len(members),mirror_rows=len(present),missing_rows=len(absent),rankable=int(valid.sum()),
                             history_unavailable=int((~valid).sum()),zero_volume=int(ranked.Volume.eq(0).sum()),
                             potential_signals=len(candidates),uncertain=len(next((x.get('uncertain',[]) for x in membership['daily_membership'] if x['date']==date),[]))))
    # Jan 8 entry signals use Jan 7 official membership supplied separately.
    for date,members_list in membership.get('pre_evaluation_membership',{}).items():
        f=byday.get(date,frame.iloc[:0]);members={x['code']:x for x in members_list}
        _,cand=select_day(f,members,rs_min)
        for r in cand.itertuples():
            signals.append(dict(date=nextday[date],signal_date=date,code=r.Code,rs=r.rs,isin=members[r.Code]['isin'],outside_fixed=r.Code not in fixedset,
                execution_record_available=bool(r.execution_record_available),still_listed_next_open=r.Code in {x['code'] for x in allmembers[nextday[date]]},basis='comparison_base_chain_proxy'))
    if any(len(ids)>1 for ids in identity.values()): raise ValueError('SECURITY_IDENTITY_REQUIRES_EPISODE_LINK')
    result=pd.DataFrame(signals);result=result[result.date.isin(manifest['sessions'])]
    order={c:i for i,c in enumerate(fixed)}
    # Existing order preserved for old tickers; new tickers have deterministic
    # lexical order, precommitted as diagnostic tie-break only.
    result['tie_order']=result.code.map(order).fillna(len(fixed))
    result=result.sort_values(['date','rs','tie_order','code'],ascending=[True,False,True,True])
    pitkeys={(r.date,r.code) for r in result.itertuples()};finaldate=manifest['sessions'][-1]
    ended={c for c in seen if c not in {x['code'] for x in allmembers[finaldate]}}
    rankframe=pd.DataFrame(ranks);cov=pd.DataFrame(coverage)
    summary=dict(sessions=len(cov),official_codes=len(seen),codes_with_mirror_rows=len(price_codes),codes_ever_rankable=len(eligible_codes),
        missing_price_codes=len(seen-price_codes),missing_mirror_code_days=int(cov.missing_rows.sum()),history_unavailable_code_days=int(cov.history_unavailable.sum()),
        frozen_exact_candidates=len(exactkeys),fixed_proxy_candidates=len(proxykeys),pit_proxy_candidates=len(pitkeys),
        same_proxy_common_candidates=len(proxykeys&pitkeys),same_proxy_pit_added=len(pitkeys-proxykeys),same_proxy_fixed_removed=len(proxykeys-pitkeys),
        mixed_basis_exact_common=len(exactkeys&pitkeys),mixed_basis_exact_removed=len(exactkeys-pitkeys),mixed_basis_pit_added=len(pitkeys-exactkeys),
        pit_candidates_outside_fixed=int(result.outside_fixed.sum()),pit_candidate_unique_codes=int(result.code.nunique()),
        pit_candidates_in_codes_absent_at_end=int(result.code.isin(ended).sum()),
        candidates_without_positive_valid_quote=int((~result.execution_record_available).sum()),candidates_absent_at_next_open=int((~result.still_listed_next_open).sum()),
        shared_rank_pairs=len(rankframe),shared_rank_changed=int(rankframe.change.abs().gt(1e-10).sum()),
        mean_abs_shared_rs_change=float(rankframe.change.abs().mean()),max_abs_shared_rs_change=float(rankframe.change.abs().max()),
        actual_buy_sell_changes=None,performance_calculated=False,verdict='INCONCLUSIVE_PERFORMANCE_AND_SIGNAL_BASIS')
    annual=[]
    for year,group in result.groupby(result.date.str[:4]):
        p={(r.date,r.code) for r in group.itertuples()};q={x for x in proxykeys if x[0].startswith(year)};e={x for x in exactkeys if x[0].startswith(year)}
        annual.append(dict(year=year,fixed_exact=len(e),fixed_proxy=len(q),pit_proxy=len(p),common_same_proxy=len(p&q),pit_added_same_proxy=len(p-q),fixed_removed_same_proxy=len(q-p),outside_fixed=int(group.outside_fixed.sum())))
    details=dict(summary=summary,annual=annual,signals=result.to_dict('records'),rank_changes=rankframe.to_dict('records'),
                 coverage=cov.to_dict('records'),unavailable=missing,manifest=manifest,
                 limitations=['Broad signal prices are chained proxy, not frozen provider equivalent','2015 code/ISIN continuity not independently certified',
                              'Listed is not proven executable','No account replay/exit/performance; corporate actions/delisting still require path review'])
    return details


def main():
    service=_build_service(*(os.environ[k] for k in ['GDRIVE_OAUTH_CLIENT_ID','GDRIVE_OAUTH_CLIENT_SECRET','GDRIVE_OAUTH_REFRESH_TOKEN']))
    fid=read_retry(lambda:folder(service))
    if fid!='1f_FAl_IL31nhw69gSgU5UCfW8P9LBbKY': raise ValueError('DESTINATION_MISMATCH')
    def load(name,expected):
        obj=read_retry(lambda:existing(service,fid,name))
        if not obj or obj.get('shared') is not False: raise ValueError('PRIVATE_INPUT_NOT_FOUND')
        raw=read_retry(lambda:service.files().get_media(fileId=obj['id']).execute())
        if sha(raw)!=expected or hashlib.md5(raw).hexdigest()!=obj['md5Checksum']: raise ValueError('INPUT_HASH_MISMATCH')
        return raw
    pack=load(os.environ['SIGNAL_PACK_NAME'],os.environ['SIGNAL_PACK_SHA256'])
    with zipfile.ZipFile(io.BytesIO(pack)) as z:
        manifest=json.loads(z.read('manifest.json'))
        frame=pd.read_parquet(io.BytesIO(z.read('proxy_features.parquet')))
        exact=pd.read_parquet(io.BytesIO(z.read('fixed_exact.parquet')))
        proxy=pd.read_parquet(io.BytesIO(z.read('fixed_proxy.parquet')))
    membership=json.loads(gzip.decompress(load(MEMBERSHIP_NAME,MEMBERSHIP_SHA)))
    # One reused month supplies prior-day official membership for first entry.
    obj=read_retry(lambda:existing(service,fid,'KRX_PIT_2016_01_v1.json.gz'))
    raw=load('KRX_PIT_2016_01_v1.json.gz',membership['archives_sha256']['KRX_PIT_2016_01_v1.json.gz'])
    jan=json.loads(gzip.decompress(raw));rec=next(x for x in jan['records'] if x['date']=='20160107')
    b=validate('basic','20160107',rec['basic']);d=validate('daily','20160107',rec['daily'])
    if b.keys()!=d.keys():raise ValueError('PRIOR_DAY_OFFICIAL_MISMATCH')
    membership['pre_evaluation_membership']={'20160107':[dict(code=c,isin=r['ISU_CD']) for c,r in b.items() if classification(r)=='common']}
    frame=frame.rename(columns={'Date':'date'});frame['date']=pd.to_datetime(frame.date).dt.strftime('%Y%m%d')
    details=compare(frame,membership,manifest,exact,proxy)
    details['input_pack_sha256']=sha(pack);details['official_membership_sha256']=MEMBERSHIP_SHA
    details['comparison_script_sha256']=sha(Path(__file__).read_bytes())
    data=gzip.compress(json.dumps(details,ensure_ascii=False,allow_nan=False,separators=(',',':'),sort_keys=True).encode(),mtime=0)
    h=sha(data);name=f'KRX_PIT_SIGNAL_COMPARE_{h[:16]}.json.gz'
    def verify(obj):
        body=read_retry(lambda:service.files().get_media(fileId=obj['id']).execute())
        if obj.get('shared') is not False or sha(body)!=h or hashlib.md5(body).hexdigest()!=obj['md5Checksum']:raise ValueError('OUTPUT_INTEGRITY')
    upload_archive(service,fid,name,f'Private derived signal comparison sha256={h}',data,existing,verify)
    print('SIGNAL_COMPARE_SUMMARY '+json.dumps(details['summary'],sort_keys=True),flush=True)
    for row in details['annual']:print('SIGNAL_COMPARE_YEAR '+json.dumps(row,sort_keys=True),flush=True)
    print('PRIVATE_SIGNAL_COMPARISON_SAVED sha256='+h,flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        safe=str(exc) if str(exc) in {'OFFICIAL_MIRROR_MARKET_CONFLICT','SECURITY_IDENTITY_REQUIRES_EPISODE_LINK','INPUT_HASH_MISMATCH','PRIVATE_INPUT_NOT_FOUND','PRIOR_DAY_OFFICIAL_MISMATCH','OUTPUT_INTEGRITY','PRE_LISTING_MEMBERSHIP'} else 'UNCLASSIFIED'
        print('PRIVATE_SIGNAL_COMPARE_FAILED type='+type(exc).__name__+' code='+safe,flush=True)
        raise SystemExit(2)
