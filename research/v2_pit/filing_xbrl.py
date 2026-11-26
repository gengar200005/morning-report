"""Extract evidence from one receipt-bound public DART XBRL archive, without network I/O."""
import argparse
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

XBRLI = 'http://www.xbrl.org/2003/instance'
X = '{' + XBRLI + '}'
D = '{http://xbrl.org/2006/xbrldi}'
L = '{http://www.xbrl.org/2003/linkbase}'
XL = '{http://www.w3.org/1999/xlink}'
NIL = '{http://www.w3.org/2001/XMLSchema-instance}nil'
ISO_KRW = '{http://www.xbrl.org/2003/iso4217}KRW'
IFRS = re.compile(r'http://(?:xbrl\.ifrs\.org/taxonomy/[0-9-]+/ifrs-full|xbrl\.iasb\.org/taxonomy/[0-9-]+/ifrs)')
DART = re.compile(r'http://dart\.fss\.or\.kr/taxonomy/[0-9-]+/ifrs/dart')
FIELDS = {
    'revenue': (IFRS, 'Revenue'),
    'operating_profit': (DART, 'OperatingIncomeLoss'),
    'basic_common_eps': (IFRS, 'BasicEarningsLossPerShare'),
}
COMMON_LABELS = {'보통주기본주당이익(손실)', '보통주기본주당이익', '보통주기본주당손실',
                 '보통주기본주당순이익(손실)', '보통주기본주당순이익'}


def period(year, quarter, *, cumulative=False):
    if not 1 <= quarter <= 4:
        raise ValueError('Invalid calendar quarter')
    end_month = quarter * 3
    start_month = 1 if cumulative else end_month - 2
    return (date(year, start_month, 1).isoformat(),
            date(year, end_month, calendar.monthrange(year, end_month)[1]).isoformat())


def parse_instance(raw):
    # The bounded extractor supports namespace bindings declared on the root.
    # Refuse inner declarations rather than resolving lexical QNames in the wrong scope.
    namespaces = {}
    parser = ET.iterparse(io.BytesIO(raw), events=('start-ns', 'start'))
    root = None
    for event, item in parser:
        if event == 'start-ns':
            if root is not None:
                raise ValueError('Nested namespace declarations need review')
            prefix, uri = item
            namespaces[prefix] = uri
        elif root is None:
            root = item
    if root is None or root.tag != X + 'xbrl':
        raise ValueError('Missing XBRL instance')
    return root, namespaces


def qname(text, namespaces):
    prefix, _, local = (text or '').strip().rpartition(':')
    return '{' + namespaces.get(prefix, '') + '}' + local


def dimensions_match(context, namespaces):
    scenario = context.find(X + 'scenario')
    if context.find(X + 'entity/' + X + 'segment') is not None or scenario is None or len(scenario) != 1:
        return False
    member = scenario[0]
    axis = qname(member.get('dimension'), namespaces)
    value = qname(member.text, namespaces)
    uri, _, name = axis[1:].partition('}')
    return (member.tag == D + 'explicitMember' and IFRS.fullmatch(uri) is not None
            and name == 'ConsolidatedAndSeparateFinancialStatementsAxis'
            and value == '{' + uri + '}ConsolidatedMember')


def unit_kind(unit, namespaces):
    if unit is None or len(unit) != 1:
        return 'unrecognized'
    first = unit[0]
    if first.tag == X + 'measure':
        measure = qname(first.text, namespaces)
        return {ISO_KRW: 'KRW', X + 'shares': 'shares'}.get(measure, 'unrecognized')
    if first.tag == X + 'divide' and len(first) == 2:
        num = first.find(X + 'unitNumerator')
        den = first.find(X + 'unitDenominator')
        if num is not None and den is not None and len(num) == len(den) == 1:
            if (num[0].tag == den[0].tag == X + 'measure'
                    and qname(num[0].text, namespaces) == ISO_KRW
                    and qname(den[0].text, namespaces) == X + 'shares'):
                return 'KRW/share'
    return 'unrecognized'


def common_extensions(z, corp):
    """Exact ordinary/basic/total labels on issuer-specific extension taxa are candidates only."""
    names = set()
    for path in z.namelist():
        if not re.search(r'[/\\]lab_' + corp + r'-ko_.*\.xml$', path):
            continue
        doc = ET.fromstring(z.read(path))
        for link in doc.iter(L + 'labelLink'):
            labels = {node.get(XL + 'label') for node in link.findall(L + 'label')
                      if node.get(XL + 'role') == 'http://www.xbrl.org/2003/role/label'
                      and ''.join((node.text or '').split()) in COMMON_LABELS}
            locations = {arc.get(XL + 'from') for arc in link.findall(L + 'labelArc')
                         if arc.get(XL + 'to') in labels}
            for loc in link.findall(L + 'loc'):
                if loc.get(XL + 'label') in locations:
                    fragment = loc.get(XL + 'href', '').partition('#')[2]
                    prefix = 'entity' + corp + '_'
                    if fragment.startswith(prefix):
                        names.add(fragment[len(prefix):])
    return names


