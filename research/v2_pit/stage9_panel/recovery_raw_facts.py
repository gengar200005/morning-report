"""Replay document-level CFS facts in a preserved raw part. No as-of, industry or outcome inputs."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filing_xbrl import D, X, parse_instance, qname
from stage9_panel.pit_facts import FIELDS, inspect_xbrl


CURRENT = 'PeriodCoveredbytheReportofCurrentFiscalYearorQuarterorHalfYearMember'
MEMBER = re.compile(r'(\d{14})/xbrl-([0-9a-f]{16})\.zip')
METADATA_NAMESPACE = re.compile(r'http://dart\.fss\.or\.kr/taxonomy/[0-9-]+/(?:ifrs/)?dart-gcd')


def filing_header(payload):
    """Read the issuer's current-period declaration, never inferring the period from a filename."""
    with ZipFile(BytesIO(payload)) as archive:
        members = [item for item in archive.infolist() if item.filename.lower().endswith('.xbrl')]
        if len(members) != 1 or members[0].file_size > 128 * 1024 ** 2:
            raise ValueError('instance_layout')
        tree, namespaces = parse_instance(archive.read(members[0]))
    declared = defaultdict(set)
    current_ids = set()
    issuers = set()
    for context in tree.findall(X + 'context'):
        ident = context.find(X + 'entity/' + X + 'identifier')
        if ident is None or ident.get('scheme') != 'http://dart.fss.or.kr/ifrs/CIK':
            raise ValueError('issuer_scheme')
        issuers.add(ident.text)
        for m in context.findall(X + 'scenario/' + D + 'explicitMember'):
            namespace, _, local = qname(m.text, namespaces)[1:].partition('}')
            if (METADATA_NAMESPACE.fullmatch(namespace) and local == CURRENT
                    and qname(m.get('dimension'), namespaces) == '{' + namespace + '}PeriodAxis'):
                current_ids.add(context.get('id'))
    if len(issuers) != 1 or not re.fullmatch(r'\d{8}', next(iter(issuers)) or ''):
        raise ValueError('issuer_identity')
    for node in tree:
        if node.get('contextRef') in current_ids:
            uri, _, local = node.tag[1:].partition('}')
            if METADATA_NAMESPACE.fullmatch(uri) and node.text:
                declared[local].add(node.text.strip())
    key = 'DocumentPeriodEndDate'
    if len(declared[key]) != 1:
        raise ValueError('ambiguous_or_absent_current_end')
    end = date.fromisoformat(declared[key].pop())
    amendment = next(iter(declared['Amendment'])) if len(declared['Amendment']) == 1 else ''
    return issuers.pop(), end, amendment


def compare_manual(parsed):
    manual_path = Path(__file__).parent / 'audit_main_manual.csv'
    by_receipt = {row['receipt']: row for row in parsed}
    checks = 0
    checked_receipts = []
    mismatches = []
    with manual_path.open(newline='', encoding='utf-8-sig') as manual:
        for ref in csv.DictReader(manual):
            if ref['role'] != 'quarter' or ref['receipt'] not in by_receipt:
                continue
            emitted = by_receipt[ref['receipt']]
            checked_receipts.append(ref['receipt'])
            for field, column in (('revenue', 'rev'), ('operating_profit', 'op')):
                for side in ('current', 'prior'):
                    checks += 1
                    if str(emitted.get(field+'_'+side)) != ref[column+'_'+side]:
                        mismatches.append([ref['receipt'], field, side])
    return {
        'manual_csv_sha256': sha256(manual_path.read_bytes()).hexdigest(),
        'receipts': checked_receipts, 'amounts': checks, 'mismatches': mismatches
    }


