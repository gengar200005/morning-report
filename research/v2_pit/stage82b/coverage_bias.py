"""Summarize signal coverage against the original and predeclared denominators."""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def summarize(rows):
    return {
        'n': len(rows),
        'F2': sum(row['F2_original_pair_QC'] == 'PASS' for row in rows),
        'F3': sum(row['F3_original_pair_QC'] == 'PASS' for row in rows),
    }


def group_by(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return {group: summarize(items) for group, items in sorted(groups.items())}


def analyze(path):
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    nonfinancial = [r for r in rows if r['industry_group'] == 'nonfinancial']
    if len(rows) != 782 or len({r['isin'] for r in rows}) != 782 or len(nonfinancial) != 722:
        raise ValueError('2021Q1 predeclared historical population changed')
    return {
        'original_population': summarize(rows),
        'applicable': summarize(nonfinancial),
        'all_sectors': group_by(rows, 'industry_group'),
        'applicable_sector': group_by(nonfinancial, 'sector_name'),
        'applicable_cap_quartile': group_by(nonfinancial, 'cap_quartile'),
        'applicable_later_delisting_status': group_by(nonfinancial, 'exit_status'),
        'warning': 'Subgroup rates describe coverage only. Later delisting is diagnostic and cannot enter historical selections.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(analyze(args.ledger), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
