"""Replay an issuer's reviewed accounting-policy and operating-segment disclosures from the archive."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from lxml import html


def compact(text):
    return ''.join(text.split())


def amount(text):
    text = compact(text).replace(',', '').replace('(-)', '-')
    if text == '-':
        return 0
    if re.fullmatch(r'\(\d+\)', text):
        return -int(text[1:-1])
    if not re.fullmatch(r'-?\d+', text):
        raise ValueError('Unrecognized numeric cell')
    return int(text)


def cells(table):
    return [[compact(cell.text_content()) for cell in row.xpath('./th|./td')]
            for row in table.xpath('./thead/tr|./tbody/tr|./tr')]


def segment(table, field):
    header, *rows = cells(table)
    if header[0] != '구분' or header[-1] != '합계' or len(set(header)) != len(header):
        raise ValueError('Ambiguous operating-segment columns')
    # The note immediately before the table states its monetary scale.
    if '(단위:원)' not in compact(''.join(table.xpath('preceding::text()[normalize-space()][position()<=2]'))):
        raise ValueError('Operating-segment note has no explicit KRW unit')
    label = {'revenue': '외부거래', 'operating_profit': '영업손익'}[field]
    selected = [row for row in rows if row[0] == label]
    if len(selected) != 1 or len(selected[0]) != len(header):
        raise ValueError('Ambiguous operating-segment row')
    data = {name: amount(value) for name, value in zip(header[1:], selected[0][1:], strict=True)}
    total = data.pop('합계')
    if sum(data.values()) != total:
        raise ValueError('Operating segments and eliminations do not reconcile')
    return data, total


def scope(table):
    header, *rows = cells(table)
    keys = [header.index(k) for k in ('상호', '설립일', '지배관계근거')]
    roster = sorted(tuple(row[k] for k in keys) for row in rows)
    if not roster or len({r[0] for r in roster}) != len(roster) or any(not all(r) for r in roster):
        raise ValueError('Incomplete roster of controlled entities')
    return roster


def consolidated_notes(doc):
    headings = [p for p in doc.xpath('//p[@class="SECTION-2"]') if compact(p.text_content()) == '3.연결재무제표주석']
    if len(headings) != 1:
        raise ValueError('Ambiguous consolidated notes section')
    text = []
    tables = []
    for sibling in headings[0].itersiblings():
        if sibling.tag == 'p' and sibling.get('class') == 'SECTION-2':
            if compact(sibling.text_content()) != '4.재무제표':
                raise ValueError('Unexpected consolidated notes boundary')
            return compact(' '.join(text)), tables
        text.append(sibling.text_content())
        if sibling.tag == 'table':
            tables.append(sibling)
        tables.extend(sibling.xpath('.//table'))
    raise ValueError('Incomplete consolidated notes section')


def replay(packages, reviewed):
    """reviewed holds exact statement locations, policy excerpts and an independent adjudication."""
    if set(reviewed['independent_face_amounts']) != {'revenue', 'operating_profit'}:
        raise ValueError('Both independently checked statement fields are required')
    if len(reviewed['sources']) != 4 or len({s['receipt'] for s in reviewed['sources']}) != 4:
        raise ValueError('Four distinct annual and nine-month source receipts required')
    tables = []
    outputs = []
    rosters = []
    notes = []
    with sqlite3.connect(packages.resolve().as_uri() + '?mode=ro', uri=True) as db:
        for source in reviewed['sources']:
            receipt = source['receipt']
            sql = 'SELECT sha256,source,body,corp FROM packages WHERE receipt=? AND kind=?'
            note_kind = source['note_kind']
            if note_kind not in ('kind_html', 'dart_notes'):
                raise ValueError('Unexpected notes format')
            for kind in (note_kind, 'xbrl'):
                row = db.execute(sql, (receipt, kind)).fetchone()
                if (not row or row[3] != reviewed['corp'] or row[0] != source['note_sha256' if kind == note_kind else 'xbrl_sha256']
                        or sha256(row[2]).hexdigest() != row[0]):
                    raise ValueError('Missing or changed original ' + receipt)
                if kind == note_kind:
                    doc = html.fromstring(row[2].decode('utf-8-sig'))
                    notes.append(dict(receipt=receipt, url=row[1], sha256=row[0]))
            if note_kind == 'kind_html':
                text, note_tables = consolidated_notes(doc)
            else:
                text, note_tables = compact(doc.text_content()), doc.xpath('//table')
                if '연결재무제표주석' not in text:
                    raise ValueError('Missing FSS consolidated notes heading')
            for label in ('policy', 'scope_change'):
                if not source[label] or any(compact(phrase) not in text for phrase in source[label]):
                    raise ValueError('Missing reviewed note disclosure ' + receipt + '/' + label)
            tabs = doc.xpath('//table')
            if source.get('scope_note_rows'):
                rows = cells(tabs[source['scope_table']])
                if '종속기업명' not in rows[0]:
                    raise ValueError('Unrecognized subsidiary roster')
                subsidiary_rows = rows[source['scope_note_rows']:]
                subsidiary_names = [r[0] for r in subsidiary_rows]
                if not subsidiary_names or len(set(subsidiary_names)) != len(subsidiary_names):
                    raise ValueError('Ambiguous subsidiary roster')
                rosters.append(sorted((r[0], r[2], r[3], r[4]) for r in subsidiary_rows))
            else:
                roster = scope(tabs[source['scope_table']])
                for equivalence in source.get('control_wording', []):
                    documented = tuple(equivalence['overview_row'])
                    note = tabs[equivalence['notes_table']]
                    ownership = equivalence['ownership_row']
                    if documented not in roster or note not in note_tables or ownership not in cells(note):
                        raise ValueError('Missing evidence for different descriptions of control')
                    if ownership[0] != documented[0] or ownership[2:4] != ['100.0', '100.0']:
                        raise ValueError('Control-wording exception requires unchanged wholly owned holding')
                    roster[roster.index(documented)] = (documented[0], documented[1], '100% ' + ownership[4])
                rosters.append(sorted(roster))
            reviewed_tables = [tabs[n] for n in source['segment_tables']]
            if not all(table in note_tables for table in reviewed_tables):
                raise ValueError('Operating-segment table outside consolidated notes')
            tables.append(reviewed_tables)
    if rosters[0] != rosters[1] or rosters[2] != rosters[3]:
        raise ValueError('Annual and nine-month consolidated entity rosters differ')
    for field, reference in reviewed['independent_face_amounts'].items():
        parts = [[segment(tab, field) for tab in period] for period in tables]
        if [len(p) for p in parts] != [2, 2, 1, 1]:
            raise ValueError('Wrong number of reviewed comparatives')
        if parts[0][1] != parts[2][0] or parts[1][1] != parts[3][0]:
            raise ValueError('Restated comparative operating segments or amounts')
        if any(set(d) != set(parts[0][0][0]) for period in parts for d, _ in period):
            raise ValueError('Operating segments or eliminations differ')
        amounts = [[total for _, total in period] for period in parts]
        if amounts != reference:
            raise ValueError('Independent main statement and segment-note amounts differ')
        delta = [a - b for a, b in zip(amounts[0], amounts[1], strict=True)]
        if reviewed['independent_review'] != 'PASS':
            raise ValueError('Independent review incomplete')
        outputs.append(dict(component_receipts=[n['receipt'] for n in notes],
                    component_hashes=[s['xbrl_sha256'] for s in reviewed['sources']], field=field,
                    source_url=notes[0]['url'], source_sha256=notes[0]['sha256'],
                    note_source_hashes=[n['sha256'] for n in notes], note_sources=notes,
                    available_session=reviewed['available_session'], verdict='PASS',
                    review_method='same_basis_filing_notes', independent_quarter_confirmed=False,
                    arithmetic_pair=delta, note_segment_amounts=amounts,
                    subsidiary_counts=[len(roster) for roster in rosters]))
    return outputs


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('packages', 'review', 'output'):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    result = replay(a.packages, json.loads(a.review.read_bytes()))
    tmp = a.output.with_suffix(a.output.suffix + '.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(a.output)
