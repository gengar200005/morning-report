import copy
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from foundation import ROOT, bar_state, load_month


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fixture.json.gz'
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript((ROOT / 'schema.sql').read_text())
        self.day = '20160104'
        self.basic = dict(ISU_CD='KR7000000000', ISU_SRT_CD='0A0000',
                          LIST_DD=self.day, MKT_TP_NM='KOSPI',
                          SECUGRP_NM='주권', KIND_STKCERT_TP_NM='보통주',
                          ISU_ABBRV='Fixture')
        self.daily = dict(ISU_CD='0A0000', MKT_NM='KOSPI', BAS_DD=self.day,
                          TDD_OPNPRC='100', TDD_HGPRC='101', TDD_LWPRC='99',
                          TDD_CLSPRC='100', ACC_TRDVOL='1')

    def load(self, records, calendar=None):
        with gzip.open(self.path, 'wt') as stream:
            json.dump(dict(schema=1, source='KRX OPEN API', year=2016, month=1,
                           records=records), stream)
        load_month(self.db, self.path, 2016, 1, calendar or [self.day])

    def test_reused_code_uses_dated_isin_and_keeps_disappeared_security(self):
        following = '20160105'
        second = dict(self.basic, ISU_CD='KR7000000001', LIST_DD=following)
        self.load([dict(date=self.day, basic=[self.basic], daily=[self.daily]),
                   dict(date=following, basic=[second],
                        daily=[dict(self.daily, BAS_DD=following)])], [self.day, following])
        self.db.executescript((ROOT / 'views.sql').read_text())
        self.assertEqual(self.db.execute('SELECT count(*) FROM securities').fetchone(), (2,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM signal_prices').fetchone(), (0,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM provenance').fetchone(), (1,))

    def test_future_listing_rejected(self):
        rec = dict(date=self.day, daily=[self.daily],
                   basic=[dict(self.basic, LIST_DD='20160105')])
        with self.assertRaisesRegex(ValueError, 'pre-listing'):
            self.load([rec])

    def test_endpoint_mismatch_rejected(self):
        rec = dict(date=self.day, basic=[self.basic], daily=[dict(self.daily, ISU_CD='000001')])
        with self.assertRaisesRegex(ValueError, 'endpoints disagree'):
            self.load([rec])

    def test_duplicate_session_rejected(self):
        rec = dict(date=self.day, basic=[self.basic], daily=[self.daily])
        with self.assertRaisesRegex(ValueError, 'calendar mismatch'):
            self.load([rec, copy.deepcopy(rec)])

    def test_zero_volume_and_invalid_bar_are_distinct(self):
        self.assertEqual(bar_state(0, 0, 0, 100, 0), 'ZERO_VOLUME')
        self.assertEqual(bar_state(100, 99, 90, 100, 10), 'INVALID_BAR')
        self.assertEqual(bar_state(100, 110, 90, 100, 10), 'POSITIVE_VOLUME_VALID_BAR')

    def test_signal_with_future_availability_rejected(self):
        self.load([dict(date=self.day, basic=[self.basic], daily=[self.daily])])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO signal_prices VALUES (?,?,?,?,?)',
                            (self.day, self.basic['ISU_CD'], 100, '20160105', self.path.name))


if __name__ == '__main__':
    unittest.main()