def inspect(archive_path, rows_path, summary_path):
    collisions = json.loads((Path(__file__).parent/'technical_checkpoint/request_reconciliation.json').read_text())
    quarantined = set(collisions['quarantine'])
    rows = []
    seen_receipts = set()
    with ZipFile(archive_path) as outer:
        for item in sorted(outer.infolist(), key=lambda member: member.filename):
            if '/xbrl-' not in item.filename:
                continue
            m = MEMBER.fullmatch(item.filename)
            if not m or m.group(1) in seen_receipts:
                raise ValueError('unexpected XBRL package key or duplicate receipt')
            receipt, prefix = m.groups()
            seen_receipts.add(receipt)
            payload = outer.read(item)
            digest = sha256(payload).hexdigest()
            if not digest.startswith(prefix):
                raise ValueError('XBRL SHA mismatch')
            row = {'receipt': receipt, 'source_sha256': digest, 'status': 'parsed'}
            if receipt in quarantined:
                row['status'] = 'quarantined'
                rows.append(row)
                continue
            try:
                corp, end, amendment = filing_header(payload)
                if end >= date.fromisoformat(receipt[:8]):
                    raise ValueError('period_end_not_before_receipt_number_date')
                facts = inspect_xbrl(payload, corp, end)
            except (ValueError, ParseError, BadZipFile) as error:
                row.update(status='unparsed', reason=str(error))
                rows.append(row)
                continue
            row.update(issuer=corp, period_end=end.isoformat(), amendment_metadata=amendment,
                       has_cfs_context=int(facts['has_cfs_context']), instance_sha256=facts['instance_sha256'])
            for field in FIELDS:
                for side in ('current', 'prior'):
                    k = field + '_' + side
                    fact = facts['3'][k]
                    if 'value' in fact:
                        row[k] = fact['value']
                    row[k + '_status'] = fact['status']
                row[field + '_pair'] = int(field+'_current' in row and field+'_prior' in row)
            rows.append(row)

    keys = ['receipt', 'source_sha256', 'status', 'reason', 'issuer', 'period_end', 'amendment_metadata',
            'instance_sha256', 'has_cfs_context']
    for field in FIELDS:
        for side in ('current', 'prior'):
            keys.extend([field+'_'+side, field+'_'+side+'_status'])
        keys.append(field+'_pair')
    with rows_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)

    def metrics(items):
        return {
            'parsed_xbrl_receipts': len(items),
            'with_cfs_context': sum(r['has_cfs_context'] for r in items),
            'exact_3m_revenue_pair': sum(r['revenue_pair'] for r in items),
            'exact_3m_operating_profit_pair': sum(r['operating_profit_pair'] for r in items),
            'both_exact_pairs': sum(r['revenue_pair'] and r['operating_profit_pair'] for r in items),
        }
    parsed = [r for r in rows if r['status'] == 'parsed']
    groups = defaultdict(list)
    years = defaultdict(list)
    for row in parsed:
        groups[row['period_end']].append(row)
        years[row['period_end'][:4]].append(row)
    out = {
        'scope': 'One row per XBRL receipt in this raw part, including financial firms. A version is not assumed original. No HTML fallback, price data, or PIT selection.',
        'exact_pair': 'Two integer KRW CFS figures ending on the declared report date and one year earlier, each covering exactly three months. No YTD subtraction. Zero retained. Missing cells left empty in CSV.',
        'slice_sha256': sha256(archive_path.read_bytes()).hexdigest(),
        'per_document_csv_sha256': sha256(rows_path.read_bytes()).hexdigest(),
        'receipt_count': len(rows), 'distinct_source_sha256': len({r['source_sha256'] for r in rows}),
        'receipt_status': dict(Counter(r['status'] for r in rows)),
        'unparsed_reasons': dict(Counter(r['reason'] for r in rows if r['status']=='unparsed')),
        'amendment_metadata_values': dict(Counter(r['amendment_metadata'] for r in parsed)),
        'total': metrics(parsed), 'by_period_end': {g:metrics(v) for g,v in sorted(groups.items())},
        'by_period_year': {g:metrics(v) for g,v in sorted(years.items())},
        'parsed_field_cells': dict(Counter(r[field+'_'+side+'_status'] for r in parsed
            for field in FIELDS for side in ('current', 'prior'))),
        'true_zero_field_cells': sum(r.get(field+'_'+side)==0 for r in parsed
            for field in FIELDS for side in ('current', 'prior'))
    }
    out['frozen_direct_quarter_controls'] = compare_manual(parsed)
    summary_path.write_text(json.dumps(out, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('archive_path', 'rows_path', 'summary_path'):
        p.add_argument(name, type=Path)
    inspect(**vars(p.parse_args()))
