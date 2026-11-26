"""Join the fixed quarter-end KRX universe to originals without dropping unlinked securities.
Directory linkage is an identifier candidate, not proof of historic identity for corporate actions.
The search window is bounded. Later amendments and earlier non-periodic disclosures are outside scope.
"""
import csv
import sys
import json
from collections import Counter,defaultdict
from pathlib import Path
root=Path(sys.argv[2])
read=lambda p:list(csv.DictReader(p.open(encoding='utf-8')))
universe=read(Path(sys.argv[1]))
receipts=read(root/'all_202103_receipts.csv')
current=read(root/'current_directory_P.csv')
by_corp=defaultdict(list)
by_name=defaultdict(set)
directory=defaultdict(list)
for company in current:
    if company['stock_code']:directory[company['stock_code']].append(company)
for report in receipts:
    if report['type']=='original':
        by_corp[report['corp_code']].append(report)
        by_name[report['dart_display_name']].add(report['corp_code'])
p_filtered={r['receipt'] for r in read(root/'P_202103_receipts.csv')}
result=[]
for sec in universe:
    tick=sec['stock_code'];candidates=directory.get(tick,[]);names=by_name.get(sec['issuer_as_of'],set())
    corp='';status='unmatched'
    if len(candidates)==1 and candidates[0]['corp_code'] in by_corp:
        corp=candidates[0]['corp_code']
        if not names:status='directory_code_only'
        elif names=={corp}:status='directory_code_and_exact_name'
        else:corp='';status='conflicting_code_and_name'
    elif len(names)==1 and not candidates:corp=next(iter(names));status='exact_name_only'
    elif len(names)>1 or len(candidates)>1:status='ambiguous'
    elif candidates:status='code_linked_no_matching_original'
    originals=by_corp.get(corp,[])
    if len(originals)!=1 and corp:status='no_unique_original'
    r=originals[0] if len(originals)==1 else {}
    result.append({**sec,'directory_method':status,'circumstance':'provisional' if r else 'unresolved','corp_code_candidate':corp,'receipt_candidate':r.get('receipt',''),'dart_name':r.get('dart_display_name',''),'filing_date':r.get('filed',''),'absent_in_DART_P_filter':str(r['receipt'] not in p_filtered) if r else ''})
counts=Counter(r['corp_code_candidate'] for r in result if r['corp_code_candidate'])
for r in result:
    if counts[r['corp_code_candidate']]>1:
        r['circumstance']='issuer_collision'
with (root/'candidate_universe.csv').open('w',newline='',encoding='utf8') as out:
    w=csv.DictWriter(out,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
summary=dict(denominator=len(result),classification=dict(Counter(r['directory_method'] for r in result)),usable_candidates=sum(r['circumstance']=='provisional' for r in result),missing_in_market_filter=sum(r['absent_in_DART_P_filter']=='True' for r in result),collisions=sum(r['circumstance']=='issuer_collision' for r in result))
(root/'candidate_summary.json').write_text(json.dumps(summary,indent=2));print(summary)
