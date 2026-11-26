"""Archive and verify the FSS main-document family for the fixed sample's pre-calendar comparators."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from lxml import html
from identity_ledger import read, save

URL='https://dart.fss.or.kr/dsaf001/main.do?rcpNo='
TITLES={'11011':'사업보고서','11012':'반기보고서','11013':'분기보고서'}
menu_pattern=r'rcpNo=(\d{14})'


def parsed_menu(body):
    dom=html.fromstring(body.decode())
    corps={m[1] for onclick in dom.xpath('//span[contains(@onclick,"openCorpInfoNew")]/@onclick') if (m:=re.search(r"openCorpInfoNew\('(\d{8})'",onclick))}
    family=[]
    for option in dom.xpath('//select[@id="family"]/option'):
        match=re.fullmatch(menu_pattern,option.get('value',''))
        if not match:continue
        label=' '.join(option.text_content().split())
        date=re.match(r'^(\d{4})[.](\d{2})[.](\d{2})\s+(.+)$',label)
        if not date:continue
        family.append(dict(receipt=match[1],date=''.join(date.groups()[:3]),title=date[4],selected=option.get('selected') is not None))
    return corps,family


def get_jobs(ledger,priority):
    originals=defaultdict(list)
    def key(row):return row['isin'],row['corp_code'],row['period_end'],row['report_type']
    def cross(row):
        return row['comparator_identity_status']=='PASS' and all(row.get(k) for k in ('receipt','kind_receipt','source_dart_sha256','source_kind_sha256','source_kind_export_sha256'))
    for r in ledger:
        if r['version']=='original' and cross(r):originals[key(r)].append(r)
    candidates=[]
    for r in ledger:
        if r['period_end'] not in ('20150930','20151231') or r['filing_date']>'20171201' or r['version']!='amendment' or not cross(r):continue
        orig=originals[key(r)]
        if len(orig)==1 and r['dart_title'].startswith('[기재정정]') and '[정정]' in r['kind_title']:
            candidates.append((r,orig[0]))
    return sorted(candidates,key=lambda pair:(pair[0]['receipt'] not in priority,pair[0]['receipt']))


def capture(work,db,jobs):
    paths={row['receipt']:work/'raw'/('fss-comparator-'+row['receipt']+'-menu.html') for pair in jobs for row in pair}
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as store:
        for rid,file in paths.items():
            if file.exists():continue
            src=store.execute('select sha,body from pointers where url=?',(URL+rid,)).fetchone()
            if src:
                digest,body=src
                assert sha256(body).hexdigest()==digest
                if b'openCorpInfoNew' in body and parsed_menu(body)[1]:file.write_bytes(body)


def prove(work,amend,orig):
    out={'receipt':amend['receipt'],'candidate_parent':orig['receipt'],'corp_code':amend['corp_code'],'isin':amend['isin'],'period_end':amend['period_end'],
         'form':amend['report_type'],'amendment_date':amend['filing_date'],'original_date':orig['filing_date'],'status':'BLOCKED',
         'reason':'no_verified_dual_menu','amendment_menu_sha256':'','original_menu_sha256':'','amendment_kind_receipt':amend['kind_receipt'],
         'original_kind_receipt':orig['kind_receipt'],'amendment_kind_page':amend['source_kind_sha256'],'amendment_kind_export':amend['source_kind_export_sha256'],
         'amendment_dart_index':amend['source_dart_sha256'],'original_kind_page':orig['source_kind_sha256'],'original_kind_export':orig['source_kind_export_sha256'],
         'original_dart_index':orig['source_dart_sha256']}
    for label,row in [('amendment',amend),('original',orig)]:
        p=work/'raw'/('fss-comparator-'+row['receipt']+'-menu.html')
        if not p.is_file():return out
        body=p.read_bytes();out[label+'_menu_sha256']=sha256(body).hexdigest();corps,family=parsed_menu(body)
        selected=[v for v in family if v['selected']]
        if corps!={amend['corp_code']} or len(selected)!=1 or selected[0]['receipt']!=row['receipt']:return out
        anchor=[v for v in family if v['receipt']==orig['receipt'] and v['date']==orig['dart_published'] and v['title']==TITLES[amend['report_type']]]
        revised=[v for v in family if v['receipt']==amend['receipt'] and v['date']==amend['dart_published'] and v['title']=='[정정] '+TITLES[amend['report_type']]]
        if len(anchor)!=1 or len(revised)!=1:return out
        if orig['filing_date']>amend['filing_date']:return out
        if orig['filing_date']==amend['filing_date'] and not (orig.get('ordering_timestamp') and amend.get('ordering_timestamp') and orig['ordering_timestamp']<amend['ordering_timestamp']):return out
    out.update(status='PASS',reason='receipt_bound_original_and_amended_FSS_main_family_both_dated_KIND_FSS_indexes')
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work',type=Path);parser.add_argument('receipt_db',type=Path);parser.add_argument('priority',type=Path)
    a=parser.parse_args()
    priority={r['receipt'] for r in read(a.priority)};jobs=get_jobs(read(a.work/'receipts.csv'),priority)
    capture(a.work,a.receipt_db,jobs)
    output=[prove(a.work,amend,orig) for amend,orig in jobs]
    if output:save(a.work/'comparator_chains.csv',output,output[0])
    print(len(priority),len(jobs),Counter(v['status'] for v in output),len(list((a.work/'raw').glob('fss-comparator-*-menu.html'))))
if __name__=='__main__':main()
