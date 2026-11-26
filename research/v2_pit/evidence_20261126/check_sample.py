"""Compare held-aside manual transcriptions with independently parsed receipt fields."""
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def keyed(items):
    indexed = {row['receipt']: row for row in items}
    if len(items) != len(indexed):
        raise ValueError('Repeated validation receipt')
    return indexed


def compare():
    manual = keyed(load('qc_manual.json')['rows'])
    xbrl = keyed(load('qc_xbrl.json'))
    eps = keyed(load('qc_eps_verified.json'))
    if len(manual) != 8 or set(eps) != set(xbrl) or set(xbrl) - set(manual):
        raise ValueError('Fixed QC receipt identities differ')
    counts = {}
    details = []
    for field in ('revenue', 'operating_profit', 'basic_eps_common'):
        count = Counter()
        for receipt, row in manual.items():
            gold = row['fields'][field]
            count['sample'] += 1
            count['manual_valid_pair'] += gold['status'] == 'PASS'
            if receipt not in xbrl:
                continue
            source = xbrl[receipt]
            if row['corp_code'] != source['corp'] or source['periods']['current'] != ['2021-01-01','2021-03-31']:
                raise ValueError('Corporate identity or period mismatch')
            if field == 'basic_eps_common':
                pair = eps[receipt]
                if pair['status'] != 'PASS':
                    continue
                values = [pair['current'], pair['prior_as_reported']]
            else:
                pair = [source['fields'][when][field] for when in ('current', 'prior_as_reported')]
                if any(fact['status'] != 'PASS' for fact in pair):
                    continue
                values = [fact['value'] for fact in pair]
            scale = {'KRW': 1, '백만원': 1000000, 'KRW/share': 1}.get(gold['unit'])
            if not scale or gold['status'] != 'PASS':
                raise ValueError('Automatically accepted a field with unresolved independent evidence')
            expected = [Decimal(str(gold[k])) * scale for k in ('current','prior')]
            if list(map(Decimal, values)) != expected:
                raise ValueError(f'Independent quarter comparison failed for {receipt} {field}')
            count['auto_exact_pair'] += 1
            details.append([receipt, field, *map(str, expected)])
        counts[field] = dict(count)
    return dict(counts=counts, matching_pairs=details)


if __name__ == '__main__':
    print(json.dumps(compare(), ensure_ascii=False, indent=2))
