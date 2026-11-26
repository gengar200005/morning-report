"""Check pretranscribed exact contexts in an original XBRL submission and compare with the general reader."""
import argparse
import calendar
import csv
from datetime import date
from hashlib import sha256
import io
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile
from lxml import etree
from pit_facts import extract_receipt

FIELDS=('revenue_current','revenue_prior','operating_profit_current','operating_profit_prior')
RAW_FIELDS=('rev_current','rev_prior','op_current','op_prior')


def read(path):
    with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def compare(manual, fixed, register, packages, output):
    drawn={(r['stock_code'],r['period_end']) for r in read(fixed)}
    metadata={(r['stock_code'],r['receipt']):r for r in read(register) if r['identity_status']=='PASS'}
    con=sqlite3.connect('file:'+str(packages.resolve())+'?mode=ro',uri=True)
    results=[]
    for r in read(manual):
        code,receipt=r['code'],r['receipt']
        reg=metadata[code,receipt]
        end=date.fromisoformat(reg['period_end'])
        if (code,end.isoformat()) not in drawn and r['role']!='nine_month_only_ofs':raise ValueError('non-frozen company-period')
        doc,url,digest,raw=con.execute("""SELECT document,source,sha256,body FROM packages p
            WHERE receipt=? AND kind='xbrl' AND NOT EXISTS(SELECT 1 FROM quarantine q WHERE (q.receipt,q.kind)=(p.receipt,p.kind))""",(receipt,)).fetchone()
        if digest!=sha256(raw).hexdigest():raise ValueError('source digest mismatch')
        with ZipFile(io.BytesIO(raw)) as archive:
            filename,=[p for p in archive.namelist() if p.lower().endswith('.xbrl')]
            instance=archive.read(filename)
        root=etree.fromstring(instance)
        contexts={};cfs_count=0;ofs_count=0
        for node in root.xpath('./*[local-name()="context"]'):
            members=node.xpath('.//*[local-name()="explicitMember"]')
            cfs_count+=any(m.text.endswith(':ConsolidatedMember') for m in members)
            ofs_count+=any(m.text.endswith(':SeparateMember') for m in members)
            if len(members)!=1 or not members[0].text.endswith(':ConsolidatedMember') or node.xpath('.//*[local-name()="typedMember"]'):continue
            if not members[0].get('dimension','').endswith(':ConsolidatedAndSeparateFinancialStatementsAxis'):continue
            ids=node.xpath('.//*[local-name()="identifier"]/text()')
            if ids!=[reg['corp_code']]:raise ValueError('wrong issuer')
            bounds=node.xpath('.//*[local-name()="startDate"]/text() | .//*[local-name()="endDate"]/text()')
            if len(bounds)!=2:continue
            for side,year in [('current',end.year),('prior',end.year-1)]:
                want=[date(year,end.month-2,1).isoformat(),date(year,end.month,calendar.monthrange(year,end.month)[1]).isoformat()]
                if bounds==want:contexts[node.get('id')]=(side,*bounds)
        expected={k:int(r[rk]) if r[rk] else None for k,rk in zip(FIELDS,RAW_FIELDS)}
        if r['role'] in ('only_ofs','nine_month_only_ofs') and not (cfs_count==0 and ofs_count>0):raise ValueError('OFS role mismatch')
        traces={k:[] for k in FIELDS}
        for fact in root:
            ctx=fact.get('contextRef')
            if ctx not in contexts:continue
            q=etree.QName(fact)
            field={'Revenue':'revenue','OperatingIncomeLoss':'operating_profit'}.get(q.localname)
            if not field:continue
            side,a,b=contexts[ctx];key=field+'_'+side
            units=root.xpath('./*[local-name()="unit"][@id=$ref]/*[local-name()="measure"]',ref=fact.get('unitRef'))
            if len(units)!=1:raise ValueError('unit not simple')
            pu,lu=units[0].text.split(':')
            if lu!='KRW' or units[0].nsmap[pu]!='http://www.xbrl.org/2003/iso4217':raise ValueError('unit not ISO KRW')
            if int(fact.text)!=expected[key]:raise ValueError((receipt,key,'locked literal disagrees'))
            traces[key].append(dict(qualified_tag=fact.tag,context=ctx,start=a,end=b,iso_unit='KRW',
                                decimals=fact.get('decimals'),literal=fact.text))
        if any(v is not None and not traces[k] for k,v in expected.items()):raise ValueError('missing source rendition')
        canonical=extract_receipt(receipt,doc,reg['corp_code'],end.isoformat(),'xbrl',raw,digest)
        auto={k:canonical['3'][k].get('value') for k in FIELDS}
        if auto!=expected:raise ValueError((receipt,'canonical vs locked',auto,expected))
        results.append(dict(stock_code=code,receipt=receipt,period_end=end.isoformat(),kind_receipt=reg['kind_receipt'],
                filing_kst=reg['kind_timestamp'],available_session=reg['available_session'],role=r['role'],manual=expected,
                sha256=digest,source_url=url,format='xbrl_only_independent_raw_context_read',
                scope_note=r['review_note'],cfs_contexts=cfs_count,ofs_contexts=ofs_count,instance_sha256=sha256(instance).hexdigest(),
                raw_trace=traces,xbrl={'values':auto,'match':[True]*4,'source_sha256':digest,'source_url':url}))
    output.write_text(json.dumps({'input_sha256':sha256(manual.read_bytes()).hexdigest(),
        'scope':'Independent literal/context reading and program replay of a single archive format. No independent KIND monetary proof claimed. OFS-only describes the archived instance.',
        'rows':results},indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('manual','fixed','register','packages','output'):p.add_argument(k,type=Path)
    compare(**vars(p.parse_args()))
