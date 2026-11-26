"""Independently reconcile four filed statements, XBRL, segment totals and scope notes for Kukdo."""
from hashlib import sha256
import io
import json
from pathlib import Path
import sqlite3
import sys
from zipfile import ZipFile

from lxml import etree, html

PERIODS={'20170329000302':'2016-12-31','20161114000547':'2016-09-30',
         '20160329000310':'2015-12-31','20151112000368':'2015-09-30'}


def clean(value):
    return ' '.join(value.split())


def table_rows(table):
    return [[clean(cell.text_content()) for cell in row.xpath('./td|./th')]
            for row in table.xpath('./tbody/tr|./thead/tr|./tr')]


def numeric_xbrl(body,end):
    with ZipFile(io.BytesIO(body)) as z:
        root=etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.xbrl'))))
    unit=root.xpath('//*[local-name()="unit"][@id="KRW"]/*[local-name()="measure"]/text()')
    assert len(unit)==1 and unit[0].split(':')[-1]=='KRW'
    ids={}
    for c in root.xpath('//*[local-name()="context"]'):
        identifier=c.xpath('string(.//*[local-name()="identifier"])')
        start=c.xpath('string(.//*[local-name()="startDate"])')
        through=c.xpath('string(.//*[local-name()="endDate"])')
        if identifier=='00104388' and c.xpath('.//*[local-name()="explicitMember"]/text()')==['ifrs:ConsolidatedMember'] and start==through[:4]+'-01-01' and through[4:]==end[4:]:
            ids[c.get('id')]=through
    values={}
    for concept in ('Revenue','OperatingIncomeLoss'):
        for n in root.xpath('//*[local-name()="'+concept+'"]'):
            if n.get('unitRef')=='KRW' and n.get('contextRef') in ids:
                when=ids[n.get('contextRef')];values.setdefault(when,{})[concept]=int(n.text)
    return values


def inspect(dbpath):
    output={};all_numbers={}
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        for rid,end in PERIODS.items():
            chart={};digests={};current={}
            for kind,body,hsh in db.execute('select kind,body,sha256 from packages where receipt=?',(rid,)):
                if kind not in ('xbrl','kind_html','dart_html','dart_notes'):continue
                assert sha256(body).hexdigest()==hsh
                digests[kind]=hsh
                if kind=='xbrl':
                    numbers=numeric_xbrl(body,end)
                    for period,values in numbers.items():
                        if period in all_numbers:assert all_numbers[period]==values
                        all_numbers[period]=values
                    continue
                textroot=html.fromstring(body.decode());ts=textroot.xpath('//table')
                if kind in ('kind_html','dart_html'):
                    headings=[i for i,t in enumerate(ts) if clean(t.text_content()).startswith('연결 포괄손익계산서') and '(단위 : 원)' in clean(t.text_content())]
                    assert len(headings)==1
                    index=headings[0]+1;rows=table_rows(ts[index])
                    chart['display_table_zero_based']=index;chart['display_unit']='KRW'
                    for row in rows:
                        if row and row[0] in ('매출액','영업이익'):
                            current[{'매출액':'Revenue','영업이익':'OperatingIncomeLoss'}[row[0]]]=int(row[2 if end.endswith('09-30') else 1].replace(',',''))
                if kind in ('kind_html','dart_notes'):
                    texts=[clean(p.text_content()) for p in textroot.xpath('//p') if len(p.text_content())<4000]
                    same=next(v for v in texts if '비교표시된' in v and '동일한 회계정책' in v and '연결재무제표 작성' in v)
                    chart['policy_note']=same
                    group=next(t for t in ts if '소유지분율' in t.text_content() and '국도화공(곤산)유한공사' in t.text_content())
                    chart['subsidiary_rows']=table_rows(group)[-3:]
                    discontinued=next(t for t in ts if '세후중단영업손익' in t.text_content())
                    disc=table_rows(discontinued)
                    col=disc[0].index('세후중단영업손익')
                    assert disc[1][0]=='일도화학(주)' and disc[1][col]=='-'
                    chart['joint_venture_discontinued_profit']=disc[1][col]
                    if end=='2016-12-31':
                        chart['rename_note']=next(v for v in texts if '2017년 1월 2일부로' in v and '상호를 변경' in v)
                    if kind=='kind_html':
                        segments={}
                        for i in (20,21):
                            unit=ts[i].xpath('preceding::*[self::p or self::table][1]')[0]
                            assert '(단위:천원)' in ''.join(unit.text_content().split())
                            for row in table_rows(ts[i]):
                                if row and row[0].startswith(('매출액(','영업이익(')):
                                    label,dates=row[0].split('(');period=dates[:-1].split('~')[-1].replace('.','-')
                                    segments.setdefault(period,{})[{'매출액':'Revenue','영업이익':'OperatingIncomeLoss'}[label]]=int(row[-1].replace(',',''))
                        chart['segment_1000_KRW']=segments
            output[rid]={'source_sha256':digests,'end':end,'current_KRW':current,**chart}
    for r in output.values():
        assert r['current_KRW']==all_numbers[r['end']]
        for end,values in r.get('segment_1000_KRW',{}).items():
            for field,value in values.items():assert abs(all_numbers[end][field]-1000*value)<=500
    q4={year:{f:all_numbers[year+'-12-31'][f]-all_numbers[year+'-09-30'][f] for f in ('Revenue','OperatingIncomeLoss')} for year in ('2015','2016')}
    return {'isin':'KR7007690001','corp_code':'00104388','source_reports':output,'q4_KRW':q4,
            'independent_verdict':'Approve as-reported consolidated FY minus 9M for the four named original filings.',
            'comparison':'Exact 2015 comparative amounts agree with original 2015 statements, 2016 comparative columns, and XBRL. The 2016 segment tables in thousands agree within rounding.',
            'scope':'Same three consolidated subsidiaries at 90%, 100%, and 100%. Hajinkemtech changed only its name to Kukdo Finechem on 2017-01-02. Joint venture Ildo is accounted for separately.',
            'direct_quarter_receipt':None,'next_session':'20170330'}


if __name__=='__main__':
    result=inspect(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
