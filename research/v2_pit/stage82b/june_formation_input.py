"""Construct the preregistered June cross-section using only formation-time records."""
import argparse
from collections import Counter
import csv
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
import re


def csv_index(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    indexed = {r['isin']: r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError('Duplicate ISIN in formation inputs')
    return indexed


def source_digest(hashes):
    entries = sorted(set(hashes.split('|')))
    if not all(re.fullmatch(r'[0-9a-f]{64}', s) for s in entries):
        raise ValueError('Missing or malformed source SHA-256')
    if len(entries) == 1:
        return entries[0]
    return sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()


def build(census, context, reviewed, output):
    old, today = csv_index(census), csv_index(context)
    review = json.loads(reviewed.read_text())['decisions']
    changes = {r['isin']: r for r in review}
    if (len(old), len(today)) != (782, 785) or not (today.keys() - old.keys()) <= changes.keys():
        raise ValueError('Unverified historical universe or additions')
    records = []
    for isin, member in today.items():
        wics = member['sector_code']
        group = 'unknown' if not wics else 'financial' if wics == 'G40' else 'nonfinancial'
        obs = old.get(isin, {})
        override = changes.get(isin, {})
        if override.get('action') == 'replace':
            obs = override['observation']
        rec = dict(isin=isin, stock_code=member['stock_code'], company=member['issuer'],
                   sector_code=wics, sector_name=member['sector_name'], industry_group=group,
                   quarter_end=obs.get('quarter_end',''), receipt=obs.get('receipt',''),
                   published_date=obs.get('published',''), available_session=obs.get('available_session',''),
                   source_sha256='', all_source_sha256=obs.get('sha256',''), source_urls=obs.get('source',''),
                   status='', F2='', F3='')
        if rec['all_source_sha256']:
            rec['source_sha256'] = source_digest(rec['all_source_sha256'])
        if override.get('action') == 'quarantine':
            status = override['reason']
        elif group != 'nonfinancial':
            status = 'sector_' + group
        elif obs.get('identity_status') != 'PASS' or not obs.get('receipt'):
            status = obs.get('F3_status') or 'identity_or_filing_unconfirmed'
        elif obs['revenue_reason'] != 'PASS':
            status = obs['revenue_reason'] or 'revenue_pair_unavailable'
        elif not rec['source_sha256'] or not ('20201203' <= rec['quarter_end'] <= rec['published_date'] < rec['available_session'] <= '20210601'):
            raise ValueError('Evidence/version window conflict for ' + isin)
        else:
            with localcontext() as ctx:
                ctx.prec = 40
                c, p = (Decimal(obs['revenue_'+period+'_KRW']) for period in ('current','prior'))
                if c >= 0 and p > 0:
                    rec['F3'] = str(c/p-1)
                    if c > 0 and obs['operating_profit_reason'] == 'PASS':
                        cur, prev = (Decimal(obs['operating_profit_'+period+'_KRW']) for period in ('current','prior'))
                        rec['F2'] = str(100*(cur/c-prev/p))
            status = 'PASS' if rec['F3'] else 'nonpositive_revenue_base'
        if not override and group == obs.get('industry_20210331') == 'nonfinancial':
            for name, column in [('F2', 'F2_pp'), ('F3', 'F3_fraction')]:
                if (obs[name+'_status'] == 'PASS') != bool(rec[name]):
                    raise ValueError('Changed established eligibility: ' + isin)
                if rec[name]:
                    original = Decimal(obs[column])
                    if abs(Decimal(rec[name]) - original) > max(Decimal('1e-12'), abs(original)*Decimal('1e-13')):
                        raise ValueError('Recomputed value differs from reviewed census: ' + isin)
        rec['status'] = status
        records.append(rec)
    with output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    return dict(population=len(records), F2=sum(bool(r['F2']) for r in records),
                F3=sum(bool(r['F3']) for r in records), status=dict(Counter(r['status'] for r in records)),
                sha256=sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('census','context','reviewed','output'):
        parser.add_argument(name, type=Path)
    print(json.dumps(build(**vars(parser.parse_args())), ensure_ascii=False, indent=2))
