"""Isolated accounting-only E1 sensitivities supported by dated issuer evidence."""
import argparse
import json
from pathlib import Path

from candidate_features import Policy, build_features
from candidate_study import CUT, open_db, summarize_one
from full_replay import calendar, load_config, replay
from decimal import Decimal as D

EXTRA = {
    'B': (
        ('20170511',('stage41-shinpoong','KR7002870004','split','V1_ACCOUNT_TERMS',None,
                     {'verified':{'ratio_numerator':10,'ratio_denominator':1}},'20170216')),
        ('20180509',('stage41-fila','KR7081660003','split','V1_ACCOUNT_TERMS',None,
                     {'verified':{'ratio_numerator':5,'ratio_denominator':1}},'20180308')),
    ),
    'C': (
        ('20210208',('stage41-cs-wind','KR7112610001','bonus',
                     'TERMS_CONFIRMED_SETTLEMENT_UNVERIFIED',None,
                     {'ratio':'1','planned_delivery':'20210305'},'20201120')),
    ),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('database','market','benchmark','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--reuse-run-tapes',action='store_true')
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    market = {r[0]:r[4] for r in json.loads(a.market.read_text())[1:] if r[0]<=CUT}
    benchmark = [r for r in json.loads(a.benchmark.read_text())['gross']['daily'] if r['day']<=CUT]
    with open_db(a.database) as db:
        features = None if a.reuse_run_tapes else build_features(db,calendar(db),market,CUT,('B','C'))
        result = {}
        for name in ('B','C'):
            tape = a.output/f'{name}.json'
            if features is None:
                run = json.loads(tape.read_text())
            else:
                run = replay(db,market,D('.01'),load_config(),mode='exploratory',
                             policy=Policy(name,features),end=CUT,additional_actions=EXTRA[name])
                tape.write_text(json.dumps(run,default=str))
            result[name] = summarize_one(run,benchmark)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2,default=str))


if __name__=='__main__':
    main()
