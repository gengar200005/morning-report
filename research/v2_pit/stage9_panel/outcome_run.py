"""Calculate 2017–21 fixed-panel outcomes only after independently approved data-quality gates."""
import argparse
from bisect import bisect_right
from collections import defaultdict
import csv
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import io
import json
import math
import os
import re
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from outcome_summary import HORIZONS, analyze, calendar
from single_formation import digest
from momentum_study import load_actions, outcome
from kodex_benchmark import day as etf_day

ROOT=Path(__file__).resolve().parents[1]
START,END='20170101','20211231'


def load_input(a):
    gate=json.loads(a.gate.read_text())
    fields=gate.get('passed_signals',[])
    if (not a.release_outcomes or gate.get('phase')!='development' or gate.get('data_quality_pass') is not True
            or gate.get('asof_complete') is not True or not fields or len(fields)!=len(set(fields))
            or not set(fields)<={'F2','F3'}):
        raise ValueError('Phase, independent gates or explicit outcome release missing')
    for k in ('asof','context','sample','rates'):
        if digest(getattr(a,k))!=gate.get(k+'_sha256'):
            raise ValueError(f'Gated {k} has changed')
    frozen=json.loads((ROOT/'stage82b/limited_panel_summary.json').read_text())
    if gate['sample_sha256']!=frozen['sample_sha256']:
        raise ValueError('Different fixed sample')
    with a.sample.open(newline='') as stream:
        chosen={(r['formation'],r['historical_isin']):r['historical_code'] for r in csv.DictReader(stream)}
    with a.asof.open(newline='',encoding='utf-8-sig') as stream:
        rows=list(csv.DictReader(stream))
    if len(rows)!=len(chosen) or {(r['formation'],r['isin']) for r in rows}!=chosen.keys():
        raise ValueError('Require exactly one as-of row per preselected ISIN and month')
    ctx={}
    with a.context.open(newline='',encoding='utf-8-sig') as stream:
        for r in csv.DictReader(stream):
            k=(r['formation'],r['isin'])
            if k not in chosen:
                continue
            if k in ctx or chosen[k]!=r['code']:
                raise ValueError('Historical identity mismatch in monthly context')
            ctx[k]=r
    if len(ctx)!=len(chosen):
        raise ValueError('Incomplete as-of market context')
    with a.rates.open(newline='') as stream:
        rates={}
        for r in csv.DictReader(stream):
            key=r['formation'],r['isin']
            numerator,denominator=int(r['traded_shares']),int(r['listed_shares'])
            if key in rates or numerator<0 or denominator<=0:
                raise ValueError('Invalid share turnover row')
            rates[key]=Fraction(numerator,denominator)
    if rates.keys()!=chosen.keys():
        raise ValueError('Share turnover roster differs')
    data=defaultdict(dict)
    for r in rows:
        day,i=r['formation'],r['isin'];c=ctx[(day,i)]
        item={'code':c['code'],'corp_code':r.get('corp_code',''),'cap_quartile':c.get('cap_quartile','unknown'),
              'share_turnover':rates[day,i],
              'available_session':r.get('available_session',''),'sector':c['sector_code'],'industry_group':c['industry_group'],
              'cap':int(c['cap_krw']) if c['cap_krw'] else None,
              'turnover':int(c['turnover_krw']) if c['turnover_krw'] else None}
        if c['industry_group'] not in ('financial','nonfinancial','unknown'):
            raise ValueError('Unknown industry policy value')
        if c['sampled']!='1':
            raise ValueError('Sample flag in context differs from frozen draw')
        for metric in fields:
            x=Decimal(r[metric]) if r[metric].strip() else None
            item[metric+'_reason']=r[metric+'_reason']
            if x is not None and (not x.is_finite() or item['industry_group']!='nonfinancial' or not item['sector']):
                raise ValueError('Invalid numeric or industry-eligible observation')
            if x is not None:
                if (r['status']!='PASS' or r[metric+'_reason']!='PASS' or r['identity_pass']!='1'
                        or not r['source_sha256'] or r['industry_group']!=c['industry_group']):
                    raise ValueError('Numeric signal without upstream field-level quality evidence')
                if not re.fullmatch(r'\d{8}',item['corp_code']):
                    raise ValueError('Missing unambiguous DART issuer for a numeric signal')
                available=item['available_session']
                if not re.fullmatch(r'\d{8}',available) or available>day:
                    raise ValueError('As-of signal not yet public at this formation')
            item[metric]=x
        data[day][i]=item
    for items in data.values():
        issuers=[r['corp_code'] for r in items.values() if any(r.get(f) is not None for f in fields)]
        if len(issuers)!=len(set(issuers)):
            raise ValueError('Two eligible common securities represent one issuer at formation')
    if len(data)!=60 or any(not START<=d<=END or len(rs)!=240 for d,rs in data.items()):
        raise ValueError('Unexpected calendar or monthly sample size')
    return fields,data


