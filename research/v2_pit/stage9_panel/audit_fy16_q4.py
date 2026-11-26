"""Independent review of eight published statements and segment notes used for two 2016 Q4 checks."""
import argparse
import csv
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
from zipfile import ZipFile
from lxml import etree,html

INPUTS={
    '000080':[('20170331000549',8,9),('20161114000295',4,5),('20160330000717',6,7),('20151113000033',4,5)],
    '007690':[('20170329000302',115,117),('20161114000547',118,120),('20160329000310',120,122),('20151112000368',118,120)]
}
DATES=('20170403','20170502')


def clean(x):return ' '.join(x.text_content().split())


def money(s):
    s=s.replace(',','').replace('(-)','-')
    if s=='-':return 0
    return -int(s[1:-1]) if s.startswith('(') else int(s)


def load_note(raw,kind):
    root=html.fromstring(raw.decode())
    if kind=='kind_html':
        start,=[n for n in root.xpath('//body/p[starts-with(@class,"SECTION")]') if ''.join(n.text_content().split())=='3.연결재무제표주석']
        doc=html.Element('div')
        for node in list(start.itersiblings()):
            if node.get('class') in ('SECTION-1','SECTION-2') or node.tag in ('h1','h2','h3'):break
            doc.append(node)
        return doc
    return root


def amount_pairs(raw, corp, end):
    with ZipFile(BytesIO(raw)) as z:
        name,=[p for p in z.namelist() if p.lower().endswith('.xbrl')]
        xml=z.read(name)
    t=etree.fromstring(xml)
    ids={}
    for c in t.xpath('./*[local-name()="context"]'):
        ms=c.xpath('.//*[local-name()="explicitMember"]')
        if len(ms)!=1 or not ms[0].text.endswith(':ConsolidatedMember') or not ms[0].get('dimension').endswith(':ConsolidatedAndSeparateFinancialStatementsAxis'):continue
        if c.xpath('.//*[local-name()="identifier"]/text()')!=[corp]:raise ValueError('wrong CIK')
        a=c.xpath('.//*[local-name()="startDate"]/text()');b=c.xpath('.//*[local-name()="endDate"]/text()')
        for side,year in [('current',end.year),('prior',end.year-1)]:
            if a==[f'{year}-01-01'] and b==[f'{year}-{end.month:02}-{end.day:02}']:ids[c.get('id')]=side
    facts={}
    for n in t:
        side=ids.get(n.get('contextRef'))
        if not side:continue
        local=etree.QName(n).localname
        if local not in ('Revenue','OperatingIncomeLoss'):continue
        unit,=t.xpath('./*[local-name()="unit"][@id=$u]/*[local-name()="measure"]',u=n.get('unitRef'))
        pr,token=unit.text.split(':')
        if token!='KRW' or unit.nsmap[pr]!='http://www.xbrl.org/2003/iso4217':raise ValueError('not ISO KRW')
        key=(side,local)
        if key in facts and facts[key]!=int(n.text):raise ValueError('contradictory copies')
        facts[key]=int(n.text)
    return {side:[facts[side,tag] for tag in ('Revenue','OperatingIncomeLoss')] for side in ('current','prior')}


def run(packages,register,dest):
    db=sqlite3.connect('file:'+str(packages.resolve())+'?mode=ro',uri=True)
    with register.open() as f:versions=list(csv.DictReader(f))
    result={}
    for code,group in INPUTS.items():
        docs=[];receipts=[x[0] for x in group]
        for rc,cur,prev in group:
            meta,=[r for r in versions if r['stock_code']==code and r['receipt']==rc]
            doc={}
            for fmt,url,h,b in db.execute("""SELECT kind,source,sha256,body FROM packages p WHERE receipt=?
                AND NOT EXISTS (SELECT 1 FROM quarantine q WHERE p.receipt=q.receipt AND p.kind=q.kind)""",(rc,)):
                if sha256(b).hexdigest()!=h:raise ValueError('source digest')
                doc[fmt]=(url,h,b)
            xurl,xhash,raw=doc['xbrl']
            parsed=amount_pairs(raw,meta['corp_code'],date.fromisoformat(meta['period_end']))
            kind='dart_notes' if (code=='000080' or rc in ('20160329000310','20151112000368')) else 'kind_html'
            nurl,nhash,notes=doc[kind]
            tree=load_note(notes,kind);tables=tree.xpath('.//table')
            unit=1 if code=='000080' else 1000
            proof={}
            for idx,side in [(cur,'current'),(prev,'prior')]:
                tb=tables[idx];rows=[[clean(c) for c in tr.xpath('./td|./th')] for tr in tb.xpath('.//tr')]
                label='원' if unit==1 else '천원'
                if '단위:'+label+')' not in re.sub(r'\s','',clean(tb.getprevious())):raise ValueError('note unit')
                rev,op=(2,5) if code=='000080' else (1,2)
                if not ('영업' in rows[op][0] and rows[rev][0].replace(' ','') in ('외부거래','수익')):raise ValueError('not segment sales and op')
                values=[money(rows[i][-1]) for i in (rev,op)]
                deltas=[a-v*unit for a,v in zip(parsed[side],values)]
                if any(abs(z)>unit//2 for z in deltas):raise ValueError((rc,side,'notes not within filing precision',deltas))
                proof[side]=dict(table=idx,headers=rows[0],revenue_row=rows[rev],op_row=rows[op],note_unit_krw=unit,exact_KRW_minus_display_scaled=deltas)
            docs.append(dict(receipt=rc,version=meta['version'],period=meta['period_end'],filed=meta['filing_date'],
                        available_session=meta['available_session'],identity=meta['identity_status'],comparator_identity=meta['comparator_identity_status'],
                        source_xbrl=xurl,xbrl_sha256=xhash,source_notes=nurl,notes_sha256=nhash,note_section=kind,values=parsed,segment_notes=proof))
        if docs[0]['values']['prior']!=docs[2]['values']['current'] or docs[1]['values']['prior']!=docs[3]['values']['current']:
            raise ValueError('prior historical comparison mismatch')
        for d in DATES:
            filings=[r for r in versions if r['stock_code']==code and r['filing_date']<d and r['period_end'] in {s['period'] for s in docs}]
            if set(r['receipt'] for r in filings)!=set(receipts) or any(r['version']!='original' for r in filings):raise ValueError('unexpected version by formation '+d)
        quarters={s:[x-y for x,y in zip(docs[0]['values'][s],docs[1]['values'][s])] for s in ['current','prior']}
        result[code]=dict(formation_dates=list(DATES),receipts=docs,derived=[quarters['current'],quarters['prior']],order=['revenue_KRW','operating_profit_KRW'],
            decision='PASS_same_as_reported_basis',independent_direct_Q4_publication=False)
    dest.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('packages','register','dest'):p.add_argument(n,type=Path)
    run(**vars(p.parse_args()))
