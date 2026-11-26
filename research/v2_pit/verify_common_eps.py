"""Cross-check Q1 common basic EPS against the same filing's consolidated statement and notes.

Inputs are outputs of filing_xbrl.extract and public_dart.collect. A match describes
this receipt's economic units and amounts only. First-publication timing is separate.
"""
import argparse
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def compact(text):
    return ''.join(text.split())


def rows(table):
    return [[compact(cell['text']) for cell in row] for row in table['rows']]


def basic_label(label):
    """Only total, basic per-share net profit. Full match excludes component facts."""
    body = re.sub(r'\((?:단위:)?원(?:/주)?\)$', '', label)
    return bool(re.fullmatch(r'(?:보통주기본|기본보통주|기본)주당(?:연결)?(?:분기)?(?:순)?(?:이익|손익)(?:\(손실\))?', body))


def amount(text):
    value = re.sub(r'원(?:/주)?$', '', text)
    number = r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?'
    if not re.fullmatch(rf'(?:-?{number}|\({number}\))', value):
        return None
    if value.startswith('(') and value.endswith(')'):
        value = '-' + value[1:-1]
    try:
        return Decimal(value.replace(',', ''))
    except InvalidOperation:
        return None


def krw_label(label):
    return bool(re.search(r'\((?:단위:)?원(?:/주)?\)$', label))


def evidence(section, table, row, label, pair, basis):
    return {'url': section['url'], 'sha256': section['sha256'], 'table': table,
            'row': row, 'label': label, 'values': list(map(str, pair)), 'basis': basis}


def statement_matches(section, periods):
    matches = []
    for j, table in enumerate(section['tables'][1:], 1):
        body = rows(table)
        heading = rows(section['tables'][j-1])
        if (len(heading) != 4 or heading[0] not in (['연결손익계산서'], ['연결포괄손익계산서'])
                or len(body) < 3 or body[1] != ['3개월','누적','3개월','누적'] or len(body[0]) != 3):
            continue
        # Match both year labels to the two column groups in order, using the
        # dates printed above this exact statement, including current vs prior.
        expected = []
        for label, span in zip(body[0][1:], periods):
            expected.append([label + span[0].replace('-', '.') + '부터' + span[1].replace('-', '.') + '까지'])
        if (heading[1:3] != expected or not all(re.fullmatch(r'제\d+기1분기', s) for s in body[0][1:])
                or any(c.get('colspan') != '2' for c in table['rows'][0][1:])):
            continue
        for k, row in enumerate(body[2:], 2):
            if len(row) != 5 or not basic_label(row[0]) or not krw_label(row[0]):
                continue
            pair = [amount(row[1]), amount(row[3])]
            if None not in pair:
                matches.append(evidence(section, j, k, row[0], pair, '원; 당분기·전년동기 3개월 열'))
    return matches


def note_matches(section, years):
    matches = []
    for j, table in enumerate(section['tables']):
        body = rows(table)
        hdr = [row for row in body if len(row) == 3 and row[0] == '구분']
        if len(hdr) != 1 or hdr[0][1:] not in (['당분기','전분기'], [f'{y}년1분기' for y in years]):
            continue
        paragraph = compact(table.get('preceding_paragraph', ''))
        if any(token in paragraph for token in ('직전분기', '계속영업', '중단영업', '별도재무', '조정주당')):
            continue
        labels = [r[0] for r in body if r]
        common = [s for s in labels if re.fullmatch(r'÷?가중평균(?:유통)?보통주식수(?:\((?:\*|천주|주|단위:주)\))?', s)]
        if len(common) != 1:
            continue
        # Ordinary and preferred rows must not be combined in a note lacking a
        # column-level share-class partition. Standalone diluted notes are excluded.
        if any('우선주' in label or '희석' in label for label in labels):
            continue
        for k, row in enumerate(body):
            if len(row) != 3 or not basic_label(row[0]):
                continue
            if not (krw_label(row[0]) or all(re.search(r'원(?:/주)?$', v) for v in row[1:])
                    or ['(단위:원)'] in body):
                continue
            pair = [amount(v) for v in row[1:]]
            if None not in pair:
                matches.append(evidence(section, j, k, row[0], pair, common[0]))
    return matches


