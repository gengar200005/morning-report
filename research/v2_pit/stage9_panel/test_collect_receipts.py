import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from stage9_panel.collect_receipts import initialize, plan, reserve, store


class CollectionTest(unittest.TestCase):
    def test_evidence_formats_remain_separate_and_cap_counts_failed_initial_attempts(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'raw.sqlite'
            initialize(path)
            with sqlite3.connect(path) as db:
                jobs=[({'receipt':str(j)},'xbrl') for j in range(105)]
                first=reserve(db,jobs,'technical')
                self.assertEqual(len(first),100)
                with db:
                    db.execute("INSERT INTO completed VALUES('0','xbrl','BLOCKED','HTTP 503')")
                self.assertEqual(reserve(db,[jobs[0],jobs[-1]],'technical'),[])
                self.assertEqual(reserve(db,[jobs[0]],'technical',True),[jobs[0]])
                store(db,'1','10','co','xbrl','X',b'zip')
                store(db,'1','20','co','kind_html','K',b'html')
                self.assertEqual(db.execute("SELECT count(*) FROM packages WHERE receipt='1'").fetchone()[0],2)
                with self.assertRaises(ValueError):store(db,'1','10','co','xbrl','X',b'different')
                self.assertEqual(reserve(db,[jobs[-1]],'full'),[jobs[-1]])
    def test_full_only_asof_eligible_and_annual_support(self):
        panel=[{'formation':'20170502','historical_isin':'A'}]
        def row(rc,period,available):
            return dict(isin='A',corp_code='00111111',kind_receipt=rc,receipt=rc,document='12345',
                period_end=period,available_session=available,report_type='11011' if period.endswith('1231') else '11013',version='original',identity_status='PASS')
        inputs=[row('Q3','20160930','20161115'),row('FY','20161231','20170403'),
                row('FUTURE','20161231','20170504'),row('TOOOLD','20160630','20160801')]
        self.assertEqual([r['receipt'] for r,k in plan(inputs,[],[],panel,'full')],['Q3','FY'])
    def test_technical_no_issuer_replacement(self):
        r=dict(receipt='r',isin='B',corp_code='c',kind_receipt='k',period_end='20210331',
               available_session='20210517',document='12345',version='original',identity_status='PASS')
        draws=[dict(isin='A',period_end='2021-03-31')]
        self.assertEqual(plan([r],draws,[],[],'technical'),[])

class AsOfAcquisitionTest(unittest.TestCase):
    def test_prior_reference_only_used_for_annual_but_never_as_primary(self):
        from stage9_panel.collection_targets import target_receipts
        with TemporaryDirectory() as directory:
            path=Path(directory)/'economic.sqlite'
            sessions=['20160104','20160401','20160404','20161114','20161115','20170403','20170404','20170502']
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE sessions(day TEXT)')
                db.executemany('INSERT INTO sessions VALUES(?)', [(d,) for d in sessions])
            def row(rc,period,stamp,available,report,identity):
                return dict(receipt=rc,isin='A',corp_code='00111111',stock_code='001234',
                            kind_receipt=rc,period_end=period,filing_date=stamp,available_session=available,
                            report_type=report,identity_status=identity,original_receipt=rc,version='original',
                            comparator_identity_status='PASS',comparator_identity_basis='dated_master_and_link')
            rows=[row('20151114000001','20150930','20151114','20160104','11013','BLOCKED'),
                  row('20160401000001','20151231','20160401','20160404','11011','PASS'),
                  row('20161114000001','20160930','20161114','20161115','11013','PASS'),
                  row('20170403000001','20161231','20170403','20170404','11011','PASS')]
            roster=[dict(formation='20170502',historical_isin='A')]
            coverage=[dict(formation='20170502',isin='A',complete='1')]
            self.assertEqual(target_receipts(rows,roster,path,coverage,[],[],[]),{r['receipt'] for r in rows})
            monthly_fin=[dict(formation='20170502',isin='A',industry_group='financial')]
            self.assertEqual(target_receipts(rows,roster,path,coverage,monthly_fin,[],[]),set())
