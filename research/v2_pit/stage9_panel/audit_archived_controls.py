"""Reapply the new monetary fact reader to earlier immutable, independently read statements."""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import re
from pit_facts import extract_receipt

BASE=Path(__file__).resolve().parent
MAPPING={'revenue_current':'revenue_current','revenue_comparison':'revenue_prior',
         'op_current':'operating_profit_current','op_comparison':'operating_profit_prior'}


def run(raw, historical, output):
    manual=json.loads((BASE.parent/'stage82b/quarter_holdout_manual.json').read_bytes())
    packages={r['kind']:r for r in json.loads((raw/'package_manifest.json').read_bytes())}
    checks=[]
    for r in manual:
        m=re.search(r'\((\d{4})\.(\d\d)\)$',r['title'])
        year,month=map(int,m.groups())
        import calendar
        end=date(year,month,calendar.monthrange(year,month)[1]).isoformat()
        p=packages[r['kind']]
        dur={'annual':'12','nine_month':'9'}.get(r['method'],'3')
        amounts={k:r[old] for old,k in MAPPING.items()}
        fmt={'xbrl':(raw/(r['kind']+'.zip'),p['archive_sha256'])}
        if dur=='3':
            fmt['kind_html']=(raw/(r['kind']+'.htm'),r['sha256'])
        for kind,(path,h) in fmt.items():
            f=extract_receipt(p['receipt'],p['document'],p['corp'],end,kind,path.read_bytes(),h)
            values={k:f.get(dur,{}).get(k,{}).get('value') for k in amounts}
            if values!=amounts:
                raise ValueError((r['kind'],kind,dur,amounts,values))
            checks.append(dict(kind_receipt=r['kind'],source_type=kind,period_end=end,duration=int(dur),sha256=h,
                               monetary_matches=sum(x is not None for x in values.values()),missing_matches=sum(x is None for x in values.values())))
    legacy=[]
    for meta in sorted(historical.glob('????-??????.json')):
        p=json.loads(meta.read_bytes())
        end=p['filing_date'][:4]+'-03-31'
        f=extract_receipt(p['receipt'],p['document'],p['corp_code'],end,'xbrl',meta.with_suffix('.zip').read_bytes(),p['sha256'])['3']
        comparisons=[]
        for side,newside in [('current','current'),('prior_as_reported','prior')]:
            for field,expected in p['signed_fields'][side].items():
                value=f[field+'_'+newside].get('value')
                if (int(expected) if expected is not None else None)!=value:
                    raise ValueError((meta,side,field))
                comparisons.append(value is not None)
        legacy.append(dict(receipt=p['receipt'],source_sha256=p['sha256'],monetary_matches=sum(comparisons),missing_matches=comparisons.count(False)))
    result={'scope':'Earlier, known statements used only as controls for the Stage 9 reader. Not counted as new holdout successes.',
            'display_and_xbrl_checks':checks,'historical_xbrl_regression':legacy}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('raw','historical','output'):
        p.add_argument('--'+k,type=Path,required=True)
    run(**vars(p.parse_args()))
