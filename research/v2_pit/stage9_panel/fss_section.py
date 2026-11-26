"""Bind one original consolidated statement section to its selected FSS receipt."""
import re
from lxml import html
from urllib.parse import urlencode
from public_dart import PARAMS

def statement_pointer(raw,receipt,expected_document=''):
    source=raw.decode('utf-8')
    tree=html.fromstring(source)
    if 'rcpNo='+receipt not in tree.xpath('//option[@selected]/@value'):
        raise ValueError('selected original receipt differs in FSS main')
    title=tree.xpath('string(//title)')
    if not any(t in title for t in ('분기보고서','반기보고서','사업보고서')):
        raise ValueError('FSS main is not a periodic report')
    matches=[]
    for block in re.split(r'var node\d+\s*=\s*\{\s*\}\s*;',source)[1:]:
        node=dict(re.findall(r"""node\d+\['(\w+)'\]\s*=\s*"([^"]*)"\s*;""",block))
        label=' '.join(node.get('text','').split())
        if not re.fullmatch(r'\d+\.\s*연결재무제표',label):continue
        if node.get('rcpNo')!=receipt or any(not re.fullmatch(r'\d+',node.get(k,'')) for k in PARAMS[1:5]):
            raise ValueError('invalid receipt-specific FSS node')
        if expected_document and node['dcmNo']!=expected_document:
            raise ValueError('FSS receipt has different document from original index')
        if not re.fullmatch(r'(?:dart\d*\.xsd|HTML)',node.get('dtd','')):
            raise ValueError('invalid FSS DTD')
        url='https://dart.fss.or.kr/report/viewer.do?'+urlencode({k:node[k] for k in PARAMS})
        matches.append((label,node['dcmNo'],url))
    if len(matches)!=1:raise ValueError('no unique consolidated statement node in FSS main')
    return matches[0]
