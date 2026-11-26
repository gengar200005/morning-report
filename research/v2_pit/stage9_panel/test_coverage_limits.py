import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from coverage_limits import ceiling, cfs_proofs, field_class, minimum_uncached_receipts, other_exclusions
from hashlib import sha256


class CoverageLimitTests(unittest.TestCase):
    def test_only_complete_version_with_explicit_public_display_can_be_subtracted(self):
        receipt,corp,period='20190513000321','12345678','20190331'
        kind_receipt,doc='20190513000111','20190513000444'
        row={'receipt':receipt,'corp_code':corp,'period_end':period,'original_receipt':receipt,'kind_receipt':kind_receipt,
             'identity_pass':'1','formation':'20190603','available_session':'20190514','F2':'','F2_reason':'revenue_no_exact_cfs_pair',
             'revenue_source_sha256':'','revenue_reason':'no_exact_cfs_pair'}
        base={'source_sha256':'a'*64,'explicit_no_cfs':True,'3':{},'receipt':receipt,'corp':corp,'period_end':'2019-03-31',
              'document':doc,'source_url':'https://kind.krx.co.kr/external/2019/05/13/000111/'+doc+'/11013.htm'}
        with TemporaryDirectory() as temp:
            db=Path(temp)/'facts.db'
            with sqlite3.connect(db) as c:
                c.execute('create table facts(receipt,kind,doc,corp,period,sha,evidence)')
                c.execute('insert into facts values(?,?,?,?,?,?,?)',(receipt,'kind_html',doc,corp,period,'a'*64,json.dumps(base)))
            evidence=cfs_proofs(db)
            self.assertEqual(field_class(row,'F2',evidence)[0],'explicit_no_cfs')
            self.assertEqual(field_class(row|{'identity_pass':'0'},'F2',evidence)[0],'index_incomplete_with_explicit_filing')
            self.assertEqual(field_class(row|{'kind_receipt':doc},'F2',evidence)[0],'pending_or_unproven')
            with sqlite3.connect(db) as c:
                c.execute('insert into facts values(?,?,?,?,?,?,?)',(receipt,'xbrl','202001',corp,period,'b'*64,
                          json.dumps({'source_sha256':'b'*64,'has_cfs_context':True})))
            self.assertEqual(field_class(row,'F2',cfs_proofs(db))[0],'pending_or_unproven')

    def test_threshold_equality_and_optimistic_all_unclassified(self):
        self.assertFalse(ceiling(100,20)['impossible_at_80pct'])
        self.assertTrue(ceiling(100,21)['impossible_at_80pct'])
        self.assertFalse(ceiling(105,21)['impossible_at_80pct'])
        self.assertFalse(ceiling(0,0)['impossible_at_80pct'])

    def test_optimistic_cost_groups_months_by_distinct_receipt(self):
        cost=minimum_uncached_receipts(100,5,{'p':10,'q':1,'r':7,'s':10})
        self.assertEqual(cost['free_success_assumption'],67)
        self.assertEqual(cost['minimum_uncached_latest_receipts'],2)
        self.assertIsNone(minimum_uncached_receipts(100,25,{'p':10})['minimum_uncached_latest_receipts'])

    def test_complete_negative_search_does_not_ignore_other_agency_or_same_day_lag(self):
        with TemporaryDirectory() as t:
            p=Path(t); (p/'parsed').mkdir();(p/'raw').mkdir()
            c=p/'monthly_coverage.csv'
            c.write_text('formation,isin,stock_code,complete,kind_window_complete,full_dart_list,corp_identity_evidenced\n20170502,i,c,1,1,1,1\n')
            q={'coverage_sha256':sha256(c.read_bytes()).hexdigest()}
            raw=b'index'; (p/'raw/D-c-ALL-p1.html').write_bytes(raw)
            idx=dict(code='c',count=1,start='20150101',end='20211201',records=[{'filing_date':'20170502'}],hashes=[sha256(raw).hexdigest()])
            (p/'parsed/D-c-ALL.json').write_text(json.dumps(idx))
            rows=[dict(formation='20170502',isin='i',corp_code='',stock_code='c',F3_reason='no_available_periodic_report',receipt='')]
            self.assertEqual(other_exclusions(p,rows,q)['20170502','i'][0],'complete_search_no_periodic_report')
            (p/'parsed/KP-test-p1.json').write_text(json.dumps({'records':[{'stock_code':'c','kind_timestamp':'2017-04-28 16:00'}]}))
            self.assertEqual(other_exclusions(p,rows,q),{})
            self.assertEqual(other_exclusions(p,rows,{'coverage_sha256':'other'}),{})

    def test_legal_formation_and_receipt_bind_to_security_and_prior_quarter(self):
        with TemporaryDirectory() as t:
            p=Path(t);(p/'raw').mkdir();(p/'parsed').mkdir()
            (p/'monthly_coverage.csv').write_text('formation,isin\n')
            body='<table><tr><th>설립일</th><td>2017-01-10</td><th>종목코드</th><td>123456</td></tr></table>'.encode()
            (p/'raw/ipo-123456-corp.html').write_bytes(body);(p/'raw/transfer-20170316000001.htm').write_bytes(b'ISINEXACT')
            legal=dict(isin='ISINEXACT',corp_code='12345678',stock_code='123456',established='20170110',
                       registry_sha256=sha256(body).hexdigest(),official_listing=[dict(kind='20170316000001',date='2017-03-16',
                       body_sha256=sha256(b'ISINEXACT').hexdigest())])
            (p/'prelisting_proof.json').write_text(json.dumps([legal]))
            row=dict(isin='ISINEXACT',stock_code='123456',corp_code='12345678',formation='20180502',receipt='src',original_receipt='src',
                     kind_receipt='k',available_session='20180102',identity_pass='1',period_end='20180331',comparison_basis_status='BLOCKED',F3='',
                     F3_reason='issuer_not_yet_established_for_full_prior_three_months')
            ex=other_exclusions(p,[row],{'coverage_sha256':'unused'})['20180502','ISINEXACT']
            self.assertEqual(ex[1]['prior_quarter_start'],'20170101')
            self.assertEqual(field_class(row,'F3',{},ex)[0],'confirmed_issuer_not_established')
            self.assertEqual(field_class(row,'F3',{('src','12345678','20180331'):[('k','hash')]},ex)[0],'explicit_no_cfs')
            self.assertEqual(other_exclusions(p,[row|{'period_end':'20180630'}],{'coverage_sha256':'unused'}),{})