def csv_member(z,name):
    with z.open(name) as raw,gzip.GzipFile(fileobj=raw) as packed,io.TextIOWrapper(packed) as csvfile:
        for row in csv.DictReader(csvfile):
            day=row['day']
            if day>END:
                break
            if day>=START:
                yield row


def stage5_reference(path, sample, cal, inv):
    m4=defaultdict(dict); old={}; refs={}; by_day={r['formation']:r for r in cal}
    with ZipFile(path) as z:
        for item in inv['stage5']['members']:
            blob=z.getinfo(item['member'])
            if blob.file_size!=item['size'] or f'{blob.CRC:08x}'!=item['crc32']:
                raise ValueError('Stage 5 bundle metadata mismatch')
        for r in csv_member(z,'formations.csv.gz'):
            d,i=r['day'],r['isin']
            if d not in sample:
                raise ValueError('Unexpected Stage 5 formation')
            if i in sample[d]:
                if i in m4[d]:
                    raise ValueError('Duplicate M4')
                m4[d][i]=Decimal(r['M4'])
        for r in csv_member(z,'outcomes.csv.gz'):
            d,i,h=r['day'],r['isin'],int(r['horizon'])
            if h not in HORIZONS:
                continue
            if (r['entry'],r['exit'])!=(by_day[d]['entry'],by_day[d]['exits'][str(h)]):
                raise ValueError('Archived outcome horizon escapes development phase or differs')
            ref=(r['regime'],float(r['etf_price']) if r['etf_price'] else None,
                 float(r['etf_economic']) if r['etf_economic'] else None)
            if refs.setdefault((d,h),ref)!=ref:
                raise ValueError('Unequal archived ETF or regime on same date')
            if i not in sample[d]:
                continue
            key=d,i,h
            if key in old:
                raise ValueError('Duplicate Stage 5 observation')
            old[key]=(float(r['price']) if r['price'] else None,float(r['economic']) if r['economic'] else None,
                      r['status'],int(r['dividends']))
    return m4,old,refs


def raw_etf(path,days,cal,inv):
    """Project official input files to allowed dates before reading quote/distribution amounts."""
    with ZipFile(path) as z:
        def raw_json(name,key):
            blob=z.read(name)
            if key and hashlib.sha256(blob).hexdigest()!=inv['stage5']['expected_input_hashes'][key]:
                raise ValueError('Unrecognized raw ETF input')
            return json.loads(blob)
        primary=raw_json('inputs/yahoo_069500.json','etf')['result']
        second=raw_json('inputs/daum.json','secondary')
        if primary['meta']['symbol']!='069500.KS' or second['code']!=200:
            raise ValueError('Wrong benchmark')
        split=primary.get('events',{}).get('splits',{})
        if any(days[0]<=etf_day(s['date'])<=END for s in split.values()):
            raise ValueError('Unexpected ETF split')
        quote=primary['indicators']['quote'][0]
        prices={}
        for j,stamp in enumerate(primary['timestamp']):
            day=etf_day(stamp)
            if days[0]<=day<=END and quote['volume'][j] and quote['open'][j] and quote['close'][j]:
                prices[day]=(quote['open'][j],quote['close'][j])
        for r in second['data']:
            day=r['date'][:10].replace('-','')
            if not days[0]<=day<=END:
                continue
            if r['symbolCode']!='A069500':
                raise ValueError('Wrong secondary symbol')
            pair=(r['openingPrice'],r['tradePrice'])
            if day in prices and prices[day]!=pair:
                raise ValueError('ETF primary/secondary disagree')
            if all(pair) and r['accTradeVolume']:
                prices[day]=pair
        rights={}
        # Only extract the dated issuer-rights array; no account/NAV output is parsed.
        for item in inv['benchmark']['members']:
            if not item['member'].startswith('inputs/issuer'):
                continue
            info=z.getinfo(item['member'])
            if (info.file_size,f'{info.CRC:08x}')!=(item['size'],item['crc32']):
                raise ValueError('ETF issuer archive member changed')
            for r in raw_json(item['member'],None)['dividList']:
                record=r['basicD']
                if not days[0]<=record<=END:
                    continue
                if r['stkTicker']!='069500':
                    raise ValueError('Wrong issuer instrument')
                j=bisect_right(days,record)-2
                if j<0:
                    continue
                ex=days[j]
                if ex in rights:
                    raise ValueError('Duplicate issuer distribution')
                rights[ex]=float(r['dividA'])
    at={d:i for i,d in enumerate(days)}
    result={}
    for period in cal:
        day=period['formation'];i=at[day]
        prev=prices.get(days[i-60]) if i>=60 else None
        now=prices.get(day)
        regime=('up' if now[1]>=prev[1] else 'down') if now and prev else 'unknown'
        for h in HORIZONS:
            end=period['exits'][str(h)]
            if not end:
                continue
            entry=period['entry'];beg=prices.get(entry);last=prices.get(end)
            post_entry=sum(v for d,v in rights.items() if entry<d<=end)
            px=last[1]/beg[0]-1 if beg and last else None
            econ=(last[1]+post_entry)/beg[0]-1 if beg and last else None
            result[day,h]=(regime,px,econ)
    return result


