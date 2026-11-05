"""Independent ledger checks and clearly labelled incomplete-account diagnostics."""
import argparse
from decimal import Decimal as D
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def stats(values,initial=100_000_000):
    years=(values.index[-1]-values.index[0]).days/365.25
    dd=values/values.cummax()-1
    return dict(cagr_pct=100*((values.iloc[-1]/initial)**(1/years)-1),mdd_pct=100*dd.min(),final_priced_subtotal=float(values.iloc[-1]),total_return_pct=100*(values.iloc[-1]/initial-1),mdd_trough=str(dd.idxmin().date()))


def read_ledger(path):return pd.read_csv(path,dtype={'ticker':str})

def verify(folder,mode):
    # Parse all monetary strings as Decimal, no relative error tolerance.
    rows=pd.read_csv(folder/f'{mode}_daily.csv',dtype=str,keep_default_na=False)
    ledger=pd.read_csv(folder/f'{mode}_ledger.csv',dtype=str,keep_default_na=False)
    expected=D(100_000_000);max_cash=D(0)
    for e in ledger.to_dict('records'):
        expected+=D(e.get('cash_delta') or '0');error=abs(D(e['cash'])-expected);max_cash=max(max_cash,error)
        if error>D('.01'):raise AssertionError('Independent cash ledger error')
    max_nav=D(0)
    for r in rows.to_dict('records'):
        subtotal=sum((D(r[k]) for k in ['cash','stock','receivable','undelivered','derived_stock','distinct_pending']),D(0))
        if 'priced_asset_subtotal' in r:max_nav=max(max_nav,abs(subtotal-D(r['priced_asset_subtotal'])))
        if r['nav']:max_nav=max(max_nav,abs(subtotal-D(r['nav'])))
        if D(r['reserved'])>D(r['cash']):raise AssertionError('Reservation double spend')
    assert max_nav<=D('.01') and len(rows)==2650
    fill=ledger[ledger.event.isin(['filled','partial_fill'])]
    assert fill.quantity.map(lambda x:D(x)==int(D(x)) and D(x)>0).all()
    return dict(mode=mode,rows=len(rows),cash_max_abs_error=str(max_cash),asset_max_abs_error=str(max_nav),integer_fills=True,status='PASS_LEDGER_ARITHMETIC_NOT_RIGHTS_COMPLETENESS')


def cycles(ledger):
    active={};pending={};rows=[]
    for e in ledger.to_dict('records'):
        t=e['ticker'];day=e['time'].split()[0]
        if e['event']=='candidate_queued':pending[t]=day
        if e['event'] in ['filled','partial_fill']:
            if e['side']=='BUY':
                active.setdefault(t,dict(ticker=t,entry_date=day,signal_first_open=pending.get(t,''),buy_quantity=0,buy_cash=0.,sell_cash=0.,sell_quantity=0,quantity=0))
                a=active[t];a['buy_quantity']+=int(e['quantity']);a['quantity']+=int(e['quantity']);a['buy_cash']-=float(e['cash_delta'])
            elif t in active:
                a=active[t];a['quantity']-=int(e['quantity']);a['sell_quantity']+=int(e['quantity']);a['sell_cash']+=float(e['cash_delta'])
                if not a['quantity']:
                    a.update(exit_date=day,trading_cash_pnl=a['sell_cash']-a['buy_cash'],economic_pnl_verified=False,pnl_scope='trade cashflow only; dividends and unreceived rights unallocated')
                    rows.append(active.pop(t))
        elif t in active and e['event']=='split':active[t]['quantity']=int(e['quantity'])
        elif t in active and e['event']=='right_delivered':active[t]['quantity']+=int(e['quantity'])
    return pd.DataFrame(rows)


