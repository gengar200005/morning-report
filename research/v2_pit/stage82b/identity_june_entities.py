"""Recheck June formation-date entity identity, original versions and non-December fiscal quarters."""
import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
import sys

from lxml import html

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from filing_xbrl import extract
from stage82b.display_fields import extract_display_fields, no_consolidated_statement

PRIOR = {
    '018500': '20210215001130', '002630': '20210215000868', '008110': '20210215000983',
    '092440': '20210215000707', '001720': '20210210000924', '004310': '20210414000539',
}
PARENT = {
    '003550': ('20210517001312', '20210503000422', '비교표시된 연결손익계산서도 이에 따라 재작성되었습니다.'),
    '007700': ('20210517002096', '20210503000269', '비교표시된 전분기 분기연결포괄손익계산서도 이에 따라 재작성 되었습니다.'),
    '102260': ('20210517002091', '20210401000557', '(주)동성화학은 (주)동성코퍼레이션의 연결대상 종속기업이므로'),
}
OTHER = {
    '361610': (['20210507000691','20210513000071'], 'preliminary_report_only'),
    '380440': (['20210518000370'], 'new_spac_no_prior_year_and_no_periodic_filing'),
    '383220': (['20210518000357','20210503000269'], 'new_company_after_quarter_end_no_own_periodic_filing'),
    '383800': (['20210525000477','20210503000422'], 'new_company_after_quarter_end_no_own_periodic_filing'),
    '005190': (['20210413000181','20210401000557'], 'delisted_before_formation'),
}
FIELDS = ('revenue','operating_profit')
SIDE_NOTES = {
    '361610': 'Listing review records 2019-04-01 as the creation date. On 2021-05-13 the company published preliminary results. Neither the KIND security list nor the OpenDART filing-type search identified an eligible own periodic report with a current three-month pair.',
    '380440': 'IPO notice identifies SPAC, 2021-05-21 listing and 2021-03-04 dividend start. The later issuer confirmation of the formation date is an identity annotation only.',
    '383220': 'Fashion business separated from 007700 effective 2021-05-01. The 2021-05-03 report records application for split registration. Predecessor segment or discontinued-operation figures cannot supply an original of 383220.',
    '383800': 'Investment division separated from 003550 effective 2021-05-01. The 2021-05-03 report lists the planned registration application. The parent report does not qualify as an original of 383800.',
    '005190': 'Acquired by parent 102260 on 2021-04-01. KRX notice names 2021-04-16 as delisting date.',
    '003550': 'LX business classified as discontinued. Current and comparative CFS operating lines cover continuing operations. The revenue label is 매출 및 지분법 손익, identical to the receipt-bound XBRL revenue pair; retain original sector/product rules.',
    '007700': 'Fashion business classified as discontinued in both periods. Direct continuing CFS revenue and operating income match XBRL; do not apply old combined sales to either surviving or newly listed issuer.',
    '102260': 'Merger report confirms 005190 already was a CFS subsidiary. Historical group revenue and operating income remain comparable. No reassignment of subsidiary amounts. EPS and standalone perimeters not evaluated.',
}
def load(p):
    return json.loads(p.read_text())
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def normal(s):
    return ''.join(s.split())
def source(raw, receipt):
    proof=load(raw/(receipt+'-proof.json'))
    assert all(digest(raw/(receipt+suffix))==proof[key] for suffix,key in
               [('.htm','source_sha256'),('.index.html','viewer_sha256'),('.pointer.html','pointer_sha256')])
    viewer=html.fromstring((raw/(receipt+'.index.html')).read_bytes().decode())
    assert '('+proof['code']+')' in viewer.xpath('string(//header//h1)')
    return {k:proof[k] for k in ('receipt','code','title','date','document','source_url','source_sha256','pointer_sha256','viewer_sha256')}
