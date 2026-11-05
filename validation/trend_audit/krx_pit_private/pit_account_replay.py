"""Minimal input adapter for preserved integer-share Replay; no strategy edits.
All fills are conditional daily-bar simulations, never broker-confirmed fills.
Unknown rights are recorded as unknown, not treated as zero-value settlements.
"""
import argparse
from collections import defaultdict
from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction
import gzip,hashlib,json,zipfile
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import pandas as pd

ACCOUNT_HASH={'execution.py':'9c05e6d2d87f95623581b18d524613caffb922967e39bbac37f8330a03571ec3','replay.py':'37cf6f84a2839baa01f1d5704e0e0e5661e0b2e452390af7fcd380d5d0e68658'}
SIGNAL_HASH='3c696bd878089b73db536639e73d01829b4e5212a44b59cdbeca9348c57f450a'
MEMBERSHIP_HASH='46af0417ddfcf8667ef8e8c21ff96a5ea5ef8a0bfd4d84d736c4231b4e0d5bfe'
OLD=((0,1),(1000,5),(5000,10),(10000,50),(50000,100),(100000,500),(500000,1000))
NEW=((0,1),(2000,5),(5000,10),(20000,50),(50000,100),(200000,500),(500000,1000))


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_feature_files(directory,expected_sha='32ef8ade9e1b8dfb28b732f74a2a57f0acf8e723df8bb896aacf9649856dfee7'):
    archive=directory/'signal_features.zip'
    if digest(archive)!=expected_sha:raise ValueError('Feature input hash changed')
    with zipfile.ZipFile(archive) as z:
        for name in ('manifest.json','proxy_features.parquet'):
            if hashlib.sha256(z.read(name)).hexdigest()!=digest(directory/name):
                raise ValueError('Expanded feature differs from verified archive')


def load_account(root):
    for name,expected in ACCOUNT_HASH.items():
        if digest(root/name)!=expected:raise ValueError('Preserved account hash changed')
    sys.path.insert(0,str(root.resolve()))
    import execution,replay
    assert execution.FEE==D('.0015') and replay.CASH_RATE==D('.03')
    return execution,replay


def valid_row(row):
    try:
        values=[float(getattr(row,x)) for x in ('Open','High','Low','Close','Volume')]
        if not all(np.isfinite(x) and x==int(x) for x in values):return False
        op,hi,lo,cl,v=map(int,values)
    except (ValueError,TypeError,AttributeError):return False
    return min(op,hi,lo,cl)>0 and v>0 and lo<=min(op,cl)<=max(op,cl)<=hi


