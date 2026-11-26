"""Read the public regulator XBRL index for 2021-04-01 to 2021-06-30.

Usage: python public_xbrl_index.py PAGE_CACHE OUTPUT_JSON
Requires lxml. Reads all markets; the returned list is not the historical universe.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from lxml import html

ROOT = 'https://opendart.fss.or.kr/disclosureinfo/fnltt/xbrl/'
FILTERS = {'textCrpCik':'', 'textCrpNm':'', 'startDate':'2021-04-01',
           'endDate':'2021-06-30', 'rptType':'11013', 'recordCountPerPage':100,
           'sortStdr':'date', 'sortOrdr':'desc'}


def parse_page(raw, page):
    h = html.fromstring(raw.decode('utf-8'))
    paging = h.xpath('string(//div[@class="page_info"])').strip()
    m = re.fullmatch(r'\[(\d+)/(\d+)\]\s*\[총 ([\d,]+)건\]', paging)
    if m is None or int(m[1]) != page:
        raise ValueError('Missing page or incorrect page index')
    pages, total = int(m[2]), int(m[3].replace(',',''))
    rows = []
    for tr in h.xpath('//tbody/tr'):
        issuer = tr.xpath('.//span[contains(@onclick,"openCorpInfo")]/@onclick')
        if not issuer:
            continue
        receipt = re.search(r"openReportViewer\('(\d{14})'\)",tr.xpath('.//a/@onclick')[0])[1]
        corp = re.search(r"openCorpInfo\('(\d{8})'\)", issuer[0])[1]
        buttons = tr.xpath('.//button/@onclick')
        target = re.search(r'rcp_no=(\d{14})&dcm_no=(\d+)',buttons[0]) if buttons else None
        if target and target[1] != receipt:
            raise ValueError('Mismatch between filing and download link')
        cells = tr.xpath('./td')
        received = cells[4].text_content().strip()
        # After-hours filings can show a later published date than the receipt prefix.
        # Preserve the regulator's printed date for later as-of reconciliation.
        if not re.fullmatch(r'2021\.(?:04|05|06)\.\d{2}',received):
            raise ValueError('Unexpected printed filing date')
        rows.append(dict(receipt=receipt,document=target[2] if target else None,corp_code=corp,
                         company=tr.xpath('string(.//span[contains(@onclick,"openCorpInfo")])').strip(),
                         title=' '.join(cells[2].text_content().split()),received=received,
                         market=cells[1].xpath('string(.//span[1]/@alt)')))
    return pages,total,sha256(raw).hexdigest(),rows


def read_page(cache, page):
    path = cache / f'p{page}.html'
    if path.exists():
        return parse_page(path.read_bytes(),page)
    params = dict(FILTERS,pageIndex=page,pageSize=10,pageUnit=10,isMultiCheck='')
    req = Request(ROOT+'list.do',data=urlencode(params).encode(),headers={
        'Referer':ROOT+'main.do','X-Requested-With':'XMLHttpRequest','User-Agent':'Mozilla/5.0'})
    for attempt in range(3):
        try:
            with urlopen(req,timeout=30) as response:
                raw = response.read()
            parsed = parse_page(raw,page)
            break
        except (OSError,ValueError):
            if attempt == 2:
                raise
            time.sleep(1+attempt)
    with NamedTemporaryFile(dir=cache,delete=False) as f:
        f.write(raw)
        tmp = Path(f.name)
    tmp.replace(path)
    return parsed


def collect(cache):
    cache.mkdir(parents=True,exist_ok=True)
    first = read_page(cache,1)
    pages,total = first[:2]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [first,*pool.map(partial(read_page,cache),range(2,pages+1))]
    rows = [row for result in results for row in result[3]]
    if (any(r[:2]!=(pages,total) for r in results) or len(rows)!=total
            or len({r['receipt'] for r in rows})!=total):
        raise ValueError('Incomplete, changing, or duplicate public listing')
    return dict(query={'url':ROOT+'list.do','method':'POST',**FILTERS},total=total,pages=pages,
                page_sha256={str(i):r[2] for i,r in enumerate(results,1)},rows=rows)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    data = collect(args.cache)
    with NamedTemporaryFile('w',encoding='utf-8',dir=args.output.parent,delete=False) as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
        f.write('\n')
        tmp = Path(f.name)
    tmp.replace(args.output)
    print(len(data['rows']),'distinct receipts')
