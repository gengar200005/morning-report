import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from coverage_limits import ceiling, cfs_proofs, field_class


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