def same(a,b):
    return (a is None and b is None) or (a is not None and b is not None and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10))


def build_market(db, data, fields, days, cal, m4, old, refs):
    sample_names={i for v in data.values() for i in v}
    db.execute('CREATE TEMP TABLE selected_isins(isin TEXT PRIMARY KEY)')
    db.executemany('INSERT INTO selected_isins VALUES(?)',[(i,) for i in sorted(sample_names)])
    # Restrict the shared Stage 5 action loader and all daily market queries to this phase.
    for table,col in [('corporate_actions','effective_date'),('exit_audit','delisted')]:
        db.execute(f"CREATE TEMP VIEW {table} AS SELECT a.* FROM main.{table} a JOIN selected_isins s ON s.isin=a.isin WHERE a.{col} BETWEEN '{START}' AND '{END}'")
    actions,exits=load_actions(db,days)
    index={d:i for i,d in enumerate(days)}
    by_isin=defaultdict(dict)
    for day,isin,op,cl,state,ref,check in db.execute("""
        SELECT m.day,m.isin,p.open,p.close,p.state,k.implied_reference_krw,k.rate_status
        FROM membership m JOIN selected_isins s USING(isin) LEFT JOIN execution_bars p USING(day,isin)
        LEFT JOIN krx_return_checks k USING(day,isin) WHERE m.day BETWEEN ? AND ?
        """,(START,END)):
        by_isin[isin][index[day]]=(op,cl,None,state,ref,check)
    market={};compared=0;outside_m4=0
    for period in cal:
        d=period['formation'];entry=index[period['entry']];eligible=data[d]
        windows={h:index[period['exits'][str(h)]] for h in HORIZONS if period['exits'][str(h)]}
        groups={h:{} for h in windows}
        for isin,r in eligible.items():
            r['subsequent_exit']='within_development_after_formation' if any(er>=index[d] for er in exits[isin]) else 'no_exit_in_remaining_development'
            if not windows or not any(r.get(f) is not None for f in fields):
                continue
            outcomes=outcome(by_isin[isin],actions[isin],exits[isin],entry,set(windows.values()))
            for h,e in windows.items():
                metrics=outcomes[e]
                if isin in m4[d]:
                    archive=old.get((d,isin,h))
                    if archive is None or metrics[2:]!=archive[2:] or not all(same(a,b) for a,b in zip(metrics[:2],archive[:2])):
                        raise ValueError('Stage 5 archived and database outcome mismatch')
                    groups[h][isin]=archive
                    compared+=1
                else:
                    groups[h][isin]=metrics
                    outside_m4+=1
        bench={h:(period['entry'],period['exits'][str(h)],*refs[d,h][1:]) for h in windows}
        regime=refs[d,next(iter(windows))][0] if windows else 'phase_end_censored'
        market[d]={'m4':m4[d],'records':groups,'benchmark':bench,'regime':regime,'signals':fields}
    return market,{'checked_stage5_observations':compared,'additional_outside_M4':outside_m4}


def run(a):
    fields,data=load_input(a)
    inv=json.loads((ROOT/'stage82b/stage5_input_inventory.json').read_text())
    if digest(a.database)!=inv['stage5']['expected_input_hashes']['database']:
        raise ValueError('Changed economic DB')
    if a.output.exists():
        raise ValueError('Use a new output directory')
    with sqlite3.connect(a.database.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        days=[r[0] for r in db.execute("SELECT day FROM sessions WHERE day BETWEEN '20160101' AND ? ORDER BY day",(END,))]
        first={}
        for d in days:
            if START<=d<=END:
                first.setdefault(d[:6],d)
        if set(first.values())!=data.keys():
            raise ValueError('Inputs are not all official first monthly sessions')
        cal=calendar(days,sorted(data))
        m4,old,archive_refs=stage5_reference(a.stage5,data,cal,inv)
        refs=raw_etf(a.stage3,days,cal,inv)
        for key,old_ref in archive_refs.items():
            actual=refs[key]
            if old_ref[0]!=actual[0] or not all(same(a,b) for a,b in zip(old_ref[1:],actual[1:])):
                raise ValueError('Archived and independent ETF returns or regime disagree')
        market,audit=build_market(db,data,fields,days,cal,m4,old,refs)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=a.output.parent) as tmp:
        p=Path(tmp)/'results'
        analyze(cal,data,market,p)
        audit.update(phase='development',last_allowed_session=END,signals=fields,months=len(cal),
                     phase_checked_etf_pairs=len(archive_refs),gate_sha256=digest(a.gate))
        (p/'audit.json').write_text(json.dumps(audit,indent=2)+'\n')
        os.rename(p,a.output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for k in ('gate','asof','context','sample','rates','database','stage5','stage3','output'):
        parser.add_argument('--'+k,type=Path,required=True)
    parser.add_argument('--release-outcomes',action='store_true')
    run(parser.parse_args())
