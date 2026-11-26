"""Read comparable revenue and operating income from a receipt-bound statement viewer.

Values are integers in KRW; field PASS describes a nonfinancial pair suitable for
F2/F3 data QA. An observed amount can still be blocked for signal use.
"""

import calendar
from datetime import date
from decimal import Decimal
import hashlib
import re

from lxml import etree, html

from public_dart import normalized, table_rows

UNIT_SCALES = {'원': 1, '천원': 1000, '백만원': 10**6, '억원': 10**8}
DATE = re.compile(r'(\d{4})\s*[.년/-]\s*(\d{1,2})\s*[.월/-]\s*(\d{1,2})\s*일?')
FISCAL = re.compile(r'(?:제\s*\d+\s*(?:\([당전]\))?\s*기|\d{4}\s*회계연도)(?:\s*제?\s*\d+\s*분기|\s*반기|\s*분기)?')
FIELDS = {'revenue': {'매출액', '수익(매출액)', '영업수익', '매출'},
          'operating_profit': {'영업이익', '영업이익(손실)', '영업손익'}}
TITLE = re.compile(r'^(?:[가-힣A-Za-z0-9]+[.)])?(?:요약)?(?:분기|반기)?(연결)?(?:별도)?(?:포괄)?손익계산서(?:\(포괄손익계산서\))?$')


def compact(text):
    return ''.join(text.split())


def quarter_dates(end):
    if end.day != calendar.monthrange(end.year, end.month)[1]:
        raise ValueError('Need a calendar month end')
    start_month = (end.month - 3) % 12 + 1
    return date(end.year - (start_month > end.month), start_month, 1), end


def fiscal_key(text):
    # Both the metadata and the data column must identify the same fiscal period.
    key = FISCAL.match(text.strip())
    return re.sub(r'\([당전]\)', '', compact(key.group(0))) if key else None


def table_metadata(table, scope, wanted):
    lines = [table['preceding_paragraph']] + [' '.join(c['text'] for c in row) for row in table['rows']]
    titles = [m for line in lines if (m := TITLE.fullmatch(compact(line)))]
    if not titles or any(bool(m.group(1)) != (scope == 'CFS') for m in titles):
        return None
    units = {value.strip() for value in re.findall(r'단위[ \t]*[:：][ \t]*([^\n)]+)', '\n'.join(lines))}
    if len(units) != 1 or not units.issubset(UNIT_SCALES):
        return None
    periods = []
    for actual in wanted:
        matches = []
        for line in lines:
            dates = DATE.findall(line)
            key = fiscal_key(line)
            if len(dates) != 2 or key is None:
                continue
            try:
                start, end = (date(*map(int, item)) for item in dates)
            except ValueError:
                return None
            if end == actual[1] and start.day == 1 and 0 <= (actual[0] - start).days <= 280:
                matches.append((key, start, start == actual[0]))
        if len(matches) != 1:
            return None
        periods.append(matches[0])
    if periods[0][0] == periods[1][0] or (periods[0][1].month, periods[0][1].day) != (periods[1][1].month, periods[1][1].day):
        return None
    return units.pop(), periods


def header_columns(rows, periods):
    if len(rows) < 2:
        return None
    groups = {}
    position = 0
    for cell in rows[0]:
        width = int(cell.get('colspan', 1))
        key = fiscal_key(cell['text'])
        if key:
            if key in groups:
                return None
            groups[key] = list(range(position, position + width))
        position += width
    if not all(key in groups for key, _, _ in periods):
        return None
    sub = [compact(c['text']) for c in rows[1]]
    if '3개월' in sub:
        # Map the lower header onto upper cells, including the label's rowspan.
        lower = []
        index = 0
        for cell in rows[0]:
            width = int(cell.get('colspan', 1))
            if int(cell.get('rowspan', 1)) > 1:
                lower.extend([None] * width)
            else:
                lower.extend(sub[index:index + width])
                index += width
        if index != len(sub) or len(lower) != position:
            return None
        cols = [[i for i in groups[key] if lower[i] == '3개월'] for key, _, _ in periods]
        return cols if all(len(c) == 1 for c in cols) else None
    # A single dated quarter can have separate detail / subtotal columns, as in KB.
    return [groups[key] for key, _, _ in periods] if all(exact for _, _, exact in periods) else None