def verify(facts, display):
    result = {'receipt': facts['receipt'], 'document': facts['document'], 'corp': facts['corp'],
              'archive_sha256': facts['archive_sha256'], 'status': 'BLOCKED',
              'first_publication': 'UNASSESSED', 'current': None, 'prior_as_reported': None}

    def blocked(reason):
        return dict(result, reason=reason)

    if facts['receipt'] != display['receipt'] or display.get('source') != 'public_dart_display':
        return blocked('receipt_or_source_mismatch')
    periods = [facts['periods'][key] for key in ('current', 'prior_as_reported')]
    years = [date.fromisoformat(p[0]).year for p in periods]
    if years[0] != years[1]+1 or any(tuple(p) != (f'{y}-01-01', f'{y}-03-31') for p,y in zip(periods,years)):
        return blocked('only_calendar_Q1_note_periods_supported')
    sections = {}
    for section in display['sections']:
        label = compact(section['section'])
        if label not in ('2.연결재무제표','3.연결재무제표주석'):
            continue
        url = urlparse(section['url'])
        params = parse_qs(url.query)
        if (url.scheme != 'https' or url.netloc != 'dart.fss.or.kr' or url.path != '/report/viewer.do'
                or params.get('rcpNo') != [facts['receipt']] or params.get('dcmNo') != [facts['document']]
                or not re.fullmatch('[0-9a-f]{64}', section['sha256']) or label in sections):
            return blocked('section_version_or_provenance_mismatch')
        sections[label] = section
    if len(sections) != 2:
        return blocked('missing_consolidated_statement_or_notes')
    expected = []
    units = set()
    for key in ('current','prior_as_reported'):
        field = facts['fields'][key]['basic_common_eps']
        if not str(field.get('reason','')).startswith('common_share_class_requires_notes'):
            return blocked('missing_or_conflicting_xbrl_basic_eps')
        candidates = field['candidates']
        if not candidates or any(c['nil'] or c['unit'] not in ('KRW/share','shares') for c in candidates):
            return blocked('invalid_xbrl_candidate_or_unit')
        try:
            amounts = {Decimal(c['raw']) for c in candidates}
        except (InvalidOperation, TypeError):
            return blocked('invalid_xbrl_numeric_value')
        if len(amounts) != 1 or not next(iter(amounts)).is_finite():
            return blocked('missing_or_conflicting_xbrl_basic_eps')
        units.update(c['unit'] for c in candidates)
        expected.append(next(iter(amounts)))
    if len(units) != 1:
        return blocked('inconsistent_xbrl_units')
    fs = statement_matches(sections['2.연결재무제표'], periods)
    notes = note_matches(sections['3.연결재무제표주석'], years)
    result.update(statement_evidence=fs, note_evidence=notes, xbrl_units=sorted(units))
    if not fs or not notes:
        return blocked('no_eligible_quarterly_statement_and_common_share_note_pair')
    if any([Decimal(v) for v in row['values']] != expected for row in fs + notes):
        return blocked('display_note_or_statement_differs_from_xbrl')
    return dict(result, status='PASS', reason='same_receipt_statement_note_and_xbrl_agree',
                current=str(expected[0]), prior_as_reported=str(expected[1]), economic_unit='KRW/share',
                unit_basis='display statement + ordinary basic EPS note; original XBRL unit retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', required=True, type=Path, help='One filing_xbrl record or a JSON array')
    parser.add_argument('--display-dir', required=True, type=Path)
    args = parser.parse_args()
    payload = json.loads(args.facts.read_text())
    items = payload if isinstance(payload, list) else [payload]
    print(json.dumps([verify(item, json.loads((args.display_dir / (item['receipt']+'.json')).read_text()))
                      for item in items], indent=2, ensure_ascii=False))