def main(raw, census, special, out):
    securities=load(raw/'securities.json')
    cross={r['stock_code']:r for r in csv.DictReader(census.open())}
    annual={r['stock_code']:r for r in load(special)['rows'] if r['stock_code'] in PRIOR}
    evidence={}
    issuers=[]
    for code in sorted(set(PRIOR)|set(PARENT)|set(OTHER)):
        secular=securities['20210601']['rows'].get(code) or securities['20210331']['rows'][code]
        filings=load(raw/(code+'.json'))
        reports=[f for f in filings if any(t in f['title'] for t in ('분기보고서','반기보고서','사업보고서'))]
        row={'stock_code':code,'isin':secular['isin'],'name':secular['name'],'listing_date':secular['listing_date'],
             'formation_member':code in securities['20210601']['rows'],'scope':'','unit':'KRW','receipt':None,
             'available_session':None,'period_current':None,'period_prior':None,'F2_status':'BLOCKED','F3_status':'BLOCKED',
             'regulatory_periodic_filings_to_cutoff':[{k:r[k] for k in ('receipt','title','date')} for r in sorted(reports,key=lambda r:r['date'])],
             'metrics':{},'reason':None}
        filings_pages=sorted(raw.glob(code+'-p*.html'))
        row['kind_search_page_sha256']=[digest(f) for f in filings_pages]
        ids=[]
        if code in PRIOR:
            rid=PRIOR[code];ids=[rid]
            assert sorted(reports,key=lambda r:r['date'])[-1]['receipt']==rid
            proof=source(raw,rid); filed=proof['date'][:10].replace('-','')
            end='2021-02-28' if code=='004310' else '2020-12-31'
            cperiod=end.replace('-','')
            assert all(securities[t]['rows'][code]['isin']==secular['isin'] for t in (cperiod,filed,'20210601'))
            age=(date(2021,6,1)-date.fromisoformat(end)).days
            assert age<=180
            row.update(quarter_end=cperiod,age_days=age,available_session=securities[filed]['next'],kind_receipt=rid,
                       published_kst=proof['date'],latest_version='original',period_check='latest available periodic filing: complete issuer search through 2021-06-01')
            d=load(raw/(rid+'-dart.json'))
            if code in annual:
                a=annual[code]
                assert a['filing_date']>'2021-06-01'
                row['following_march_annual_after_cutoff']={k:a[k] for k in ('filing_date','kind_receipt','first_available_session')}
                row['following_march_annual_after_cutoff']['dart_receipt']=(a.get('dart') or {}).get('receipt')
            if code=='001720':
                row['reason']='financial_sector; excluded under frozen nonfinancial definition'
            else:
                assert len(d)==1 and d[0]['source_page_sha256']==digest(raw/(rid+'.dartlist.html'))
                r=d[0];raw_x=raw/(rid+'.zip');xh=digest(raw_x);details=load(raw/(rid+'-xbrl.json'))
                assert xh==details['sha256']
                row.update(receipt=r['dart_receipt'],corp_code=r['corp_code'],source=details['source_url'],sha256=xh)
                body=(raw/(rid+'.htm')).read_bytes()
                scope='OFS' if no_consolidated_statement(body) else 'CFS'
                display=extract_display_fields(body,scope,end,False,standalone_confirmed=(scope=='OFS'))
                assert all(display['fields'][field]['status']=='PASS' for field in FIELDS)
                metrics={field:[display['fields'][field][t] for t in ('current','prior')] for field in FIELDS}
                row.update(scope=scope,metrics=metrics,period_current='/'.join(v.replace('-','') for v in display['periods'][0]),
                           period_prior='/'.join(v.replace('-','') for v in display['periods'][1]))
                if scope=='CFS':
                    submitted=extract(raw_x,r['dart_receipt'],r['document'],r['corp_code'],2020,4,xh)
                    for field in FIELDS:
                        assert [int(submitted['fields'][k][field]['value']) for k in ('current','prior_as_reported')]==metrics[field]
                    row.update(F2_status='PASS',F3_status='PASS',reason='independent XBRL and KIND 3-month CFS values match')
                else: row['reason']='explicit_no_consolidated_statement; reported standalone metrics only'
        elif code in PARENT:
            rid,action,label=PARENT[code];ids=[rid,action];row['reason']=SIDE_NOTES[code]
            c=cross[code]
            assert c['isin']==row['isin'] and c['receipt']==c['original_receipt'] and c['scope']=='CFS'
            ref=action if code=='102260' else rid
            body=html.fromstring((raw/(ref+'.htm')).read_bytes().decode())
            assert normal(label) in normal(body.text_content())
            for key in ('corp_code','receipt','available_session','quarter_end','period_current','period_prior','scope','source','sha256','F2_status','F3_status'):
                row[key]=c[key]
            row['metrics']={field:[int(c[field+'_'+t+'_KRW']) for t in ('current','prior')] for field in FIELDS}
            row['kind_receipt']=rid
        else:
            ids,row['reason']=OTHER[code]
            if code!='005190':
                assert not reports
                newdart=[r for r in load(raw/'newdart.json') if r['code']==code]; assert len(newdart)==3
                row['opendart_checked_reports']=[{'type':q['query']['rptType'],'rows':q['rows'],'sha256':q['source_sha256']} for q in newdart]
            if code=='361610':
                rid='20210513000071';proof=source(raw,rid)
                tx=normal(html.fromstring((raw/(rid+'.htm')).read_bytes().decode()).text_content())
                assert all(v in tx for v in ('백만원','139,232','99,653','32,363','26,922'))
                row['preliminary_only']={'scope':'CFS','unit':'KRW million','revenue':[139232,99653],'operating_profit':[32363,26922],'kind_receipt':rid,'next_session':securities['20210513']['next']}
            row['note']=SIDE_NOTES[code]
            if code=='361610':
                row['formation_reference']={'date':'2019-04-01','basis':'official historical listing review, effective date',
                    'url':'https://kind.krx.co.kr/listinvstg/listinvstgcom.do?bizProcNo=20200731000069&method=searchListInvstgCorpDetail',
                    'sha256':digest(raw/'sk-listing-review.htm')}
            if code=='380440':
                row['formation_reference']={'date':'2021-03-04','basis':'retrospective confirmation of creation date only; no financial input',
                    'url':'https://kind.krx.co.kr/external/2022/08/03/000209/20220803000559/11012.htm',
                    'sha256':load(raw/'nh-formation-excerpt.json')['sha256']}
                row['krx_listing_industry']='금융 지원 서비스업 (11-66-01); sector for ranking comes from formation-date WICS'
        for rid in ids:evidence[rid]=source(raw,rid)
        row['source_receipts']=ids
        if row['F2_status']=='PASS':
            rev,prev=row['metrics']['revenue'];op,pop=row['metrics']['operating_profit']
            assert min(rev,prev)>0
            row.update(F2_pp=100*(op/rev-pop/prev),F3_fraction=rev/prev-1)
        issuers.append(row)
    output={'as_of':'20210601','membership':securities['membership_change'],'issuers':issuers,
            'corporate_actions':{'003550':['383800'],'007700':['383220'],'102260':['005190']},
            'corporate_action_direction':'retained issuer to separated or absorbed issuer; see issuer records for direction and effective dates',
            'source_receipts':dict(sorted(evidence.items())),
            'scope_note':'KIND issuer originals and amendments searched 2020-12-01 to 2021-06-01. OpenDART three periodic form searches confirm no own filing with a direct comparable quarter for four entrants. Only the 4 prior-period CFS original pairs add new rankable observations. Explicit OFS figures and provisional reports have no rank.'}
    out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('raw','census','nondec','out'):p.add_argument(key,type=Path)
    a=p.parse_args();main(a.raw,a.census,a.nondec,a.out)
