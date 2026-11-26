import csv
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from limited_panel import allow_membership
from single_formation import audit_replayed_outcomes, cells, digest, gate_signals, groups, matched, rank_ic, read_ledger, stress, summaries, top


class SingleFormationTest(unittest.TestCase):
    def test_gate_requires_all_gates_and_exact_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'ledger';file.write_text('fixture')
            gate=dict(formation='20210601',q1_quality_pass=True,asof_complete=True,
                      quarter_forms_checked=True,passed_signals=['F3'],asof_sha256=digest(file))
            self.assertEqual(gate_signals(gate,file),['F3'])
            for field in ('q1_quality_pass','asof_complete','quarter_forms_checked'):
                with self.assertRaises(ValueError):gate_signals(dict(gate,**{field:False}),file)
            with self.assertRaises(ValueError):gate_signals(dict(gate,passed_signals=['F1']),file)
            file.write_text('changed')
            with self.assertRaises(ValueError):gate_signals(gate,file)

    def test_ledger_includes_new_members_and_excludes_future(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.csv'
            fields=['isin','industry_group','sector_code','receipt','published_date','available_session','F2','F3','status','source_sha256']
            with p.open('w',newline='') as f:
                w=csv.writer(f);w.writerow(fields)
                w.writerow(['old','nonfinancial','G45','20210517001140','20210517','20210518','2.4','.1','PASS','c'*64])
                w.writerow(['new','unknown','','','','','','','no_asof_filing',''])
            members={'old':'1','new':'2'}
            sessions=['20210514','20210517','20210518','20210520','20210601']
            _,vals=read_ledger(p,members,['F2','F3'],sessions)
            self.assertEqual(vals['F3'],{'old':Decimal('.1')})
            with self.assertRaises(ValueError):read_ledger(p,{'old':'1'},['F3'],sessions)
            p.write_text(p.read_text().replace('20210518','20210602'))
            with self.assertRaises(ValueError):read_ledger(p,members,['F3'],sessions)

    def test_ranks_intersection_and_empty_groups(self):
        s={str(i):Decimal(i) for i in range(15)}
        m4={str(i):-i for i in range(12)}
        g=groups(s,m4)
        self.assertEqual(g['top'],{'12','13','14'})
        self.assertEqual(g['A'],{'0','1'})
        self.assertEqual(g['B'],{'10','11'})
        self.assertEqual(g['C'],set())
        self.assertEqual(top({k:1 for k in 'edcba'}),{'a'})

    def test_matching_and_stress_do_not_impute_failed_entry(self):
        r={'a':(.14,.15,'observed',0),'b':(None,None,'entry_unavailable',0),
           'c':(None,None,'unverified_reference',0),'d':(.08,.1,'observed',0)}
        self.assertAlmostEqual(stress(set('abc'),r,0,-.2),-.03)
        self.assertIsNone(stress({'b'},r,0,-.2))
        m=matched(set('ac'),{'d'},{k:v[0] for k,v in r.items()},{'a':1,'c':1,'d':1})
        self.assertAlmostEqual(m['effect'],.06)
        self.assertEqual(m['structurally_matched_target'],2)
        self.assertEqual(cells(set(),{}),{})

    def test_descriptive_statistics_and_quintiles(self):
        s={str(i):i for i in range(10)}
        info={k:(v/100,v/100,'observed',0) for k,v in s.items()}
        benchmark=('20210602','20210629',.03,.04)
        out=summaries(groups(s,s),{20:(info,benchmark)}, {}, {k:'G45' for k in s},s)[20]
        self.assertAlmostEqual(out['diagnostics']['price']['spearman_ic'],1)
        self.assertAlmostEqual(out['groups']['top']['price']['median'],.085)
        self.assertEqual([x['n'] for x in out['diagnostics']['price']['quintiles_high_to_low']],[2]*5)
        self.assertIsNone(out['contrasts']['C-A']['price']['difference'])


    def test_replay_cross_check_compares_missingness_returns_status_and_dividend_count(self):
        windows={20:(1,20)}
        outcomes={'x':{20:(-.1,-.09,'observed',1)},'new':{20:(None,None,'entry_unavailable',0)}}
        correct={('x',20):(-.1,-.09,'observed',1)}
        self.assertEqual(audit_replayed_outcomes(outcomes,windows,{'x'},correct),1)
        for bad in ((-.09,-.09,'observed',1),(-.1,None,'observed',1),(-.1,-.09,'other',1),(-.1,-.09,'observed',0)):
            with self.assertRaises(ValueError):
                audit_replayed_outcomes(outcomes,windows,{'x'},{('x',20):bad})

    def test_sampling_sql_authorizer(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript('CREATE TABLE sessions(day text);CREATE TABLE ohlcv(close real);')
            db.set_authorizer(allow_membership)
            self.assertEqual(db.execute('SELECT day FROM sessions').fetchall(),[])
            with self.assertRaises(sqlite3.DatabaseError):db.execute('SELECT close FROM ohlcv')
