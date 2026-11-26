"""Recheck raw CFS XBRL and issuer display independently from the extraction code."""
import csv,hashlib,io,json,re,sqlite3,sys,zipfile
from pathlib import Path
from lxml import etree,html

config=[('20180330000582','2017-12-31',186),('20171114000220','2017-09-30',184),('20170331000549','2016-12-31',None),('20161114000295','2016-09-30',None)]
q=sqlite3.connect(Path(sys.argv[1]).resolve().as_uri()+'?mode=ro',uri=True)
facts={};reports=[]
for rid,end,index in config:
    rows=q.execute('select document,kind,body,sha256 from packages where receipt=?',(rid,))
    report={'receipt':rid,'period_end':end,'corp_code':'00150244','raw':{}}
    for document,kind,body,sha in rows:
        assert hashlib.sha256(body).hexdigest()==sha
        if kind not in ('xbrl','kind_html','dart_notes','dart_overview'): continue
        report['raw'][kind]={'document':document,'sha256':sha}
        if kind=='xbrl':
            z=zipfile.ZipFile(io.BytesIO(body))
            root=etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith('.xbrl'))))
            unit=root.xpath('//*[local-name()="unit"][@id="KRW"]/*[local-name()="measure"]/text()')
            assert len(unit)==1 and unit[0].split(':')[-1]=='KRW'
            ctx={}
            for node in root.xpath('//*[local-name()="context"]'):
                v=lambda n:node.xpath('string(.//*[local-name()="'+n+'"])')
                d=v('endDate');members=node.xpath('.//*[local-name()="explicitMember"]/text()')
                if members!=['ifrs:ConsolidatedMember'] or v('identifier')!='00150244' or v('startDate')!=d[:4]+'-01-01' or d[4:]!=end[4:]:continue
                ctx[node.get('id')]=d
            for tag in ('Revenue','OperatingIncomeLoss'):
                for item in root.xpath('//*[local-name()="'+tag+'"]'):
                    if item.get('contextRef') not in ctx or item.get('unitRef')!='KRW': continue
                    when=ctx[item.get('contextRef')];assert facts.get((when,tag),int(item.text))==int(item.text)
                    facts[(when,tag)]=int(item.text)
            report['audit']={tag:sorted({(item.text or '').strip() for item in root.xpath('//*[local-name()="'+tag+'"]') if (item.get('contextRef') or '').endswith('PeriodCoveredbytheReportofCurrentFiscalYearorQuarterorHalfYearMember')}) for tag in ('ConsolidatedAuditType','ConsolidatedAuditOpinion','ConsolidatedAuditReportDate')}
        elif kind in ('dart_notes','dart_overview'):
            root=html.fromstring(body.decode())
            texts=[' '.join(n.text_content().split()) for n in root.xpath('//p|//tr') if 1<len(n.text_content())<4500]
            if kind=='dart_notes':
                vietnam=[v for v in texts if 'VIETNAM' in v and '종속기업에 추가' in v]
                segment=[v for v in texts if '수입맥주' in v and '비교표시' in v and '맥주부문으로 변경' in v]
                assert len(vietnam)==len(segment)==1 and not any('중단영업' in v for v in texts)
                report['prior_original_notes']={'vietnam_inclusion':vietnam[0],'segment_comparatives':segment[0],
                    'contains_discontinued_operations_label':False}
            else:
                idx=next(i for i,v in enumerate(texts) if '연결대상회사의 변동' in v)
                scope=texts[idx:idx+6]
                assert any('신규연결 HITEJINRO VIETNAM' in v for v in scope) and '연결제외 - -' in scope
                report['prior_original_group_change']=scope
        elif kind=='kind_html' and index is not None:
            root=html.fromstring(body.decode());tables=root.xpath('//table')
            heading=' '.join(tables[index-1].text_content().split());assert '연결 포괄손익계산서' in heading and '(단위 : 원)' in heading
            table={node.xpath('./td|./th')[0].text_content().strip():[cell.text_content().strip() for cell in node.xpath('./td|./th')[1:]] for node in tables[index].xpath('.//tr') if node.xpath('./td|./th')}
            vals={}
            for tag,label in [('Revenue','수익(매출액)'),('OperatingIncomeLoss','영업이익')]:
                cells=table[label];vals[tag]=[int(cells[i].replace(',','')) for i in ((1,3) if end.endswith('09-30') else (0,1))]
            report['kind_CFS']={'table_index_zero_based':index,'heading':heading,'amounts_current_and_prior_KRW':vals}
    reports.append(report)
for report in reports:
    end=report['period_end']
    report['current_KRW']={tag:facts[end,tag] for tag in ('Revenue','OperatingIncomeLoss')}
    for tag,ys in report.get('kind_CFS',{}).get('amounts_current_and_prior_KRW',{}).items():
        for off,val in enumerate(ys):assert facts[(str(int(end[:4])-off)+end[4:],tag)]==val
result={'issuer':'000080','basis':'as-reported statutory consolidated annual minus statutory consolidated Jan-Sep; KRW','sources':reports,
        'q4_KRW':{yr:{tag:facts[(yr+'-12-31',tag)]-facts[(yr+'-09-30',tag)] for tag in ('Revenue','OperatingIncomeLoss')} for yr in ('2016','2017')},
        'current_display_and_all_four_originals_match':True,
        'current_group_notes':'Both 2017 submissions show no new or excluded subsidiaries during 2017. HITEJINRO VIETNAM is identified as newly included in the prior year.',
        'current_policy_notes':'2017 interim notes identify the change to IAS 12/K-IFRS 1012 as having no effect on this consolidated group. K-IFRS 1115 identified as effective from 2018-01-01.',
        'prior_notes_review':'Both official 2016 reports include the same Vietnamese subsidiary from within the first nine months and list no excluded subsidiary. Imported beer moved between segments; the consolidated totals agree across all four original reports and both 2017 comparative displays.',
        'direct_standalone_q4_source':None,
        'review_decision':'Approved for as-reported annual-minus-nine-month consolidated revenue and operating income on these four receipts only.'}
assert all('prior_original_group_change' in report and 'prior_original_notes' in report for report in reports[2:])
Path(sys.argv[2]).write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
