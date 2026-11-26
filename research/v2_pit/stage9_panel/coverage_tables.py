"""Summarize the whole fixed sample, as-of documents and repeated monthly uses without prices."""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path


def counts(rows):
    selected = [r for r in rows if r['industry_group'] == 'nonfinancial']
    missing_sector = sum(r['industry_group'] == 'unknown' for r in rows)
    result = {
        'all': len(rows),
        'identity': sum(r['identity_pass'] == '1' for r in rows),
        'financial': len(rows) - len(selected) - missing_sector,
        'unknown': missing_sector,
        'nonfinancial': len(selected),
    }
    for metric in ('F2', 'F3'):
        valid = [r for r in selected if r[metric] != '']
        result[metric] = len(valid)
        result[metric+'_of_applicable'] = len(valid)/len(selected) if selected else None
        result[metric+'_of_all'] = len(valid)/len(rows)
        result[metric+'_of_applicable_plus_unknown'] = len(valid)/(len(selected)+missing_sector) if selected or missing_sector else None
    return result


def run(ledger, quality, output):
    cert = json.loads(quality.read_bytes())
    if sha256(ledger.read_bytes()).hexdigest() != cert['ledger_sha256']:
        raise ValueError('Quality and ledger fingerprints differ')
    with ledger.open(newline='') as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 14400 or len({(r['formation'], r['isin']) for r in rows}) != len(rows):
        raise ValueError('Incomplete frozen sample')
    groups = defaultdict(list)
    documents = Counter()
    field_methods = defaultdict(Counter)
    for r in rows:
        t = r['formation']
        quarter = str((int(t[4:6])-1)//3+1)
        groups['formation_year', t[:4]].append(r)
        groups['formation_year_quarter', t[:4]+'Q'+quarter].append(r)
        period = r['period_end']
        field_quarter = period[:4]+'Q'+str((int(period[4:6])-1)//3+1) if period else 'unresolved'
        groups['selected_accounting_period_end', field_quarter].append(r)
        if r['F2'] or r['F3']:
            documents[r['receipt']] += 1
        for metric in ('F2','F3'):
            if r[metric]:
                field_methods[metric][r['method_'+metric]] += 1
    result = {label: {} for label in ('formation_year','formation_year_quarter','selected_accounting_period_end')}
    for (label, period), selected in sorted(groups.items()):
        result[label][period] = counts(selected)
    for year, measures in result['formation_year'].items():
        for field in ('identity','nonfinancial','F2','F3','unknown'):
            if measures[field] != cert['by_year'][year][field]:
                raise ValueError('Annual counts differ from the as-of ledger')
    uses = sum(documents.values())
    result['accepted_primary_document_reuse'] = {
        'issuer_months_with_either_signal': uses,
        'distinct_primary_receipts': len(documents),
        'additional_uses_after_first': uses-len(documents),
        'fraction_of_uses_after_first': (uses-len(documents))/uses if uses else None,
        'monthly_uses_per_primary_receipt_distribution': dict(sorted(Counter(documents.values()).items())),
        'signal_generation_method_by_issuer_month': field_methods,
        'unit': 'One primary receipt per accepted issuer-month. Q4 support documents omitted from this usage count.',
    }
    result['ledger_sha256'] = cert['ledger_sha256']
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('ledger','quality','output'):
        parser.add_argument(key, type=Path)
    run(**vars(parser.parse_args()))