def make_quotes(rows,prior,relevant,mode,iso,ex,rep):
    """A D2 submission reference exists independently of today's fill outcome."""
    class ObservedRule(ex.QuoteRule):
        def valid(self,price):return type(price) is int and price>0
        def cap(self,reference):
            tick=next(t for floor,t in reversed(self.bands) if reference>=floor)
            return max(1,reference//tick*tick)
    bands=OLD if iso<'20230125' else NEW
    quotes={};states={};indexed={r.Code:r for r in rows.itertuples(index=False)}
    for t in relevant:
        row=indexed.get(t);valid=row is not None and valid_row(row)
        states[t]='TRADABLE' if valid else 'NO_MARKET_DATA'
        if row is not None and not valid:
            try:
                if float(row.Volume)==0 and min(float(row.Open),float(row.Close))>0:states[t]='ZERO_VOLUME_VALID_RECORD'
            except (TypeError,ValueError):pass
        opening=int(row.Open) if valid else None;close=int(row.Close) if valid else None
        if mode=='D1' and valid:
            quotes[t]=rep.Quote(ObservedRule(1,10**9,((0,1),)),prior.get(t,opening),opening,close,True)
        elif mode=='D2' and t in prior:
            quotes[t]=rep.Quote(ObservedRule(1,10**9,bands),prior[t],opening,close,valid)
    return quotes,states


def actions_from_preserved(root,ids,rep,include_material):
    """Reuse confirmed terms. Unverified rows remain an explicit inventory."""
    inp=root/'inputs';stage=inp/'v1_ca_stage';dates=pd.DatetimeIndex(pd.to_datetime(ids));lookup=dict(zip(ids,range(252,252+len(ids))))
    actions=defaultdict(list);scales=defaultdict(dict);resolved=defaultdict(list);paths=[]
    def read(p):paths.append(p);return json.loads(p.read_text())
    def add(day,event,t,kind,**terms):actions[day].append(rep.Action(event,t,kind,terms))
    for r in read(stage/'corporate/output/ledger.json'):
        if r['ex_date'] in lookup:
            add(r['ex_date'],r['event_id'],r['ticker'],'cash_dividend',per_share=r['per_share_krw'],due=252+dates.searchsorted(pd.Timestamp(r['payment_date'])))
    for r in read(stage/'review/split_primary_resolutions.json')['resolutions']:
        if not r['replay_ready']:continue
        v=r['verified'];day=v['legal_effective_date'];t=r['ticker'];ratio=Fraction(v['ratio_numerator'],v['ratio_denominator'])
        if day in lookup:
            add(day,r['event_id'],t,'split',ratio=ratio);scales[day][t]=ratio;resolved[t].append(day)
    for r in read(stage/'corporate/output/kis_reconciliation.json')['bonus_issues']:
        day=r['ex_right_date_KIS'];delivery=r['listing_date_KIS'];t=r['ticker']
        agreed=any(x['ratio_matches'] and x['delivery_matches'] for x in r['issuer_bonus_matches'])
        if day not in lookup or delivery not in lookup or not agreed:continue
        ratio=Fraction(r['ratio_from_percent_diagnostic'])
        add(day,f'verified-bonus-{t}-{day}',t,'bonus',ratio=ratio,due=lookup[delivery]);scales[day][t]=1+ratio;resolved[t].append(day)
    if include_material:
        path=root/'confirmed_actions.csv';paths.append(path)
        for r in pd.read_csv(path,dtype=str,keep_default_na=False).itertuples(index=False):
            if r.date not in lookup:continue
            if r.ticker in scales[r.date]:raise ValueError('Duplicate confirmed unit event')
            ratio=Fraction(r.ratio);terms={'ratio':ratio}
            if r.kind=='bonus':terms['due']=lookup[r.delivery]
            add(r.date,f'verified-material-{r.ticker}-{r.date}',r.ticker,r.kind,**terms)
            scales[r.date][r.ticker]=ratio if r.kind=='split' else 1+ratio;resolved[r.ticker].append(r.date)
    unknown=defaultdict(list)
    for r in read(stage/'corporate/output/unresolved.json'):
        day=r['ex_date'];i=dates.searchsorted(pd.Timestamp(day));t=r['ticker']
        if i==len(ids) or pd.Timestamp(day)<dates[0]:continue
        if r['kind'] in ('무상증자','공급자 분할비율','액면분할') and any(abs((pd.Timestamp(x)-pd.Timestamp(day)).days)<=7 for x in resolved[t]):continue
        unknown[ids[i]].append(r)
    return actions,scales,unknown,paths


def run(root,signal_path,membership_path,feature_dir,out,cohort):
    out.mkdir(parents=True,exist_ok=False)
    if digest(signal_path)!=SIGNAL_HASH or digest(membership_path)!=MEMBERSHIP_HASH:raise ValueError('PIT input hash changed')
    verify_feature_files(feature_dir)
    ex,rep=load_account(root/'code');inp=root/'inputs';stage=inp/'v1_ca_stage'
    manifest=json.loads((feature_dir/'manifest.json').read_text());cfg=manifest['config'];fixed=manifest['ordered_fixed'];ids=manifest['sessions'];lookup=dict(zip(ids,range(252,252+len(ids))))
    signal=json.loads(gzip.decompress(signal_path.read_bytes()))
    assert signal['manifest']['config']==cfg and signal['summary']['pit_proxy_candidates']==96382
    if cohort=='PIT':
        universe=json.loads(gzip.decompress(membership_path.read_bytes()))
        allowed={r['date']:{x['code'] for x in r['members']} for r in universe['daily_membership']}
        isin={(r['date'],x['code']):x['isin'] for r in universe['daily_membership'] for x in r['members']}
        del universe
        candidate_rows=signal['signals']
        rows=pd.read_parquet(feature_dir/'proxy_features.parquet').rename(columns={'Date':'date'})
    else:
        allowed={d:set(fixed) for d in ids};isin={}
        b=json.loads((stage/'review/frozen_candidate_batches.json').read_text())
        candidate_rows=[dict(date=x['first_date'],code=x['ticker'],rs=x['rs']) for x in b]
        quote_path=inp/'v1_kis_history_results/evidence/normalized.csv'
        expected=json.loads((stage/'INTEGRATED_PREFLIGHT.json').read_text())['frozen']['normalized_sha256']
        if digest(quote_path)!=expected:raise ValueError('Frozen KIS quote hash changed')
        raw=pd.read_csv(quote_path,dtype={'ticker':str,'date':str})
        rows=raw[raw.ticker.isin(fixed)].rename(columns={'ticker':'Code','open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
        rows['MarketId']='FIXED_REFERENCE';rows['Changes']=np.nan
    del signal
    rows['date']=pd.to_datetime(rows.date).dt.strftime('%Y%m%d');rows=rows[rows.date.isin(ids)]
    assert not rows.duplicated(['date','Code']).any()
    groups={d:g for d,g in rows.groupby('date',sort=False)}
    batches=defaultdict(list)
    for r in candidate_rows:
        day=r['date'];batches[day].append(SimpleNamespace(ticker=r['code'],rs=float(r['rs']),signal_i=lookup[day]-1,extra={}))
    class MembershipReplay(rep.Replay):
        allowed_buys=frozenset()
        def add_candidates(self,day):
            for c in day.candidates:
                if c.ticker not in self.allowed_buys:self.book.event('candidate_ineligible_open',c.ticker,reason='absent_official_common_KOSPI')
            return super().add_candidates(replace(day,candidates=tuple(c for c in day.candidates if c.ticker in self.allowed_buys)))
        def submit_buys(self,day,prefunded=None):
            return super().submit_buys(replace(day,quotes={t:q for t,q in day.quotes.items() if t in self.allowed_buys}),prefunded)
        def fill(self,day,key,*args):
            o=self.book.orders[key]
            if o.side=='BUY' and o.ticker not in self.allowed_buys:raise AssertionError('Non-PIT purchase')
            return super().fill(day,key,*args)
    modes={m:MembershipReplay(m,cfg['risk'],cfg['cooldown_days']) for m in ['D1','D2']}
    actions,scales,unknown,paths=actions_from_preserved(root,ids,rep,cohort=='PIT')
    last={};events=[];holdings=[];order_audit=[];applied=[];first_uncertain={};observed_end=rows.groupby('Code').date.max().to_dict();ended_logged=set()
    for iso in ids:
        day=pd.Timestamp(iso);i=lookup[iso];dayrows=groups.get(iso,rows.iloc[:0]);current={r.Code:int(r.Close) for r in dayrows.itertuples(index=False) if valid_row(r)}
        prior_unscaled=last.copy()
        for t,factor in scales[iso].items():
            if t in last:last[t]=max(1,int(Fraction(last[t])/factor))
        indexed={r.Code:r for r in dayrows.itertuples(index=False)}
        for mode,replay in modes.items():
            replay.allowed_buys=allowed[iso];book=replay.book
            relevant=set(c.ticker for c in batches[iso])|set(book.positions)|set(replay.pending)|book.share_right_tickers
            relevant.update(getattr(x,'asset','') for x in book.derived_assets.values());relevant.discard('')
            quotes,states=make_quotes(dayrows,last,relevant,mode,iso,ex,rep)
            previous=float(replay.daily[-1]['priced_asset_subtotal']) if replay.daily else 100_000_000
            risks=list(unknown[iso]);before={t:p.shares for t,p in book.positions.items()}
            for t,p in book.positions.items():
                row=indexed.get(t);q=quotes.get(t)
                if row is not None and q and q.opening and t in prior_unscaled and t not in scales[iso]:
                    if abs(q.opening/prior_unscaled[t]-1)>.31:risks.append(dict(ticker=t,event_id=f'gap-{t}-{iso}',kind='opening_gap_gt_31pct'))
                    if cohort=='PIT' and np.isfinite(row.Changes):
                        base=int(row.Close-row.Changes)
                        if abs(base-prior_unscaled[t])>max(1,prior_unscaled[t]*.001):risks.append(dict(ticker=t,event_id=f'base-{t}-{iso}',kind='unverified_comparison_base'))
                if observed_end.get(t,'99999999')<iso and (mode,t) not in ended_logged:
                    ended_logged.add((mode,t));risks.append(dict(ticker=t,event_id=f'end-{t}-{iso}',kind='holding_after_final_observed_quote'))
            for r in risks:
                t=r['ticker'];p=book.positions.get(t);rights=sum(x.quantity for x in book.rights if x.ticker==t)
                if not p and not rights:continue
                exposure=((p.shares if p else 0)+rights)*prior_unscaled.get(t,0)
                events.append(dict(cohort=cohort,mode=mode,date=iso,ticker=t,event_id=r['event_id'],kind=r['kind'],shares=p.shares if p else 0,exposure_krw=exposure,prior_nav_share=exposure/previous if previous else None,
                    disposition='UNRESOLVED_no_fabricated_terms_or_settlement',impact='Material' if previous and exposure/previous>=.01 else 'LOW_EXPOSURE_NOT_A_RETURN_BOUND'))
                first_uncertain.setdefault(mode,iso)
            for a in actions[iso]:
                if a.ticker in book.positions:
                    p=book.positions[a.ticker];applied.append(dict(cohort=cohort,mode=mode,date=iso,ticker=a.ticker,event_id=a.event_id,kind=a.kind,shares_before=p.shares,entry_before=p.entry,peak_before=p.peak,terms=str(a.terms)))
            start=len(book.log)
            replay.step(rep.Day(i,day.date(),quotes,tuple(batches[iso]),tuple(actions[iso]),{t:last[t] for t in relevant if t in last},states))
            for e in book.log[start:]:
                if e['event']=='split' and not e['quantity'] and e['ticker'] not in book.share_right_tickers:
                    replay.exits.pop(e['ticker'],None);replay.entries.pop(e['ticker'],None)
                if e['event']=='submitted':
                    q=quotes.get(e['ticker']);order_audit.append(dict(mode=mode,date=iso,ticker=e['ticker'],side=e['side'],order_id=e['order_id'],quantity=e['quantity'],limit=e.get('limit'),preopen_reference=q.reference if q else None,reference_source='prior_observed_close_or_preknown_verified_action_base' if mode=='D2' else 'observed_open_DIAGNOSTIC',conditional_fill_model=True))
                if e['event']=='filled':
                    row=indexed.get(e['ticker']);assert row is not None and valid_row(row) and int(row.Open)==e['price']
                    e['execution_evidence']='CONDITIONAL_DAILY_BAR_FULL_FILL_NOT_BROKER_CONFIRMED'
                    e['account_path_status']='UNVERIFIED_AFTER_MATERIAL_EVENT' if mode in first_uncertain else 'KNOWN_INPUT_CONDITIONAL_PATH'
            daily=replay.daily[-1]
            subtotal=sum((daily[k] for k in ['cash','stock','receivable','undelivered','derived_stock','distinct_pending']),D(0))
            daily['priced_asset_subtotal']=subtotal
            daily['first_material_uncertainty']=first_uncertain.get(mode,'')
            daily['certified_total_nav']=None # Even undetected rights need a coverage inventory.
            daily['coverage']='FIXED_PRESERVED_SCOPE' if cohort=='FIXED' else 'PIT_SIGNAL_PROXY_AND_NONFIXED_ACTION_DIVIDEND_COVERAGE_INCOMPLETE'
            if daily['nav'] is not None:ex.reconcile(daily['nav'],subtotal)
            if book.cash<0 or book.reserved>book.cash or book.free<0:raise AssertionError('Account invariant')
            for t,p in book.positions.items():
                holdings.append(dict(mode=mode,date=iso,ticker=t,isin=isin.get((iso,t),''),shares=p.shares,entry=p.entry,peak=p.peak,entry_session=replay.entries.get(t),exit_intent=replay.exits.get(t,''),tradable_bar=states.get(t)=='TRADABLE',mark=current.get(t,last.get(t)),mark_stale=t not in current,
                    action_inventory='preserved_162_only_scope' if t in fixed else 'NOT_COMPLETE_no_event_is_not_proof_of_no_action'))
        last.update(current)
        if (i-251)%500==0:print(f'PATH_PROGRESS cohort={cohort} date={iso}',flush=True)
    for mode,replay in modes.items():
        pd.DataFrame(replay.daily).to_csv(out/f'{mode}_daily.csv',index=False)
        pd.DataFrame(replay.book.log).to_csv(out/f'{mode}_ledger.csv',index=False)
        rights=[dict(ticker=x.ticker,quantity=x.quantity,cash=x.cash,due=x.due,kind=x.kind,event_id=x.event_id) for x in replay.book.rights]
        (out/f'{mode}_ending_state.json').write_text(json.dumps(dict(cash=str(replay.book.cash),positions={t:dict(shares=p.shares,entry=str(p.entry),peak=str(p.peak)) for t,p in replay.book.positions.items()},rights=rights,unpriced_fraction_events=list(replay.book.fraction_rights),pending=replay.pending,exits=replay.exits,last_exit=replay.last_exit),default=str,indent=2))
    for name,records in [('holdings',holdings),('order_audit',order_audit),('material_events',events),('applied_actions',applied)]:pd.DataFrame(records).to_csv(out/f'{name}.csv',index=False)
    run_manifest=dict(cohort=cohort,config=cfg,source_hashes={str(p):digest(p) for p in paths},account_hashes=ACCOUNT_HASH,runner_sha256=digest(__file__),signal_sha256=digest(signal_path),membership_sha256=digest(membership_path),feature_manifest_sha256=digest(feature_dir/'manifest.json'),
        first_material_uncertainty=first_uncertain,execution='same preserved D1/D2 policy; D2 quote sizing availability independent of future OHLCV; eligible opening full-fill is conditional',omissions='Unverified rights NOT assumed settled or worth zero. Priced asset subtotal excludes unquantifiable rights and is not a certified NAV or a lower bound after path changes.',terminal='closing mark, no forced liquidation',paths_complete=True)
    (out/'run_manifest.json').write_text(json.dumps(run_manifest,ensure_ascii=False,indent=2))
    print('PATH_COMPLETE '+json.dumps(dict(cohort=cohort,sessions=len(ids),held_action_rows=len(applied),unresolved_rows=len(events),first_material_uncertainty=first_uncertain),sort_keys=True),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('signals',type=Path);p.add_argument('membership',type=Path);p.add_argument('features',type=Path);p.add_argument('out',type=Path);p.add_argument('--cohort',choices=['FIXED','PIT'],required=True)
    a=p.parse_args();run(a.root,a.signals,a.membership,a.features,a.out,a.cohort)
