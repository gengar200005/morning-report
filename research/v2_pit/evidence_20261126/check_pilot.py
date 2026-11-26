"""Compare nine versioned report extractions to the independent DART display audits."""
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TAGS = {'Revenue': 'revenue', 'OperatingIncomeLoss': 'operating_profit',
        'BasicEarningsLossPerShare': 'basic_common_eps'}


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def main():
    expected = {}
    for row in load('pilot_samsung.json')['events'].values():
        amounts = {}
        for tag, val in row['consolidated_filing_values'].items():
            scale = 10**6 if val['unit'] == 'million KRW' else 1
            amounts[TAGS[tag]] = [val[k] * scale for k in ('value','prior_year_same_quarter_as_filed')]
        expected[row['receipt']] = amounts
    for row in load('pilot_lg_sk.json'):
        expected[row['receipt']] = {name: [v['value'] for v in pair]
                                    for name, pair in row['amounts_current_then_prior'].items()}
    for row in load('pilot_exits.json')['facts']:
        expected[row['receipt']] = {TAGS[tag]: [v['value'] for v in pair]
                                    for tag, pair in row['facts'].items()}
    rows = load('pilot_xbrl.json')
    if len(rows) != 9 or len(expected) != 9 or set(expected) != {r['receipt'] for r in rows}:
        raise ValueError('Pinned receipt census mismatch')
    total = 0
    for row in rows:
        for when, side in [('current',0),('prior_as_reported',1)]:
            for name, field in row['fields'][when].items():
                amount = Decimal(expected[row['receipt']][name][side])
                observations = {Decimal(c['raw']) for c in field['candidates'] if not c['nil']}
                if observations != {amount} or (name != 'basic_common_eps' and field['status'] != 'PASS'):
                    raise ValueError(f"Different amount at {row['receipt']} {when} {name}")
                total += 1
    if total != 54:
        raise ValueError('Incomplete independent comparisons')
    print('9 versions, 54 matching reported values; EPS unit and common class use display evidence')


if __name__ == '__main__':
    main()
