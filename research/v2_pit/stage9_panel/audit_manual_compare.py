"""Check locked manual table coordinates and four KRW cells against immutable dual-source receipt blobs."""
import argparse
import csv
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from lxml import html
from pit_facts import extract_receipt

BASE=Path(__file__).resolve().parent
FIELDS=('revenue_current','revenue_prior','operating_profit_current','operating_profit_prior')
KEYS=('rev_current','rev_prior','op_current','op_prior')


def records(path):
    with path.open(newline='',encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def number(text, scale):
    s=re.sub(r'[\s,]','',text)
    if not s or s in ('-','—','–'):return None
    if s.startswith('(') and s.endswith(')'):s='-'+s[1:-1]
    v=Decimal(s)*scale
    if v!=v.to_integral_value():raise ValueError('noninteger KRW')
    return int(v)


def compare(manual, roster, receipts, packages, output):
    people=records(manual)
    if len({r['receipt'] for r in people})!=len(people):
        raise ValueError('duplicate manual read')
    fixed={(r['stock_code'],r['period_end']) for r in records(roster)}
    register={(r['stock_code'],r['receipt']):r for r in records(receipts) if r['receipt']}
    db=sqlite3.connect('file:'+str(packages.resolve())+'?mode=ro',uri=True)
    results=[]
    for reading in people:
        rc=reading['receipt']
        meta=register[reading['code'],rc]
        end=date.fromisoformat(meta['period_end']).isoformat()
        role=reading['role']
        if (reading['code'],end) not in fixed and role not in ('nine_month_support','prior_annual_support','prior_nine_support','nine_month_no_cfs'):
            raise ValueError('unexpected sample')
        if meta['identity_status']!='PASS' and role!='post_delist_financial':
            raise ValueError('unverified issuer in investable audit case')
        if reading['code']!=meta['stock_code']:
            raise ValueError('issuer mismatch')
        by_type={kind:(doc,sp,h,b) for kind,doc,sp,h,b in db.execute('SELECT kind,document,source,sha256,body FROM packages AS p WHERE receipt=? AND NOT EXISTS(SELECT 1 FROM quarantine AS q WHERE (q.receipt,q.kind)=(p.receipt,p.kind))',(rc,))}
        display_kind=reading.get('display_format') or ('kind_html' if 'kind_html' in by_type else 'dart_html')
        doc,sp,h,b=by_type[display_kind]
        if sha256(b).hexdigest()!=h or (reading.get('expected_display_sha256') and reading['expected_display_sha256']!=h):raise ValueError('display hash')
        tree=html.fromstring(b.decode('utf-8'))
        tablelist=tree.xpath('//table')
        if role in ('no_cfs','nine_month_no_cfs'):
            text=' '.join(tree.text_content().split())
            if reading['scope_note'] not in text:raise ValueError('missing scope statement')
            header=None; labels=[]
        else:
            meta_t,body_t=(tablelist[int(reading[k])] for k in ('meta_table','table'))
            header=' '.join(meta_t.text_content().split())
            scale=int(reading['multiplier'])
            unit={1:'원',1000:'천원',1000000:'백만원'}[scale]
            if not re.search(r'단위[:：]'+unit+r'[)）]',re.sub(r'\s','',header)):
                raise ValueError(('manual unit metadata mismatch',rc,header))
            vals=[]; labels=[]
            table_rows=body_t.xpath('./thead/tr|./tbody/tr|./tr')
            for key in ('rev_row','op_row'):
                if reading[key]=='':
                    vals.extend([None,None]);labels.append(None)
                    continue
                cells=table_rows[int(reading[key])].xpath('./th|./td')
                labels.append(' '.join(cells[0].text_content().split()))
                vals.extend(number(cells[int(reading[c])].text_content(),scale) for c in ('current_col','prior_col'))
        expected={field:int(reading[k]) if reading[k] else None for field,k in zip(FIELDS,KEYS)}
        if role not in ('no_cfs','nine_month_no_cfs') and dict(zip(FIELDS,vals))!=expected:
            raise ValueError(('manual transcription vs selected cells',rc,vals,expected))
        duration={'quarter':'3','annual':'12','nine_month_support':'9','prior_annual_support':'12','prior_nine_support':'9','nine_month_no_cfs':'9','no_cfs':'3','cumulative_only':'3','post_delist_financial':'3'}[role]
        result={'stock_code':reading['code'],'period_end':end,'receipt':rc,'kind_receipt':meta['kind_receipt'],
                'filing_kst':meta['kind_timestamp'],'available_session':meta['available_session'],'role':role,
                'manual':expected,'sha256':h,'source_url':sp,'metadata_header':header,'labels':labels,'scope_note':reading['scope_note'],'format':'human_read_display','display_type':display_kind,'identity_status':meta['identity_status'],'filing_date':meta['filing_date']}
        for fmt,(dn,url,digest,raw) in by_type.items():
            if fmt in ('kind_html','dart_html') and duration!='3':
                continue
            facts=extract_receipt(rc,dn,meta['corp_code'],end,fmt,raw,digest)
            got={f:facts.get(duration,{}).get(f,{}).get('value') for f in FIELDS}
            result[fmt]={'values':got,'match':[got[f]==expected[f] for f in FIELDS],'source_sha256':digest,'source_url':url}
        results.append(result)
    out={'input_sha256':sha256(manual.read_bytes()).hexdigest(),'fixed_sha256':sha256(roster.read_bytes()).hexdigest(),
         'rows':results,'remaining_read_count':len(fixed-{(r['stock_code'],r['period_end']) for r in results})}
    output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('manual','roster','receipts','packages','output'):p.add_argument(n,type=Path)
    compare(**vars(p.parse_args()))
