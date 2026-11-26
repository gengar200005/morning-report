"""Rebuild the return-free ledger from locally held packages and cross-check reporting hashes."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage9_panel.coverage_limits import run as check_limits
from stage9_panel.pit_cost import estimate
from stage9_panel.pit_facts import index_facts
from stage9_panel.pit_ledger import build


def inventory(path):
    digest=sha256()
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        for query in ('SELECT receipt,kind,document,corp,source,sha256 FROM packages ORDER BY receipt,kind',
                      'SELECT receipt,kind,reason FROM quarantine ORDER BY receipt,kind'):
            for row in db.execute(query):
                digest.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode()+b'\n')
    return digest.hexdigest()


def refresh(root,sessions,output,final=False):
    output.mkdir(parents=True,exist_ok=True)
    roster=root/'limited_issuer_months.csv'
    context=root/'context.csv'
    receipts=root/'identity/receipts.csv'
    coverage=root/'identity/monthly_coverage.csv'
    packages=root/'raw/receipts.sqlite'
    facts=root/'ledger/facts.sqlite'
    source_before=inventory(packages)
    indexed=index_facts(packages,receipts,facts)
    basis=root/'ledger/q4_basis.json'
    result=build(roster,context,receipts,coverage,sessions,facts,output,basis if basis.is_file() else None,packages)
    limits=check_limits(roster,context,output/'issuer_months.csv',output/'quality.json',facts,
                        output/'coverage_limits.json',identity=root/'identity',packages=packages)
    cost=estimate(root,sessions,'2017',output/'issuer_months.csv')
    (output/'2017_cost.json').write_text(json.dumps(cost,ensure_ascii=False,indent=2)+'\n')
    source_after=inventory(packages)
    if (limits['ledger_sha256']!=result['ledger_sha256'] or limits['context_sha256']!=result['context_sha256']
            or limits['metadata_sha256']!=result['metadata_sha256'] or limits['coverage_sha256']!=result['coverage_sha256']):
        raise ValueError('Ledger and coverage views have different input hashes')
    stable=(source_before==source_after and all(sha256(p.read_bytes()).hexdigest()==result[k] for p,k in
            [(receipts,'metadata_sha256'),(coverage,'coverage_sha256'),(context,'context_sha256')]))
    if final and not stable:
        raise ValueError('Input inventory changed during the final rebuild. Rerun after collection is frozen.')
    proof=dict(stable_during_rebuild=stable,final_requested=final,source_inventory_sha256=source_after,
        source_inventory_before_sha256=source_before,fact_snapshot_sha256=result['fact_snapshot_sha256'],
        metadata_sha256=result['metadata_sha256'],coverage_sha256=result['coverage_sha256'],
        context_sha256=result['context_sha256'],roster_sha256=result['roster_sha256'],indexed=indexed,
        outputs={f:sha256((output/f).read_bytes()).hexdigest() for f in
                 ('issuer_months.csv','quality.json','coverage_limits.json','2017_cost.json')})
    (output/'pit_snapshot.json').write_text(json.dumps(proof,indent=2)+'\n')
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('root','sessions','output'):
        parser.add_argument(key,type=Path)
    parser.add_argument('--final',action='store_true')
    print(json.dumps(refresh(**vars(parser.parse_args()))))