def analyze(root,work,out):
    out.mkdir(exist_ok=True,parents=True)
    folders={'FIXED_ADAPTER':work/'fixed_common_adapter','PIT':work/'pit','FIXED_PRESERVED':work/'fixed_reproduced'}
    daily={};ledgers={};checks=[]
    for cohort,folder in folders.items():
        for mode in ['D1','D2']:
            label=f'{cohort}_{mode}';frame=pd.read_csv(folder/f'{mode}_daily.csv',parse_dates=['date']).set_index('date')
            if 'priced_asset_subtotal' not in frame:frame['priced_asset_subtotal']=frame[['cash','stock','receivable','undelivered','derived_stock','distinct_pending']].sum(axis=1)
            daily[label]=frame;ledgers[label]=read_ledger(folder/f'{mode}_ledger.csv');checks.append(dict(cohort=cohort,**verify(folder,mode)))
    dates=next(iter(daily.values())).index
    cache=root/'inputs/trend_handoff/validation/trend_audit/v2_risk_caps/recovered_v1/source_checkout/validation/trend_audit/cache'
    def price(t):return pd.Series({pd.Timestamp(r[0]):float(r[4]) for r in json.loads((cache/f'{t}.json').read_text())[1:] if float(r[4])>0}).sort_index().reindex(dates)
    k=price('KOSPI');assert k.notna().all()
    etfpath=root/'inputs/trend_handoff/validation/trend_audit/v2_risk_caps/corporate_actions/sources/yahoo_069500.json'
    e=json.loads(etfpath.read_text())['result'];idx=pd.to_datetime(e['timestamp'],unit='s',utc=True).tz_convert('Asia/Seoul').normalize().tz_localize(None)
    etf=pd.Series(e['indicators']['adjclose'][0]['adjclose'],index=idx).reindex(dates);missing=etf.isna();bridge=price('069500')
    for i in np.flatnonzero(missing.to_numpy()):
        if i==0:raise ValueError('Missing initial benchmark')
        etf.iloc[i]=etf.iloc[i-1]*bridge.iloc[i]/bridge.iloc[i-1]
    rf=(1.03)**(dates.to_series().diff().dt.days.fillna(0)/365.25)-1
    rets={'KOSPI_PRICE':k.pct_change(fill_method=None).fillna(0),'KODEX200_TR_PROXY':etf.pct_change(fill_method=None).fillna(0)}
    values={label:df.priced_asset_subtotal for label,df in daily.items()}
    values.update({label:100_000_000*(1+r).cumprod() for label,r in rets.items()})
    # Explicit initial cost sensitivity, no terminal sale under common closing mark.
    values['KODEX200_TR_PROXY_ENTRY_COST']=values['KODEX200_TR_PROXY']/(1+.0015)
    exposures=[]
    for label,df in daily.items():
        weight=((df.stock+df.derived_stock)/df.priced_asset_subtotal).shift(1).fillna(0)
        if not weight.between(0,1+1e-10).all():raise AssertionError('Exposure outside range')
        emret=weight*rets['KODEX200_TR_PROXY']+(1-weight)*rf
        values[label+'_EXPOSURE_MATCHED']=100_000_000*(1+emret).cumprod()
        exposures.append(pd.DataFrame({'date':dates,'run':label,'prior_close_stock_weight':weight,'market_return':rets['KODEX200_TR_PROXY'],'cash_return':rf,'matched_value':values[label+'_EXPOSURE_MATCHED']}))
    allvalues=pd.DataFrame(values);allvalues.index.name='date';allvalues.to_csv(out/'diagnostic_wealth_and_benchmarks.csv')
    pd.concat(exposures).to_csv(out/'exposure_matched.csv',index=False)
    summaries=[];annual=[];trades=[];route=[]
    for label,val in values.items():
        row=dict(run=label,**stats(val));row['status']='BENCHMARK_PRICE_OR_ADJUSTED_PROXY' if label.startswith(('KOSPI_PRICE','KODEX200')) else 'INCOMPLETE_PRICED_SUBTOTAL_NOT_CERTIFIED_PERFORMANCE'
        if label in daily:
            ledger=ledgers[label];fill=ledger[ledger.event.isin(['filled','partial_fill'])];buy=fill[fill.side.eq('BUY')];sell=fill[fill.side.eq('SELL')]
            closed=cycles(ledger)
            if len(closed):
                closed['run']=label;trades.append(closed)
                wins=closed.trading_cash_pnl.gt(0);losses=closed.trading_cash_pnl.lt(0)
                row.update(buy_fills=len(buy),sell_fills=len(sell),unique_bought_codes=int(buy.ticker.nunique()),closed_cashflow_cycles=len(closed),cashflow_win_rate_pct=float(wins.mean()*100),cashflow_payoff_ratio=float(closed.loc[wins,'trading_cash_pnl'].mean()/-closed.loc[losses,'trading_cash_pnl'].mean()) if losses.any() else None)
            # Sum absolute traded notional / preceding closing subtotal; no
            # divide-by-two convention and no fictitious rights turnover.
            prev=val.shift(1).fillna(100_000_000)
            notion=fill.assign(date=pd.to_datetime(fill.time.str.split().str[0]),notional=fill.quantity*fill.price).groupby('date').notional.sum().reindex(dates,fill_value=0)
            row['annualized_gross_one_way_turnover']=float((notion/prev).sum()/((dates[-1]-dates[0]).days/365.25))
            row['vs_kospi_price_cagr_pp']=row['cagr_pct']-stats(values['KOSPI_PRICE'])['cagr_pct'];row['vs_etf_proxy_cagr_pp']=row['cagr_pct']-stats(values['KODEX200_TR_PROXY'])['cagr_pct'];row['vs_exposure_matched_cagr_pp']=row['cagr_pct']-stats(values[label+'_EXPOSURE_MATCHED'])['cagr_pct']
        summaries.append(row)
        for y,g in val.groupby(val.index.year):
            i=val.index.get_loc(g.index[0]);start=100_000_000 if i==0 else float(val.iloc[i-1]);annual.append(dict(run=label,year=int(y),return_pct=(g.iloc[-1]/start-1)*100,status=row['status']))
    pd.DataFrame(summaries).to_csv(out/'diagnostic_summary.csv',index=False);pd.DataFrame(annual).to_csv(out/'yearly_diagnostic_returns.csv',index=False)
    if trades:pd.concat(trades,ignore_index=True).to_csv(out/'cashflow_cycles_UNVERIFIED_ECONOMIC_PNL.csv',index=False)
    for mode in ['D1','D2']:
        a=ledgers['FIXED_ADAPTER_'+mode];b=ledgers['PIT_'+mode]
        for side in ['BUY','SELL']:
            def pairs(df):return {(str(r.time).split()[0],r.ticker) for r in df[df.event.isin(['filled','partial_fill'])&df.side.eq(side)].itertuples()}
            x,y=pairs(a),pairs(b)
            route.append(dict(mode=mode,side=side,fixed_pairs=len(x),pit_pairs=len(y),common_pairs=len(x&y),pit_added=len(y-x),fixed_removed=len(x-y),first_different=min(x^y) if x^y else None))
    pd.DataFrame(route).to_csv(out/'execution_path_comparison.csv',index=False)
    for c,folder in folders.items():
        if c=='FIXED_PRESERVED':continue
        events=pd.read_csv(folder/'material_events.csv',dtype={'ticker':str})
        if len(events):
            grouped=events.groupby(['cohort','mode','date','ticker'],as_index=False).agg(kinds=('kind',lambda x:'|'.join(sorted(set(x)))),exposure_krw=('exposure_krw','max'),prior_nav_share=('prior_nav_share','max'))
            grouped.to_csv(out/f'{c}_material_incidents.csv',index=False)
    (out/'independent_checks.json').write_text(json.dumps(dict(results=checks,benchmark=dict(kospi='price, excludes dividends',etf='Yahoo adjusted close TR proxy; no trading fees except explicit initial-cost sensitivity',etf_gap_days=int(missing.sum()),exposure_weights='prior close, shifted one interval; uses incomplete priced subtotal denominator'),source_hashes={str(p):digest(p) for p in [etfpath,cache/'KOSPI.json',cache/'069500.json']},script_sha256=digest(__file__)),indent=2))
    print(pd.DataFrame(summaries).loc[lambda x:~x.run.str.contains('EXPOSURE_MATCHED'),['run','cagr_pct','mdd_pct','final_priced_subtotal']].to_string(index=False))
    print('INDEPENDENT_LEDGER_CHECKS_PASS',len(checks))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('work',type=Path);p.add_argument('out',type=Path);a=p.parse_args();analyze(a.root,a.work,a.out)
