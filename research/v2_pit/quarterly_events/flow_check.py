"""Reconcile a bounded KRX order-flow download against dated membership."""
import argparse
import json
from pathlib import Path

from feasibility import COMMON, digest, load_market, rows


def check(market, delisting, requests, source, output):
    days, _, _ = load_market(market)
    report = []
    exits = {(r['Symbol'],r['ListingDate'][:10].replace('-','')):r['DelistingDate'][:10].replace('-','')
             for r in rows(delisting) if (r['Market'],r['SecuGroup'],r['Kind'])==COMMON}
    for req in json.loads(requests.read_text()):
        item = dict(req)
        report.append(item)
        if not req.get('rows'):
            continue
        day,kind = req['date'],req['kind']
        body = (source/f'{day}_{kind}.json').read_bytes()
        if digest(body) != req['sha256']:
            raise ValueError('Order flow source hash mismatch')
        records = json.loads(body)['output']
        mapping = {r['ISU_SRT_CD']:r for r in records}
        if len(mapping) != len(records):
            raise ValueError('Duplicate stock code in KRX response')
        universe = {r['ISU_SRT_CD']:r for r in days[day]
                    if (r['MKT_TP_NM'],r['SECUGRP_NM'],r['KIND_STKCERT_TP_NM'])==COMMON}
        ended = {code for code,r in universe.items() if exits.get((code,r['LIST_DD']),'')>day}
        covered = universe.keys() & mapping.keys()
        item.update(common_kospi=len(universe), joined_common=len(covered), later_delisted=len(ended),
                    joined_later_delisted=len(covered & ended))
        if kind.startswith('flow_'):
            failures, zero = 0, 0
            for code in covered:
                row = mapping[code]
                def number(key):
                    return int(str(row[key]).replace(',',''))
                try:
                    net = number('NETBID_TRDVAL')
                    failures += net != number('BID_TRDVAL')-number('ASK_TRDVAL')
                    zero += net==0
                except (ValueError, KeyError):
                    failures += 1
            item.update(net_value_zero=zero, arithmetic_invalid=failures,
                        missing_common=len(universe)-len(covered))
    output.write_text(json.dumps({'matched_downloads':report,'outcomes_read':False},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('market','delisting','requests','source','output'):
        parser.add_argument(field,type=Path)
    check(**vars(parser.parse_args()))
