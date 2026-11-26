"""Archive issuer-period search pages from KIND, DART full periodic search and the OpenDART XBRL directory."""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

from lxml import html

KIND='https://kind.krx.co.kr/disclosure/details.do'
DART='https://dart.fss.or.kr/dsab007/detailSearch.ax'
PORTAL='https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrl/list.do'
TYPES={'사업보고서':'11011','반기보고서':'11012','분기보고서':'11013'}
ACCESS_LOCK=threading.Lock()
LAST=0.0
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
def clean(text):
    return ' '.join(text.split())
def digest(data):
    return hashlib.sha256(data).hexdigest()
def save(path,obj):
    tmp=path.with_name(path.name+'.new');tmp.write_text(json.dumps(obj,ensure_ascii=False));tmp.replace(path)
def fetch(f,url,params,service):
    global LAST
    if f.is_file():return f.read_bytes()
    refer={'K':KIND+'?method=searchDetailsMain','D':'https://dart.fss.or.kr/dsab007/main.do','X':PORTAL.replace('list.do','main.do')}[service]
    for attempt in range(3):
        with ACCESS_LOCK:
            time.sleep(max(0,.47-(time.monotonic()-LAST)));LAST=time.monotonic()
        q=urlencode(params,doseq=True).encode()
        get=service=='D' and attempt!=1
        req=Request(url+'?'+q.decode() if get else url,data=None if get else q,
                    headers={'User-Agent':'Mozilla/5.0','Referer':refer,'X-Requested-With':'XMLHttpRequest'})
        try:
            with urlopen(req,timeout=17) as response: body=response.read()
            if len(body)<150 or (service!='K' and b'pageInfo' not in body and b'page_info' not in body):
                raise ValueError('invalid or incomplete result page')
            if service=='K' and b'<script>alert(' in body:raise ValueError('KIND range alert')
            f.write_bytes(body);return body
        except Exception:
            if attempt==2:raise
            time.sleep(.5+attempt)
def kind_period(w,base,start,end,market='1',specific=None):
    key='K'+(specific or ('P' if market else 'A'))+'-'+start.replace('-','')+'-'+end.replace('-','')
    dest=w/'parsed'/(key+'.json')
    if dest.exists():return
    form={**base,'method':'searchDetailsSub','fromDate':start,'toDate':end,'marketType':market,
          'currentPageSize':100,'orderMode':'','orderStat':'','reportNm':'','reportNmTemp':'','disTypevalue':'05'}
    for param in ('disclosureType05','disclosureTypeArr05','pDisclosureType05'):form[param]='0501|0502|0503'
    if specific:form.update(repIsuSrtCd='A'+specific,searchCodeType='number',searchCorpName='',allRepIsuSrtCd='')
    found=[];page=1;count=None
    while True:
        pagepaths={}
        for forward,prefix in [('details_sub','s'),('details_down','e')]:
            f=w/'raw'/f'{key}-{prefix}{page}.html';pagepaths[prefix]=fetch(f,KIND,{**form,'forward':forward,'pageIndex':page},'K')
        screen,export=pagepaths['s'],pagepaths['e']
        t=html.fromstring(screen.decode());x=html.fromstring(export.decode('cp949'))
        a=t.xpath('//tbody/tr[td]');info=t.xpath('//section[contains(@class,"paging-group")]//div[contains(@class,"info")]')
        if not info:
            if page==1 and '조회된 결과값이 없습니다' in t.text_content():
                count=0;break
            raise ValueError('Missing pagination')
        n=int(info[0].xpath('string(em)').replace(',',''));current=int(info[0].xpath('string(strong)'))
        if (count is not None and count!=n) or current!=page:raise ValueError('Changing pagination')
        count=n;xrows=x.xpath('//tr[td]')[1:] if x.xpath('//tr[1]/td') else x.xpath('//tr[td]')
        if len(a)!=len(xrows):raise ValueError('KIND screen/export length')
        records=[]
        for idx,(r,xr) in enumerate(zip(a,xrows)):
            cols=r.xpath('./td');v=[clean(c.text_content()) for c in xr.xpath('./td')]
            number,stamp,issuer,code,title,sub=v;link=cols[3].xpath('.//a')[0];nm=cols[2].xpath('.//a')[0]
            left=[clean(cols[0].text_content()),clean(cols[1].text_content()),clean(nm.text_content()),clean(link.text_content()).replace(' ',''),clean(cols[4].text_content())]
            if left!=[number,stamp,issuer,title.replace('[정]','').replace(' ',''),sub] or int(number)!=n-(page-1)*100-idx:raise ValueError('Inconsistent KIND row')
            if specific and code!=specific:raise ValueError('Unexpected issuer code')
            if not start<=stamp[:10]<=end:raise ValueError('Filing outside requested window')
            rid=re.search(r"'(\d{14})'",link.get('onclick'))[1]
            records.append(dict(stock_code=code,kind_receipt=rid,name=issuer,submitter=sub,title=left[3],kind_timestamp=stamp,
                                source_kind_sha256=digest(screen),source_kind_export_sha256=digest(export)))
        found.extend(records)
        save(w/'parsed'/f'{key}-p{page}.json',{'records':records,'page':page,'total':n,'start':start,'end':end})
        if page*100>=n:break
        page+=1
    if len(found)!=count or len({r['kind_receipt'] for r in found})!=count:raise ValueError('KIND missing/duplicate events')
    save(dest,{'records':found,'count':count,'pages':page,'start':start,'end':end,'market':market})
