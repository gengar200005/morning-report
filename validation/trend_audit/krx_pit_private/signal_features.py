"""Prepare reproducible signal diagnostics from preserved evidence, no network calls.
The broad-market signal series is explicitly a comparison-base chained proxy,
not certified equivalent to the frozen supplier's adjusted price/volume.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import numpy as np
import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def features(close, volume, cfg, valid):
    """Same corrected V1 formulas, no RS universe decision in this function."""
    s=cfg['signal']['minervini']; supply=cfg['signal']['supply']
    ma50,ma150,ma200=(close.rolling(n).mean().shift(1) for n in (50,150,200))
    hi=close.rolling(s['lookback_52w']).max().shift(1)
    lo=close.rolling(s['lookback_52w']).min().shift(1)
    core=valid & (close>ma50)&(close>ma150)&(close>ma200)&(ma50>ma150)&(ma150>ma200)
    core &= (ma200>ma200.shift(s['trend_acceleration_days']))
    core &= close.ge(lo*s['lo52_threshold']) & close.ge(hi*s['hi52_threshold'])
    up=close.diff().gt(0); n=supply['lookback_days']
    uv=volume.where(up,0).rolling(n).sum().shift(1)
    dv=volume.where(~up,0).rolling(n).sum().shift(1)
    supply_pass=(uv/dv).where(dv.gt(0),999).ge(supply['ratio_min'])
    ret=(close/close.shift(s['lookback_52w'])-1).where(valid)
    return ret, core & supply_pass


def ranked_signals(ret, precondition, gate, rs_min):
    rs=ret.rank(axis=1,method='max',pct=True)*100
    mask=precondition & rs.ge(rs_min)
    mask.loc[~gate.reindex(mask.index,fill_value=False)]=False
    return rs,mask


def prepare(root,out):
    out.mkdir(parents=True,exist_ok=True)
    inp=root/'inputs'; cache=inp/'trend_handoff/validation/trend_audit/v2_risk_caps/recovered_v1/source_checkout/validation/trend_audit/cache'
    planpath=inp/'v1_kis_history_work/repo-overlay/validation/trend_audit/kis_history/plan.json'
    cfgpath=inp/'v1_ca_stage/inputs/frozen_signal_manifest.json'; batchpath=inp/'v1_ca_stage/review/frozen_candidate_batches.json'
    plan=json.loads(planpath.read_text()); manifest=json.loads(cfgpath.read_text());cfg=manifest['config'];fixed=plan['ordered_tickers']
    assert len(fixed)==162
    k=pd.Series({pd.Timestamp(x[0]):float(x[4]) for x in json.loads((cache/'KOSPI.json').read_text())[1:]}).sort_index()
    idx=k.index; ev=pd.DatetimeIndex(pd.to_datetime(plan['sessions'],format='%Y%m%d'))
    assert idx[252:].equals(ev)
    gate=k.gt(k.rolling(cfg['signal']['market_gate']['kospi_ma']).mean().shift(1))
    closes={};volumes={};hashes={}
    for t in fixed:
        path=cache/f'{t}.json';hashes[t]=digest(path)
        assert hashes[t]==manifest['input_hashes'][t]
        data=pd.DataFrame(json.loads(path.read_text())[1:]);data.index=pd.to_datetime(data[0])
        closes[t]=data[4].reindex(idx).ffill().fillna(0)
        volumes[t]=data[5].reindex(idx).ffill().fillna(0)
    c=pd.DataFrame(closes);v=pd.DataFrame(volumes)
    ret,pre=features(c,v,cfg,c.gt(0)&c.shift(252).gt(0))
    rs,flags=ranked_signals(ret,pre,gate,cfg['signal']['minervini']['rs_min'])
    frozen=json.loads(batchpath.read_text());expected={(x['first_date'],x['ticker']):x for x in frozen}
    rows=[]
    for i in range(251,len(idx)-1):
        for t in fixed:
            if flags.loc[idx[i],t]:
                rows.append(dict(date=idx[i+1].strftime('%Y%m%d'),signal_date=idx[i].strftime('%Y%m%d'),code=t,rs=float(rs.loc[idx[i],t])))
    actual={(x['date'],x['code']):x for x in rows}
    assert actual.keys()==expected.keys(), 'Frozen candidate set differs'
    max_rs=max(abs(x['rs']-expected[key]['rs']) for key,x in actual.items())
    assert max_rs<1e-10
    fixed_frame=pd.DataFrame(rows)
    fixed_frame.to_parquet(out/'fixed_exact.parquet',index=False)
    # Broad-market computation pool is a storage optimization only. Future
    # STK observation never grants past membership; official daily master does.
    cols=['Date','Code','MarketId','Close','Changes','Volume','Open','High','Low']
    paths=[root/'source_panel'/f'{y}.parquet' for y in range(2015,2027)]
    panel=pd.concat([pd.read_parquet(p,columns=cols) for p in paths],ignore_index=True)
    panel.Date=pd.to_datetime(panel.Date);panel=panel[panel.Date.le(ev[-1]) & panel.MarketId.isin(['STK','KSQ'])]
    assert not panel.duplicated(['Date','Code']).any()
    pool=set(panel.loc[panel.MarketId.eq('STK'),'Code'])|set(fixed)
    panel=panel[panel.Code.isin(pool)]
    c=panel.pivot(index='Date',columns='Code',values='Close').reindex(idx)
    change=panel.pivot(index='Date',columns='Code',values='Changes').reindex_like(c)
    v=panel.pivot(index='Date',columns='Code',values='Volume').reindex_like(c)
    ratio=(c/(c-change)).where(c.gt(0)&(c-change).gt(0))
    chain=ratio.fillna(1).cumprod()
    valid=(ratio.notna()&v.ge(0)).rolling(253).sum().eq(253)
    ret,pre=features(chain,v,cfg,valid)
    # Keep all observed rows, including missing lookback and zero volume.
    obs=panel[panel.Date.ge('2016-01-07')].copy()
    keys=pd.MultiIndex.from_frame(obs[['Date','Code']])
    obs['ret252']=ret.stack(future_stack=True).reindex(keys).to_numpy()
    obs['precondition']=pre.stack(future_stack=True).reindex(keys).fillna(False).to_numpy()
    obs['gate']=obs.Date.map(gate)
    obs.to_parquet(out/'proxy_features.parquet',index=False)
    # Same-input fixed control: only the universe changes in later PIT compare.
    r=ret.reindex(columns=fixed);p=pre.reindex(columns=fixed,fill_value=False)
    proxy_rs,proxy_flags=ranked_signals(r,p,gate,cfg['signal']['minervini']['rs_min'])
    proxy=[]
    for i in range(251,len(idx)-1):
        for t in fixed:
            if proxy_flags.loc[idx[i],t]:
                proxy.append(dict(date=idx[i+1].strftime('%Y%m%d'),signal_date=idx[i].strftime('%Y%m%d'),code=t,rs=float(proxy_rs.loc[idx[i],t])))
    pd.DataFrame(proxy).to_parquet(out/'fixed_proxy.parquet',index=False)
    pk={(r['date'],r['code']) for r in proxy};ek=set(actual)
    summary=dict(frozen_candidates=len(expected),regenerated_candidates=len(actual),added=0,removed=0,max_rs_error=max_rs,
                 proxy_fixed_candidates=len(pk),proxy_fixed_vs_exact_common=len(pk&ek),proxy_fixed_vs_exact_added=len(pk-ek),proxy_fixed_vs_exact_removed=len(ek-pk),
                 proxy_observed_rows=len(obs),proxy_codes=int(obs.Code.nunique()),raw_price_coverage_is_not_signal_price_equivalence=True)
    data=dict(config=cfg,ordered_fixed=fixed,sessions=plan['sessions'],calendar=[x.strftime('%Y%m%d') for x in idx],summary=summary,
              source_head=manifest['source_head'],frozen_engine_sha256=manifest['engine_sha256'],frozen_provider_sha256=manifest['provider_sha256'],
              source_hashes={str(p.relative_to(root)):digest(p) for p in paths+[cfgpath,planpath,batchpath,cache/'KOSPI.json',root/'code/execution.py',root/'code/replay.py',root/'code/frozen_strategy.py']},
              provider_price_hashes=hashes,script_sha256=digest(__file__),
              signal_basis='same corrected V1 formulas; broad-market comparison-base chained signal proxy; unverified adjusted-volume equivalence',
              terminal='No account simulation, exit signals or performance calculated')
    (out/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(out/'signal_features.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in ['fixed_exact.parquet','fixed_proxy.parquet','proxy_features.parquet','manifest.json']:
            z.write(out/name,name)
    print(json.dumps(summary,sort_keys=True))
    print('PACK_SHA256',digest(out/'signal_features.zip'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('out',type=Path)
    a=parser.parse_args();prepare(a.root,a.out)
