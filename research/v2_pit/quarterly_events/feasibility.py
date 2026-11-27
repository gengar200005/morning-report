"""Bound the filing acquisition cost before any prices or future returns are read."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from fractions import Fraction
import gzip
from hashlib import file_digest, sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import sqlite3
from zlib import decompress
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from filing_xbrl import parse_instance
from stage82b.limited_panel import PER_MONTH, SALT
from stage9_panel.pit_facts import inspect_xbrl
from stage9_panel.recovery_raw_facts import filing_header

CENSUS = ROOT / 'stage82b'
COMMON = ('KOSPI', '주권', '보통주')
BUDGET = 100
HORIZONS = (20, 60, 120)
# Non-weekend public holidays that can intersect the deadline roll.
HOLIDAYS = {date(2021, 8, 16)}


def digest(body):
    return sha256(body).hexdigest()


def sha_file(path):
    with path.open('rb') as file:
        return file_digest(file, 'sha256').hexdigest()


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file))


def csv_output(path, records):
    with path.open('w', encoding='utf-8', newline='') as file:
        out = csv.DictWriter(file, fieldnames=list(records[0]), lineterminator='\n')
        out.writeheader()
        out.writerows(records)


def standard_deadline(end):
    limit = end + timedelta(days=45)
    while limit.weekday() >= 5 or limit in HOLIDAYS:
        limit += timedelta(days=1)
    return limit.strftime('%Y%m%d')


def schedule(sessions):
    for year in range(2017, 2022):
        for quarter, md in enumerate(((3,31), (6,30), (9,30)), 1):
            end = date(year, *md)
            limit = standard_deadline(end)
            i = bisect_right(sessions, limit)
            formation, entry = sessions[i:i+2]
            horizons = {h: sessions[i+h] if i+h < len(sessions) else None for h in HORIZONS}
            yield (f'{year}Q{quarter}', end.isoformat(), limit, formation, entry, horizons)


def load_market(path):
    days, proxy, fields = {}, {}, defaultdict(set)
    with ZipFile(path) as z:
        sources = json.loads(z.read('context_sources.json'))
        ctx = list(csv.DictReader(StringIO(z.read('context.csv').decode())))
        for row in ctx:
            proxy[row['formation'], row['isin']] = (row['industry_group'],row['cap_quartile'])
        for start, meta in sorted(sources.items()):
            raw = z.read('krx/' + meta['krx'])
            if digest(raw) != meta['sha256']:
                raise ValueError('KRX source drift')
            for daily in json.loads(gzip.decompress(raw))['records']:
                day = daily['date']
                if day in days or day[:6] != start[:6]:
                    raise ValueError('Duplicated or misplaced session')
                basic = daily['basic']
                if basic:
                    fields['basic'].update(basic[0])
                if daily['daily']:
                    fields['daily'].update(daily['daily'][0])
                days[day] = basic
    return days, proxy, {k:sorted(v) for k,v in fields.items()}


def get_roster(basic):
    universe = [r for r in basic if (r['MKT_TP_NM'],r['SECUGRP_NM'],r['KIND_STKCERT_TP_NM']) == COMMON]
    if len(universe) < PER_MONTH or len({r['ISU_CD'] for r in universe}) != len(universe):
        raise ValueError('Historical KRX universe incomplete')
    return universe, sorted(universe, key=lambda r: (digest((SALT+r['ISU_CD']).encode()),r['ISU_CD']))[:PER_MONTH]


def normalize_name(value):
    return re.sub(r'[^A-Za-z0-9가-힣]', '', value.replace('주식회사','').replace('(주)','')
                  .replace('㈜','')).lower()


def raw_names(payload):
    with ZipFile(BytesIO(payload)) as z:
        member, = [n for n in z.namelist() if n.lower().endswith('.xbrl')]
        root, _ = parse_instance(z.read(member))
    return {normalize_name(n.text) for n in root if n.tag.endswith('}EntityRegistrantName') and n.text}


def integer(value):
    return int(value) if value is not None and value != '' else None


def signal_pair(revenue, op):
    c,p = map(integer, revenue)
    x,y = map(integer, op)
    f3 = p is not None and p > 0 and c is not None and c >= 0
    f2 = f3 and c > 0 and x is not None and y is not None
    return (str(Fraction(c,p)-1) if f3 else '', str(100*(Fraction(x,c)-Fraction(y,p))) if f2 else '')


def load_stage82(archive_path, cache):
    root_zip = ZipFile(archive_path)
    manifest = json.loads(root_zip.read('MANIFEST.json'))['files']
    def verified(name):
        body = root_zip.read(name)
        if digest(body) != manifest[name]['sha256']:
            raise ValueError('Prior bundle hash mismatch ' + name)
        return body
    xbrl = {}
    for name in ('xbrl/portal.sqlite','xbrl/amendments.sqlite'):
        f = cache / Path(name).name
        f.write_bytes(verified(name))
        with sqlite3.connect(f.resolve().as_uri()+'?mode=ro', uri=True) as db:
            for rid, corp, h, doc, body in db.execute('SELECT receipt,corp,sha,document,raw FROM originals'):
                if digest(body) != h or rid in xbrl:
                    raise ValueError('Prior XBRL mismatch or duplicate')
                xbrl[rid] = corp,h,doc,body
    f = cache / 'kind.sqlite'
    f.write_bytes(verified('kind/filings.sqlite'))
    with sqlite3.connect(f.resolve().as_uri()+'?mode=ro', uri=True) as db:
        kind = set()
        for url,h,body in db.execute('SELECT url,hash,raw FROM page WHERE url LIKE ?', ('%/external/%',)):
            if digest(decompress(body)) != h:
                raise ValueError('Prior KIND mismatch ' + url)
            kind.add(h)
    extras = {}
    historical = {r['stock_code']:r for r in json.loads(
        (CENSUS/'historical_access_preflight.json').read_text())['samples']}
    for name in root_zip.namelist():
        if not (name.startswith(('quarter_holdouts/','historical_access/','holdout/')) and name.endswith(('.zip','.htm'))):
            continue
        match = re.search(r'(\d{14})\.', name)
        if match:
            key = name
            rid = match[1]
        elif name.startswith('historical_access/') and name.endswith('.zip'):
            key = name
            rid = historical[name.split('-')[-1].split('.')[0]]['receipt']
        else:
            continue
        body = verified(name)
        extras[key] = (rid,digest(body))
    root_zip.close()
    return xbrl,kind,extras


def census_at(d, xbrl, kind):
    direct = {r['isin']:r for r in rows(CENSUS/'census_rows.csv')}
    versions = defaultdict(list)
    for row in json.loads((CENSUS/'census_amendments.json').read_text())['bounded_version_rows']:
        versions[row['isin']].append(row)
    def select(isin):
        r = direct.get(isin)
        if not r or r['identity_status'] != 'PASS' or not r['next_krx_session'] or r['next_krx_session'] > d:
            return {}
        active = [v for v in versions[isin] if v['start_session'] and v['start_session'] <= d and
                  (not v['stop_session_exclusive'] or d < v['stop_session_exclusive'])]
        if len(active)>1 or (versions[isin] and not active):
            return {}
        if active and active[0]['version'] != 'original':
            v, = active
            if v.get('same_day_quarantined') or not v.get('bounded_to') or v['bounded_to'] < d:
                return {}
            rid, pub, h = v['receipt'], v['filed'], v['sha256']
            revenue,op = v['revenue'] or ('',''),v['operating_profit'] or ('','')
        else:
            if r['verified_original_version'] != 'True':
                return {}
            rid, pub = r['receipt'],r['original_filed']
            h = r['xbrl_source_sha256'] or r['display_source_sha256']
            if not r['xbrl_source_sha256'] or (r['revenue_evidence']!='XBRL' and r['F3_original_pair_QC']=='PASS'):
                h = r['display_source_sha256'] or h
            if r['source_report_type'] != 'Q1':
                return {}
            revenue = [r[f'revenue_{k}_KRW'] for k in ('current','prior')] if r['F3_original_pair_QC']=='PASS' else ['','']
            op = [r[f'operating_profit_{k}_KRW'] for k in ('current','prior')] if r['F2_original_pair_QC']=='PASS' else ['','']
        # A date-only DART record is admitted from the next session. Use the
        # archived cut + scope without treating any other issuer as resolved.
        if not rid or pub >= d:
            return {}
        if not h or not ((rid in xbrl and h==xbrl[rid][1] and xbrl[rid][0]==r['corp_code']) or h in kind):
            revenue=op=('','')
        f3,f2 = signal_pair(revenue,op)
        return dict(candidate_isin=isin, issuer=r['corp_code'], receipt=rid, filed=pub, sha256=h,
                    F3=f3,F2=f2,revenue_current=revenue[0],revenue_prior=revenue[1],
                    op_current=op[0],op_prior=op[1])
    return select


def coverage_envelope(upper, proxy_n):
    room = min(PER_MONTH, upper+BUDGET)
    return dict(archived_possible_upper=upper, potential_after_100=room,
                largest_denominator_at_80pct=5*room//4,
                marginal_cost_with_proxy=max(0,(4*proxy_n+4)//5-upper))


def run(args):
    out = args.destination
    out.mkdir(parents=True, exist_ok=True)
    days, proxy, fields = load_market(args.market)
    sessions = sorted(days)
    exits = {(r['Symbol'],r['ListingDate'][:10].replace('-','')):r['DelistingDate'][:10].replace('-','')
             for r in rows(args.exits) if (r['Market'],r['SecuGroup'],r['Kind'])==COMMON}
    snapshot_dates = sorted({d for d,_ in proxy})
    facts = rows(args.facts)
    period_facts = defaultdict(list)
    for row in facts:
        if row['status']=='parsed':
            period_facts[row['period_end']].append(row)
    verified_period = {r['receipt']:r['period_end'] for r in facts if r['status']=='parsed'}
    stage9_audits = json.loads((ROOT/'stage9_panel/audit_main_summary.json').read_text())['rows']
    stage9_extra = {r['original_receipt']:r['evidence'] for r in stage9_audits}
    stage9_extra.update({r['receipt']:r['body_sha256'] for r in json.loads(
        (ROOT/'stage9_panel/recovery_2018_issuer.json').read_text())['rows']})
    stage9_extra.update({r['receipt']:r['sources'][0]['sha256'] for r in json.loads(
        (ROOT/'stage9_panel/audit_daily_version_result.json').read_text())['reports']})
    marks = []
    roster_rows = []
    cut_rows = []
    audit_pool = defaultdict(list)
    screened_raw_xbrl = set()
    with TemporaryDirectory() as cache, ZipFile(args.raw) as raw:
        xbrl,kind,extras=load_stage82(args.prior,Path(cache))
        raw_count=len(raw.namelist())
        raw_members={}
        raw_scope=set()
        for member in raw.namelist():
            rid, tail = member.split('/')
            raw_scope.add(rid)
            if tail.startswith('xbrl-'):
                raw_members[rid] = member
        for quarter,end,deadline,formation,entry,horizons in schedule(sessions):
            universe, selected = get_roster(days[formation])
            previous = snapshot_dates[bisect_right(snapshot_dates,formation)-1]
            quarter_scope={(r,h) for r,h in extras.values() if end.replace('-','')<r[:8]<=formation}
            quarter_scope.update((r,h) for r,h in stage9_extra.items() if end.replace('-','')<r[:8]<=formation)
            upper = len({r for r,_ in quarter_scope}|{r for r in raw_scope|xbrl.keys()
                           if end.replace('-','')<r[:8]<=formation
                           and (r not in verified_period or verified_period[r]==end)})
            if quarter=='2021Q1':
                # The archive has hundreds of KIND-only sources in this window.
                upper=PER_MONTH
            by_name=defaultdict(list)
            for fact in period_facts[end]:
                rid=fact['receipt']
                if rid[:8]>formation:
                    continue
                body=raw.read(raw_members[rid])
                screened_raw_xbrl.add(rid)
                if digest(body)!=fact['source_sha256']:
                    raise ValueError('Derived facts differ from raw body')
                for name in raw_names(body):
                    by_name[name].append(fact)
            choose_census=census_at(formation,xbrl,kind) if quarter=='2021Q1' else None
            stats = Counter()
            groups = defaultdict(Counter)
            for rank,r in enumerate(selected,1):
                isin,code=r['ISU_CD'],r['ISU_SRT_CD']
                sector,cap=proxy.get((previous,isin),('unknown',''))
                later=exits.get((code,r['LIST_DD']),'')
                later_exit=bool(later and later>formation)
                row=dict(quarter=quarter,formation=formation,rank=rank,isin=isin,code=code,
                         name=r['ISU_ABBRV'],listed=r['LIST_DD'],previous_industry=sector,
                         later_exit=bool(later_exit),previous_cap_quartile=cap, previous_sector_date=previous)
                roster_rows.append(row)
                stats[sector]+=1
                if sector=='nonfinancial':
                    stats['applicable']+=1
                matches=by_name[normalize_name(r['ISU_ABBRV'])]
                known = [f for f in matches if f['receipt'][:8]<formation]
                matching_issuer = {f['issuer'] for f in known}
                candidate = max(known,key=lambda f:f['receipt']) if len(matching_issuer)==1 else {}
                exact = choose_census(isin) if choose_census else {}
                stats['census_identity']+=bool(exact)
                f3,f2=signal_pair([candidate.get('revenue_current'),candidate.get('revenue_prior')],
                                  [candidate.get('operating_profit_current'),candidate.get('operating_profit_prior')])
                if not candidate:
                    f3=f2=''
                if sector=='nonfinancial':
                    dims=['all','later_exit' if later_exit else 'other', 'cap_'+(cap or 'unknown')]
                    for dim in dims:
                        g=groups[dim]
                        g['denominator']+=1
                        g['XBRL_candidate_receipt']+=bool(candidate)
                        g['XBRL_candidate_F3']+=bool(f3)
                        g['XBRL_candidate_F2']+=bool(f2)
                        g['census_identity']+=bool(exact)
                        g['census_F3']+=bool(exact.get('F3'))
                        g['census_F2']+=bool(exact.get('F2'))
                    if exact and exact.get('F2') and exact['receipt'] in xbrl and exact['sha256']==xbrl[exact['receipt']][1]:
                        audit_pool['later_exit' if later_exit else 'other'].append((row,exact))
                cut_rows.append({**row,'name_match_only_receipt':candidate.get('receipt',''),
                                 'name_match_only_filing_issuer':candidate.get('issuer',''),
                                 'name_match_only_sha256':candidate.get('source_sha256',''),
                                 'name_match_only_F3':f3,'name_match_only_F2':f2,
                                 **{f'census_{k}':exact.get(k,'') for k in
                                     ('receipt','issuer','filed','sha256','F3','F2','revenue_current','revenue_prior','op_current','op_prior')}})
            marks.append(dict(quarter=quarter,period=end,ordinary_population=len(universe),deadline=deadline,
                              formation=formation,entry=entry,horizon_end=horizons,previous_sector_date=previous,
                              proxy_industry={k:stats[k] for k in ('nonfinancial','financial','unknown')},
                              diagnostics=dict(groups),identity_sample_count=stats['census_identity'] if choose_census else None,
                              count_certified_PIT=None,**coverage_envelope(upper,stats['nonfinancial'])))
        checked = []
        for label,n in [('later_exit',3),('other',5)]:
            pick = sorted(audit_pool[label],key=lambda t:digest(('quarterly-replay-v1|'+t[0]['isin']).encode()))[:n]
            for r,v in pick:
                corp,h,doc,body=xbrl[v['receipt']]
                observed,period,amend=filing_header(body)
                raw_parsed=inspect_xbrl(body,corp,period)['3']
                expected=(v['revenue_current'],v['revenue_prior'],v['op_current'],v['op_prior'])
                found=tuple(raw_parsed[k].get('value') for k in ('revenue_current','revenue_prior','operating_profit_current','operating_profit_prior'))
                checked.append(dict(quarter=r['quarter'],isin=r['isin'],stratum=label,receipt=v['receipt'],doc=doc,
                                    source_sha256=h,filed=v['filed'],metadata_correct=observed==corp==v['issuer']
                                    and period.isoformat()=='2021-03-31' and v['filed']<r['formation'],
                                    amounts_match=tuple(map(int,expected))==found, expected=expected, replayed=found))
    csv_output(out/'formation_roster.csv',roster_rows)
    csv_output(out/'filing_recovery_ledger.csv',cut_rows)
    (out/'source_audit.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2)+'\n')
    cost = sorted(m['marginal_cost_with_proxy'] for m in marks if m['horizon_end'][120])
    plausible=sum(x['marginal_cost_with_proxy']<=BUDGET for x in marks if x['horizon_end'][120])
    reduced_cost = sorted(max(0,(4*max(0,m['proxy_industry']['nonfinancial']-50)+4)//5
                              -m['archived_possible_upper']) for m in marks if m['horizon_end'][120])
    summary=dict(archive_hashes={k:sha_file(getattr(args,k)) for k in ('market','raw','prior','facts','exits')},
                 row_hashes={k:sha_file(out/k) for k in ('formation_roster.csv','filing_recovery_ledger.csv','source_audit.json')},
                 formations=marks, market_schema_fields=fields, sessions=len(sessions), budget=BUDGET,
                 source_reuse=dict(raw_archive_receipts=len(raw_scope), raw_archive_files=raw_count,
                                   raw_xbrl_screened_in_candidate_windows=len(screened_raw_xbrl), prior_xbrl_receipts=len(xbrl),
                                   prior_kind_unique_external_hashes=len(kind), prior_other_payloads=len(extras)),
                 cost_scope='Optimistic stock-quarters. Any dated retained receipt in the window may supply one successful issuer. Same-date uses admitted for the upper bound. Existing accounting and identity checks can only reduce these estimates. Prior WICS classifications approximate the nonfinancial count.',
                 max_possible_120_individual_under_cost_proxy=plausible,
                 cheapest_six_cost_proxy=sum(cost[:6]), cheapest_six_cost_if_50_more_ineligible_each_date=sum(reduced_cost[:6]),
                 new_filing_payloads=0,outcomes_read=False,
                 audited_documents=len(checked), audited_cells=4*len(checked),
                 audit_mismatches=sum(not c['metadata_correct'] or not c['amounts_match'] for c in checked))
    (out/'feasibility_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('market','raw','prior','facts','exits','destination'):
        parser.add_argument(field,type=Path)
    run(parser.parse_args())