def field_label(text):
    text = re.sub(r'^(?:[Ⅰ-Ⅻ]+|[IVX]+|\d+)\s*[.)]\s*', '', text.strip())
    return re.sub(r'\((?:주(?:석)?)[0-9,~ㆍ및-]+\)$', '', compact(text))


def parse_number(value):
    value = compact(value)
    if not value or value in ('-', '―', '–', '—'):
        return None
    if not re.fullmatch(r'(?:\(\d[\d,]*(?:\.\d+)?\)|[-+]?\d[\d,]*(?:\.\d+)?)', value):
        raise ValueError('Unrecognized monetary value')
    integer = value.strip('()+-').split('.')[0]
    if ',' in integer and not re.fullmatch(r'\d{1,3}(,\d{3})+', integer):
        raise ValueError('Invalid grouping')
    n = Decimal(value.strip('()').replace(',', ''))
    return -n if value.startswith('(') else n


def monetary_pair(row, columns, scale):
    cells = []
    for cell in row:
        if int(cell.get('colspan', 1)) != 1 or int(cell.get('rowspan', 1)) != 1:
            return None
        cells.append(cell['text'])
    result = []
    for group in columns:
        if max(group) >= len(cells):
            return None
        # Never turn missing marks into a numeric zero; multi-column subtotals
        # must have exactly one printed number and all other slots empty.
        printed = [(i, cells[i]) for i in group if cells[i].strip()]
        if len(printed) != 1:
            return None
        i, text = printed[0]
        value = parse_number(text)
        if value is None or value * scale != (value * scale).to_integral_value():
            return None
        result.append((i, text, int(value * scale)))
    return result


def kind_section(tree, pattern):
    """Isolate one section in a complete KIND report; exclude all following notes."""
    headers = tree.xpath('//body/p[starts-with(@class,"SECTION-")]')
    selected = [h for h in headers if re.fullmatch(pattern, normalized(h.text_content()))]
    if len(selected) != 1:
        return None, None
    header = selected[0]
    label = normalized(header.text_content())
    section = html.Element('body')
    anchor = etree.SubElement(etree.SubElement(section, 'p'), 'a', name='scope')
    anchor.text = label
    siblings = list(header.itersiblings())
    for node in siblings:
        if node.tag in ('h1', 'h2', 'h3') or node.get('class') in ('SECTION-1', 'SECTION-2'):
            break
        section.append(node)
    return html.tostring(section, encoding='utf-8'), label


def no_consolidated_statement(raw):
    """Recognize explicit non-applicability only, not an empty section or a failed download."""
    tree = html.fromstring(raw.decode('utf-8'))
    pattern = r'\d+\.\s*연결재무제표'
    selected, label = kind_section(tree, pattern)
    if selected is not None:
        tree = html.fromstring(selected.decode('utf-8'))
    else:
        headings = [normalized(s) for s in tree.xpath('//a[@name]/text()') if re.fullmatch(pattern, normalized(s))]
        if len(headings) != 1:
            return False
        label = headings[0]
    body = tree.find('body')
    if body is None:
        body = tree
    content = compact(body.text_content()).removeprefix(compact(label))
    content = content.strip('*※-() .。\"“”')
    as_of = r'(?:(?:본|분기|반기)?보고서(?:제출|작성)(?:기준)?일현재|공시서류작성기준일현재|당분기말현재)'
    prefix = rf'(?:(?:당사는)?(?:{as_of})?|(?:{as_of})당사는)'
    negative = (r'(?:해당(?:사항)?(?:이)?(?:없음|없습니다)|연결재무제표작성대상에해당되지않습니다|'
                r'연결대상종속(?:기업|회사)(?:이|가)없습니다|연결대상종속(?:기업|회사)(?:을|를)보유하고있지않습니다)')
    return bool(re.fullmatch(prefix + negative, content))


