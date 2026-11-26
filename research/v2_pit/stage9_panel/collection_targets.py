"""Choose original documents used at historical formation dates, including annual supports."""
from datetime import date
import sqlite3
from stage9_panel.pit_ledger import filing_versions, normalize, prev_end

def target_receipts(manifest,panel,sessions_db,monthly_coverage,context,draw,audit):
    groups={(r['formation'],r['isin']):r['industry_group'] for r in context}
    complete={(r['formation'],r['isin']) for r in monthly_coverage if r['complete']=='1'}
    history=normalize(manifest)
    with sqlite3.connect(sessions_db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        sessions=[r[0] for r in db.execute('SELECT day FROM sessions ORDER BY day')]
    targets=set()
    required={(r['isin'],date.fromisoformat(r['period_end']).strftime('%Y%m%d')) for r in draw+audit}
    extra=set()
    for isin,rows in history.items():
        for row in rows:
            if (isin,row['period_end']) in required and row['identity_status']=='PASS':
                extra.add(row['receipt'])
                if row['report_type']=='11011':
                    for n in (3,12,15):
                        required.add((isin,prev_end(row['period_end'],n)))
        extra.update(r['receipt'] for r in rows if (isin,r['period_end']) in required and r['identity_status']=='PASS')
    for m in panel:
        isin,day=m['historical_isin'],m['formation']
        if (day,isin) not in complete or groups.get((day,isin))=='financial':
            continue
        rows=history[isin]
        primary,status=filing_versions(rows,day,sessions=sessions)
        if status!='PASS' or not 0<=(date.fromisoformat(day)-date.fromisoformat(primary['period_end'])).days<=180:
            continue
        chosen=[primary]
        if primary['report_type']=='11011':
            for n in (3,12,15):
                component,st=filing_versions(rows,day,prev_end(primary['period_end'],n),sessions=sessions,reference_only=n>=12)
                if st=='PASS':chosen.append(component)
        for row in chosen:
            targets.add(row['receipt'])
            if row['original_receipt']:targets.add(row['original_receipt'])
    return targets|extra
