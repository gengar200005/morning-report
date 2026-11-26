"""Validate non-quarterly originals found for unmatched March-2021 issuers.

Use the raw, ordered KIND exports and matching regulatory index pages in the
identity evidence package. Values are independently read from labeled cells
of the preserved original. Annual figures never enter calendar-quarter pairs.
"""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path
from lxml import html

from stage82b.identity import clean, issuer_key, official_securities, read_rows

SCOPE = {"0501": "사업보고서", "0502": "반기보고서"}
SUBSET = {"001720","002630","003610","004310","005190","008110","008870","018500","092440"}
AUDIT = {"008870","003610","092440"}


def raw_sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect_original(folder, row):
    rid = row["kind_receipt"]
    meta = json.loads((folder/f"{rid}.json").read_text())
    body = (folder/f"{rid}.htm").read_bytes()
    index = (folder/f"{rid}.index.html").read_bytes()
    pointer = (folder/f"{rid}.pointer.html").read_bytes()
    viewer = html.fromstring(index.decode())
    options = [o for o in viewer.xpath('//select[@id="mainDoc"]/option[@value!=""]')]
    wanted = [o for o in options if o.get('value').split('|')[0]==meta["doc"]]
    if len(wanted)!=1 or "[정정]" in wanted[0].text_content() or row['filing_date'].replace('-','.') not in wanted[0].text_content():
        raise ValueError("not the original displayed version")
    if meta['sha256']!=raw_sha(body) or meta['body'].encode() not in pointer or meta['stock_code']!=row['stock_code']:
        raise ValueError("unexpected original receipt source")
    tree = html.fromstring(body.decode())
    heads = [(node.get("id"),clean(node.getnext().text_content()))
             for node in tree.xpath('//*[starts-with(@id,"toc_")]') if node.getnext() is not None]
    first, = [k for k,label in heads if re.fullmatch(r"2\.\s*연결재무제표",label)]
    last, = [k for k,label in heads if re.fullmatch(r"3\.\s*연결재무제표\s*주석",label)]
    source = body.decode()
    section = html.fromstring(source[source.index(f'id="{first}"'):source.index(f'id="{last}"')])
    tables = [[[clean(c.text_content()) for c in line.xpath('td|th')] for line in tbl.xpath('.//tr')]
              for tbl in section.xpath('//table')]
    i, = [ix for ix,tab in enumerate(tables) if tab and tab[0]==["연결 포괄손익계산서"]]
    labels = tables[i]
    data = tables[i+1]
    if ["(단위 : 원)"] not in labels:
        raise ValueError("unexpected monetary unit")
    result = {"source":meta,"index_sha256":raw_sha(index),"pointer_sha256":raw_sha(pointer),
              "original_document_menu":[clean(o.text_content()) for o in options],
              "table_section_ids":[first,last],"statement_header":labels,"columns":data[:2],
              "quarter_only_status":"BLOCKED","scope":"CFS","currency":"KRW","scale":1}
    if row['document_type']=="사업보고서":
        if data[0][1:]!=['제 33 기','제 32 기','제 31 기'] or any('3개월' in c for line in data for c in line[:4]):
            raise ValueError("unexpected annual table structure")
        result["reason"]="annual_only_no_quarter_column"
        return result
    if data[1]!=["3개월","누적","3개월","누적"]:
        raise ValueError("calendar-quarter columns not explicit")
    periods = [[d.replace(".","-") for d in re.findall(r"\d{4}\.\d{2}\.\d{2}",line[0])] for line in labels]
    if ["2020-10-01","2021-03-31"] not in periods or ["2019-10-01","2020-03-31"] not in periods:
        raise ValueError("wrong half-year periods for Jan-March calendar-quarter columns")
    for key,category in (("revenue",("매출액","수익(매출액)")),("operating_profit",("영업이익(손실)",))):
        matches=[line for line in data if line and re.sub(r'^[Ⅰ-Ⅻ]+\.','',line[0]) in category]
        if len(matches)!=1 or len(matches[0])!=5:
            raise ValueError("non-unique or invalid labeled statement row")
        cell=matches[0]
        result[key]={"current":int(cell[1].replace(",","")),"prior":int(cell[3].replace(",","")),
                     "label":cell[0],"original_display":cell[1:]}
    result.update(quarter_only_status="PASS",calendar_periods=[["2021-01-01","2021-03-31"],["2020-01-01","2020-03-31"]])
    return result