def d_query(w,issuer,service,report):
    code,cp,name=issuer;key=service+'-'+code+'-'+report
    dest=w/'parsed'/(key+'.json')
    if dest.exists():return
    start='20150101';end='20211201'
    if service=='D':
        form=dict(currentPage=1,maxResults=100,maxLinks=10,startDate=start,endDate=end,textCrpCik=cp,textCrpNm=name,businessCode='all',
                  option='corp',sort='date',series='asc',corporationType='all',publicType=['A001','A002','A003'])
    else:
        form=dict(pageIndex=1,pageSize=10,pageUnit=10,recordCountPerPage=100,textCrpNm=name,textCrpCik=cp,startDate='2015-01-01',
                  endDate='2021-12-01',rptType=report,sortStdr='date',sortOrdr='desc',isMultiCheck='')
    out=[];page=1;count=None;hashes=[]
    while True:
        form['currentPage' if service=='D' else 'pageIndex']=page
        f=w/'raw'/f'{key}-p{page}.html';raw=fetch(f,DART if service=='D' else PORTAL,form,service)
        t=html.fromstring(raw.decode());px=t.xpath('string(//*[@class="pageInfo" or @class="page_info"])').strip().replace(',','')
        m=re.fullmatch(r'\[(\d+)/(\d+)\]\s*\[총 (\d+)건\]',px)
        if not m:raise ValueError('Unknown DART pagination')
        current,pages,total=map(int,m.groups())
        if current!=page or (count is not None and count!=total):raise ValueError('Changing DART pagination')
        count=total;h=digest(raw);hashes.append(h)
        for tr in t.xpath('//tbody/tr[td]'):
            td=tr.xpath('./td')
            if len(td)<5:continue
            if service=='D':
                co=td[1].xpath('.//a[contains(@href,"openCorpInfoNew")]')[0];company=clean(co.text_content())
                corp=re.search(r"'(\d{8})'",co.get('href'))[1];rel=td[2].xpath('.//a[contains(@href,"rcpNo=")]')[0]
                rc=re.search(r'rcpNo=(\d{14})',rel.get('href'))[1];doc=None
            else:
                co=td[1].xpath('.//span[contains(@onclick,"openCorpInfo")]')[0];company=clean(co.text_content())
                corp=re.search(r"'(\d{8})'",co.get('onclick'))[1];rel=td[2].xpath('.//a')[0];rc=re.search(r"'(\d{14})'",rel.get('onclick'))[1]
                matches=re.findall(r'rcp_no=(\d{14})&(?:amp;)?dcm_no=(\d+)',html.tostring(tr,encoding='unicode'))
                if any(rr!=rc for rr,_ in matches):raise ValueError('Mismatched download receipt')
                doc=matches[0][1] if len(matches)==1 else None
            stamp=clean(td[4].text_content()).replace('.','').replace('-','')
            if not re.fullmatch(r'\d{8}',stamp) or not start<=stamp<=end:raise ValueError('Displayed DART date outside call window')
            out.append(dict(receipt=rc,corp_code=corp,name=company,submitter=clean(td[3].text_content()),title=clean(rel.text_content()),
                            filing_date=stamp,document=doc,source_sha256=h))
        if page>=pages:break
        page+=1
    if count!=len(out) or len(set(r['receipt'] for r in out))!=count:raise ValueError('Incomplete DART result')
    save(dest,{'start':start,'end':end,'code':code,'queried_corp':cp,'queried_name':name,'hashes':hashes,'records':out,'count':count})
def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('work',type=Path);cli.add_argument('issuer_list',type=Path)
    cli.add_argument('kind_form',type=Path);cli.add_argument('mode',choices=['K','D','X'])
    args=cli.parse_args();w=args.work
    base=dict(html.fromstring(args.kind_form.read_bytes().decode()).xpath('//form[@id="searchForm"]')[0].form_values())
    issuers=[(r['stock_code'],r['corp_code'],r['name']) for r in rows(args.issuer_list)]
    if args.mode=='K':
        jobs=[]
        for year in (2016,2017,2018,2019,2020,2021,2015):
            for st,en in (('01-01','03-31'),('04-01','06-30'),('07-01','09-30'),('10-01','12-31')):
                if year==2015 and st<'07-01':continue
                if year==2021 and st=='10-01':en='12-01'
                jobs.append((f'{year}-{st}',f'{year}-{en}'))
        def task(j):kind_period(w,base,*j)
    else:
        jobs=[(issuer,r) for issuer in issuers for r in (('ALL',) if args.mode=='D' else ('11013','11012','11011'))]
        def task(j):d_query(w,j[0],args.mode,j[1])
    def run(j):
        try:task(j)
        except Exception as e:print('FAIL',j,type(e).__name__,str(e)[:100],flush=True)
    with ThreadPoolExecutor(2,thread_name_prefix=args.mode) as pool:list(pool.map(run,jobs))
if __name__=='__main__':main()