def field_for(tag, extensions, corp):
    if not tag.startswith('{'):
        return None
    uri, _, local = tag[1:].partition('}')
    for field, (scheme, name) in FIELDS.items():
        if local == name and scheme.fullmatch(uri):
            return field
    if local in extensions and re.fullmatch(r'http://dart\.fss\.or\.kr/taxonomy/[0-9-]+/entity' + corp, uri):
        return 'basic_common_eps'
    return None


def classify(candidates, field, *, cumulative=False):
    result = {'status': 'BLOCKED', 'value': None, 'candidates': candidates}
    if not candidates:
        result['reason'] = 'no_supported_fact_in_exact_context'
        return result
    values = set()
    for fact in candidates:
        try:
            number = Decimal(fact['raw'] or '')
        except InvalidOperation:
            number = None
        if fact['nil'] or number is None or not number.is_finite():
            result['reason'] = 'nil_or_nonfinite'
            return result
        values.add(number)
    if len(values) != 1:
        result['reason'] = 'conflicting_values'
        return result
    if field == 'basic_common_eps':
        reasons = ['common_share_class_requires_notes']
        if any(f['unit'] != 'KRW/share' for f in candidates):
            reasons.append('per_share_unit_unverified')
        result['reason'] = '+'.join(reasons)
    elif any(f['unit'] != 'KRW' for f in candidates):
        result['reason'] = 'unit_not_KRW'
    else:
        reason = 'exact_consolidated_calendar_ytd_fact' if cumulative else 'exact_consolidated_quarter_fact'
        result.update(status='PASS', reason=reason, value=str(next(iter(values))))
    return result


def extract(archive, receipt, document, corp, year, quarter, sha256, *, cumulative=False):
    """Default to three months. Cumulative mode selects Jan 1 through the calendar quarter-end."""
    periods = {'current': period(year, quarter, cumulative=cumulative),
               'prior_as_reported': period(year-1, quarter, cumulative=cumulative)}
    if (not re.fullmatch(r'\d{14}', receipt) or not re.fullmatch(r'\d+', document)
            or not re.fullmatch(r'\d{8}', corp) or not 2016 <= year <= 2023
            or not periods['current'][1] <= date.fromisoformat(receipt[:8]).isoformat() <= '2023-12-31'):
        raise ValueError('Invalid pilot receipt or expected reporting period')
    if archive.stat().st_size > 32 * 1024**2:
        raise ValueError('Oversized archive')
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError('Archive hash mismatch')
    with ZipFile(io.BytesIO(data)) as z:
        instances = [p for p in z.namelist() if p.lower().endswith('.xbrl')]
        if len(instances) != 1 or sum(f.file_size for f in z.infolist()) > 128 * 1024**2:
            raise ValueError('Unexpected archive layout or size')
        raw = z.read(instances[0])
        root, namespaces = parse_instance(raw)
        extensions = common_extensions(z, corp)
    accepted = {}
    seen = set()
    entity_ids = set()
    for ctx in root.findall(X + 'context'):
        ctx_id = ctx.get('id')
        if not ctx_id or ctx_id in seen:
            raise ValueError('Duplicate or missing context id')
        seen.add(ctx_id)
        ident = ctx.find(X + 'entity/' + X + 'identifier')
        if ident is None:
            raise ValueError('Missing context corporate identity')
        entity_ids.add((ident.get('scheme'), ident.text))
        if not dimensions_match(ctx, namespaces):
            continue
        dates = tuple(ctx.findtext(X + 'period/' + X + name) for name in ('startDate', 'endDate'))
        for when, expected in periods.items():
            if dates == expected:
                accepted[ctx_id] = when
    if entity_ids != {('http://dart.fss.or.kr/ifrs/CIK', corp)}:
        raise ValueError('Wrong or mixed corporate identities')
    units = {}
    for unit in root.findall(X + 'unit'):
        key = unit.get('id')
        if not key or key in units:
            raise ValueError('Duplicate or missing unit id')
        units[key] = unit_kind(unit, namespaces)
    facts = defaultdict(list)
    for node in root:
        when = accepted.get(node.get('contextRef'))
        if when is None:
            continue
        field = field_for(node.tag, extensions, corp)
        if field:
            facts[when, field].append({'tag': node.tag, 'context': node.get('contextRef'),
                                        'unit': units.get(node.get('unitRef'), 'unrecognized'),
                                        'unit_ref': node.get('unitRef'), 'decimals': node.get('decimals'),
                                        'raw': node.text, 'nil': node.get(NIL) in ('true', '1')})
    return {'receipt': receipt, 'document': document, 'corp': corp, 'periods': periods,
            'source_url': f'https://dart.fss.or.kr/pdf/download/ifrs.do?rcp_no={receipt}&dcm_no={document}&lang=ko',
            'archive_sha256': sha256, 'instance': instances[0], 'instance_sha256': hashlib.sha256(raw).hexdigest(),
            'fields': {when: {field: classify(facts[when, field], field, cumulative=cumulative) for field in FIELDS}
                       for when in periods}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    for option in ('receipt', 'document', 'corp', 'sha256'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--quarter', type=int, choices=range(1, 5), required=True)
    print(json.dumps(extract(**vars(parser.parse_args())), indent=2, ensure_ascii=False))