def extract_display_fields(raw, scope, period_end, financial, *, standalone_confirmed=False):
    if scope not in ('CFS', 'OFS') or (financial is not None and type(financial) is not bool):
        raise ValueError('Invalid scope or industry classification')
    end = date.fromisoformat(period_end)
    last = date(end.year - 1, end.month, calendar.monthrange(end.year - 1, end.month)[1])
    wanted = (quarter_dates(end), quarter_dates(last))
    group = {True: 'financial', False: 'nonfinancial', None: 'unclassified'}[financial]
    fields = {k: {'status': 'BLOCKED', 'current': None, 'prior': None, 'reason': 'no verified income row'}
              for k in FIELDS}
    result = dict(scope=scope, financial_group=group, source_sha256=hashlib.sha256(raw).hexdigest(),
                  periods=[[d.isoformat() for d in pair] for pair in wanted], fields=fields)
    if scope == 'OFS' and standalone_confirmed is not True:
        for f in fields.values():
            f['reason'] = 'standalone group unconfirmed'
        return result
    source = raw.decode('utf-8')
    tree = html.fromstring(source)
    pattern = r'\d+\.\s*연결재무제표' if scope == 'CFS' else r'\d+\.\s*(?:별도)?재무제표'
    heads = [normalized(s) for s in tree.xpath('//a[@name]/text()') if re.fullmatch(pattern, normalized(s))]
    if len(heads) == 1:
        selected, label = raw, heads[0]
    else:
        selected, label = kind_section(tree, pattern)
        if selected is None:
            for f in fields.values():
                f['reason'] = 'missing or ambiguous statement scope'
            return result
    try:
        tables = table_rows(selected, label)
    except ValueError as error:
        if 'no display tables' not in str(error):
            raise
        return result
    matched_fields = set()
    for i in range(1, len(tables)):
        meta_table = tables[i - 1]
        if i >= 2 and len(tables[i - 2]['rows']) == 1 and len(tables[i - 2]['rows'][0]) == 1:
            title = tables[i - 2]['rows'][0][0]['text']
            if TITLE.fullmatch(compact(title)):
                meta_table = {**meta_table, 'rows': [[{'text': title}]] + meta_table['rows']}
        metadata = table_metadata(meta_table, scope, wanted)
        if not metadata:
            continue
        unit, periods = metadata
        rows = tables[i]['rows']
        cols = header_columns(rows, periods)
        if not cols:
            continue
        for k, allowed in FIELDS.items():
            matches = [(j, r) for j, r in enumerate(rows) if r and field_label(r[0]['text']) in allowed]
            if not matches:
                continue
            if len(matches) != 1 or k in matched_fields:
                matched_fields.add(k)
                fields[k] = dict(status='BLOCKED', reason='ambiguous income rows', current=None, prior=None)
                continue
            matched_fields.add(k)
            j, row = matches[0]
            try:
                vals = monetary_pair(row, cols, UNIT_SCALES[unit])
            except ValueError:
                vals = None
            if not vals:
                fields[k]['reason'] = 'ambiguous or missing monetary value'
                continue
            current, prior = vals
            fields[k] = dict(status='PASS' if financial is False else 'BLOCKED',
                             reason=None if financial is False else group + ' group outside nonfinancial signal',
                             observed=True, current=current[2], prior=prior[2],
                             reported_current=current[1], reported_prior=prior[1],
                             unit=unit, scale=UNIT_SCALES[unit], source_label=row[0]['text'],
                             table_index=i, row_index=j, value_columns=[current[0], prior[0]])
    return result
