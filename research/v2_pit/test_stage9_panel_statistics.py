from datetime import date,timedelta
import unittest

import numpy as np

from stage9_panel.statistics_panel import (
    assignments, block_counts, bootstrap_summary, calendar_spec, contrast_arrays,
    run_statistics, sample_means,
)


def validation_calendar():
    rows=[]
    for year in (2022,2023):
        for month in range(1,13):
            d=date(year,month,2)
            end=d+timedelta(days=177)
            rows.append(dict(formation=d.strftime('%Y%m%d'),entry=(d+timedelta(days=1)).strftime('%Y%m%d'),
                             exits={'120':end.strftime('%Y%m%d') if end.year<=2023 else None}))
    return rows


def records(days,n=12):
    for day in days:
        for j in range(2*n):
            yield dict(formation=day,isin=f'I{j:03d}',corp_code=f'{j:08d}',signal='F2',contrast='top-remainder',
                       side='target' if j<n else 'comparison',price=.09 if j<n else -.01)


class StatisticsPanelTest(unittest.TestCase):
    def test_month_cluster_family_and_determinism(self):
        cal=validation_calendar()
        days=[r['formation'] for r in cal if r['exits']['120']]
        rows=list(records(days))
        def run(r):
            return run_statistics(r,cal,'validation')['contrasts']
        stats=run(rows)
        target=stats[0]
        self.assertEqual(len(stats),6)
        self.assertEqual(target['valid_months'],len(days))
        self.assertEqual(target['status'],'tested')
        self.assertAlmostEqual(target['effect'],.10)
        self.assertEqual(target['issuers_observed_in_included_months'],24)
        for setting in target['bootstrap'].values():
            self.assertGreaterEqual(setting['valid_draws'],4500)
            np.testing.assert_allclose(setting['ci95'],[.10,.10],rtol=0,atol=1e-14)
            self.assertAlmostEqual(setting['p'],1/(setting['valid_draws']+1))
        self.assertAlmostEqual(target['holm_p'],6*target['p'])
        self.assertEqual(stats,run(reversed(rows)))
        self.assertTrue(all(r['p']==r['holm_p']==1 for r in stats[1:]))

    def test_one_issuer_is_sampled_once_per_full_history(self):
        cal=validation_calendar()
        days=[r['formation'] for r in cal if r['exits']['120']]
        rows=list(records(days,n=7))
        for r in rows:
            if r['side']=='target' and r['isin']!='I000':
                r['price']=''
        row=run_statistics(rows,cal,'validation')['contrasts'][0]
        self.assertEqual(row['status'],'insufficient_valid_replicates')
        self.assertEqual(row['p'],1)
        boot=row['bootstrap']['issuer_and_6_month']
        # P(unique target seen) = 1-(13/14)^14 across all selected months jointly.
        self.assertTrue(2900<boot['valid_draws']<3600)
        self.assertIsNone(boot['ci95'])
        self.assertEqual(row['bootstrap']['6_month_only']['valid_draws'],5000)

    def test_isin_replacement_keeps_same_issuer_multiplier(self):
        cal=validation_calendar()
        days=[r['formation'] for r in cal if r['exits']['120']]
        rows=list(records(days,n=8))
        baseline=run_statistics(rows,cal,'validation')
        for r in rows:
            if r['isin']=='I000' and r['formation']>=days[6]:
                r['isin']='NEW_ORDINARY_ISIN'
        changed=run_statistics(rows,cal,'validation')
        self.assertEqual(baseline['contrasts'],changed['contrasts'])
        self.assertEqual(changed['unique_assigned_issuers'],16)
        self.assertEqual(changed['unique_assigned_isins'],17)

    def test_joint_requires_A_B_C_five_assigned(self):
        day='20220102'
        rows=[]
        for contrast,other,count in [('C-A','A',5),('C-B','B',4)]:
            for label,side,n in [('C','target',5),(other,'comparison',count)]:
                for i in range(n):
                    rows.append(dict(formation=day,isin=label+str(i),corp_code=f'{100*ord(label)+i:08d}',signal='F3',contrast=contrast,side=side,price=.01))
        groups,price,issuers=assignments(rows,{day})
        for c in ('C-A','C-B'):
            _,_,valid,monthly=contrast_arrays('F3',c,[day],{day},sorted(set(issuers.values())),groups,price,issuers)
            self.assertFalse(valid[0])
            self.assertEqual(monthly[0]['status'],'insufficient_preformed_group')
        rows[-1].update(isin='A1',corp_code=f'{100*ord("A")+1:08d}')
        g,y,issuer_ids=assignments(rows,{day})
        with self.assertRaisesRegex(ValueError,'overlapping'):
            contrast_arrays('F3','C-A',[day],{day},sorted(set(issuer_ids.values())),g,y,issuer_ids)

    def test_full_month_axis_and_empty_side_bootstrap(self):
        cal=validation_calendar()
        with self.assertRaisesRegex(ValueError,'entire ordered'):
            calendar_spec(cal[:1]+cal[2:],'validation')
        days,usable=calendar_spec(cal,'validation')
        with self.assertRaisesRegex(ValueError,'censored'):
            assignments(records([days[-1]]),usable)
        draws=block_counts(24,6,np.random.default_rng(5))
        self.assertTrue(np.all(draws.sum(axis=1)==24))
        m=np.array([[.1,np.nan,.2],[.1,np.nan,.2]])
        w=np.array([[1,1,0],[1,0,1]])
        result=sample_means(m,w)
        self.assertTrue(np.isnan(result[0]))
        self.assertAlmostEqual(result[1],.15)
        s=bootstrap_summary(np.concatenate([np.zeros(4500),np.full(500,np.nan)]),0)
        self.assertEqual((s['valid_draws'],s['p'],s['ci95']),(4500,1.,[0.,0.]))

    def test_duplicate_conflicting_and_missing_returns(self):
        day='20220102'; rows=list(records([day],5))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            assignments([*rows,rows[0]],{day})
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            assignments([*rows,{**rows[0],'signal':'F3','price':.8}],{day})
        with self.assertRaisesRegex(ValueError,'status'):
            assignments([{**rows[0],'status':'entry_unavailable'}],{day})
        # Group size is fixed before outcomes; one observed per side is descriptive.
        for i,r in enumerate(rows):
            if i not in (0,5):r['price']=''
        groups,price,issuers=assignments(rows,{day})
        _,_,v,m=contrast_arrays('F2','top-remainder',[day],{day},sorted(set(issuers.values())),groups,price,issuers)
        self.assertTrue(v[0])
        self.assertEqual(m[0]['assigned'],[5,5])
        self.assertEqual(m[0]['observed'],[1,1])
        self.assertAlmostEqual(m[0]['effect'],.1)


if __name__=='__main__':
    unittest.main()