def verify(cache,archive_dir,universe):
    sec={r["stock_code"]:r for r in universe}
    dates={}
    for m in ('03','04','05','06'):
        p=archive_dir/f'KRX_PIT_2021_{m}_v1.json.gz'
        for session in json.loads(gzip.decompress(p.read_bytes()))['records']:
            if session['basic']:
                dates[session['date']]={r['ISU_SRT_CD']:r['ISU_CD'] for r in session['basic'] if
                    (r['MKT_TP_NM'],r['SECUGRP_NM'],r['KIND_STKCERT_TP_NM'])==('KOSPI','주권','보통주')}
    out=[]; source_hashes={}
    for typ,kname in SCOPE.items():
        a = cache/f"other{typ}.html"; b=cache/f"other-index-{typ}.html"
        x=html.fromstring(a.read_bytes().decode("cp949"))
        w=html.fromstring(b.read_bytes().decode())
        fss=json.loads((cache/f"alt-dart-{typ}.json").read_text())
        source_hashes[kname]={"kind_export":raw_sha(a.read_bytes()),"kind_screen":raw_sha(b.read_bytes()),
                              "opendart_index_query":fss["query"],"opendart_pages":fss["page_sha256"]}
        xr=x.xpath("//tr")[1:];wr=w.xpath("//tbody/tr[td]")
        total=int(w.xpath('string(//div[contains(@class,"info")]/em)'))
        if total!=len(xr) or total!=len(wr) or len(fss['rows'])!=fss['total'] or len({r['receipt'] for r in fss['rows']})!=fss['total']:
            raise ValueError("incomplete filing window")
        indexed=[]
        for xx,ww in zip(xr,wr,strict=True):
            cols=[clean(t.text_content()) for t in xx.xpath('td')]
            wc=ww.xpath("td");link=wc[3].xpath('.//a')[0]
            number,ts,name,code,title,submitter=cols
            if [number,ts,name,submitter]!=[clean(wc[0].text_content()),clean(wc[1].text_content()),clean(wc[2].xpath('.//a')[0].text_content()),clean(wc[4].text_content())]:
                raise ValueError("mismatched export row")
            if code not in SUBSET or "(2021.03)" not in title:continue
            if clean(link.text_content()).replace(" ","")!=title.replace("[정]","").replace(" ",""):
                raise ValueError("title mismatch")
            rid=re.search(r"'(\d{14})'",link.get("onclick"))[1]
            indexed.append(dict(code=code,name=name,submitter=submitter,stamp=ts,title=title,kind=rid))
        orig=[r for r in indexed if "[정정]" not in r['title']]
        for k in orig:
            day=k['stamp'][:10]
            names={issuer_key(k["name"]),issuer_key(k["submitter"])}
            cand=[r for r in fss["rows"] if r["received"].replace(".","-")==day and
                  r["title"]==kname+" (2021.03)" and issuer_key(r["company"]) in names]
            historic=sec[k["code"]]
            if dates['20210331'].get(k["code"])!=historic["isin"] or dates[day.replace("-","")].get(k["code"])!=historic['isin']:
                raise ValueError("historical stock-code/ISIN mismatch")
            competing=[v for v in orig if v['stamp'][:10]==day and {issuer_key(v['name']),issuer_key(v['submitter'])}&names]
            certified = len(cand)==len(competing)==1
            next_day=min(d for d in dates if d>day.replace("-",""))
            record={**historic, "filing_date":day,"first_available_session":next_day,"kind_receipt":k['kind'],
                    "kind_filed_title":k['title'],"document_type":kname,"identity":"PASS" if certified else "KIND_ONLY",
                    "krx_as_of_dates":["20210331",day.replace("-","")],"dart":cand[0] if certified else None,
                    "kind_corrections_to_20210630":[x['kind'] for x in indexed if x["code"]==k["code"] and "[정정]" in x['title']],
                    "opendart_xbrl_corrections_to_20210630":([r["receipt"] for r in fss["rows"] if r["corp_code"]==cand[0]["corp_code"] and '정정' in r['title'] and '(2021.03)' in r['title']] if certified else None)}
            if k["code"] in AUDIT:record["statement"]=inspect_original(cache/"nondec",record)
            out.append(record)
    return {"window":["2021-04-01","2021-06-30"],"source_sha256":source_hashes,"rows":out,
            "dongsung_krx_last_observation_through_20210630":max(d for d in dates if dates[d].get("005190")==sec["005190"]["isin"]),
            "no_imputed_quarter_values":True}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for x in ('cache','archive_dir','universe','output'):parser.add_argument(x,type=Path)
    args=parser.parse_args()
    data=verify(args.cache,args.archive_dir,read_rows(args.universe))
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print('cross-index:',Counter(x['identity'] for x in data['rows']),
          'quarterly pairs:',[r['stock_code'] for r in data['rows'] if r.get('statement',{}).get('quarter_only_status')=='PASS'])
